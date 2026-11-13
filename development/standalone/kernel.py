#!/usr/bin/env python3
"""Build and audit ram116 from a pristine archive and versioned source inputs.

The build never consults a previous profile, its rootfs, a source work tree,
device backups, or historical validation logs. It performs host-only checks;
successful compilation does not qualify this new image on hardware.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "kernel"))
from common import fdt_nodes  # Pure FDT parser, no artifact reads at import.

IDENTITY = "6.18.48-perrier-ram116"
PROFILE = "cpu-dvfs-mid-trial"
MAX_KERNEL_SPAN = 0x02000000


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(arguments, log: Path, *, env=None, stdout=None) -> None:
    command = [str(arg) for arg in arguments]
    with log.open("a") as stream:
        stream.write("$ " + " ".join(command) + "\n")
        stream.flush()
        result = subprocess.run(command, env=env,
                                stdout=stdout if stdout is not None else stream,
                                stderr=stream)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); see {log}: {command[0]}")


def parse_config(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def _inputs(root: Path) -> tuple[dict, dict, list[Path], str]:
    canonical = root / "development/kernel"
    profile = root / "development/standalone/kernel"
    base = json.loads((canonical / "patches/manifest.json").read_text())
    extra = json.loads((profile / "manifest.json").read_text())
    assert base["base_version"] == extra["upstream_version"] == "6.18.48"
    assert base["base_archive_sha256"] == extra["base_archive_sha256"]
    series = (canonical / "patches/series").read_text().splitlines()
    assert series == list(base["patches"]), "Canonical patch order differs from manifest"
    paths = []
    for name in series:
        path = canonical / "patches" / name
        assert sha(path) == base["patches"][name], "Changed canonical patch: " + name
        paths.append(path)
    for name, entry in base["files"].items():
        assert sha(canonical / "source" / name) == entry["after_sha256"], name
    supplemental = profile / extra["supplemental_patch"]
    assert sha(supplemental) == extra["supplemental_patch_sha256"]
    assert sha(profile / "ram116.config") == extra["config_sha256"]
    for name, digest in extra["dt_sources"].items():
        assert sha(root / name) == digest, "Changed ram116 DT source: " + name
    paths.append(supplemental)
    recipe = hashlib.sha256(json.dumps({
        "archive": base["base_archive_sha256"],
        "patches": [sha(path) for path in paths],
    }, sort_keys=True).encode()).hexdigest()
    return base, extra, paths, recipe


def verify_source(root: Path, output: Path) -> dict:
    base, extra, _, recipe = _inputs(root)
    source = output / "kernel-source"
    marker = json.loads((output / "kernel-source.json").read_text())
    assert marker["recipe_sha256"] == recipe, "Kernel source recipe changed; use a clean output directory"
    expected = {name: item["after_sha256"] for name, item in base["files"].items()}
    expected.update({name: item["after_sha256"] for name, item in extra["files"].items()})
    for name, digest in expected.items():
        assert sha(source / name) == digest, "Changed prepared kernel source: " + name
    return marker


def prepare(root: Path, output: Path, archive: Path | None = None) -> dict:
    """Unpack verified Linux and apply the complete versioned ram116 patches."""
    root, output = Path(root).resolve(), Path(output).resolve()
    archive = Path(archive or root / "development/sources/linux-6.18.48.tar.xz").resolve()
    base, extra, patches, recipe = _inputs(root)
    assert sha(archive) == base["base_archive_sha256"], "Unexpected Linux source archive"
    output.mkdir(parents=True, exist_ok=True)
    source = output / "kernel-source"
    if source.exists():
        return verify_source(root, output)
    log = output / "kernel-prepare.log"
    print("Preparing pristine Linux 6.18.48 and ram116 source patches", flush=True)
    with tempfile.TemporaryDirectory(prefix=".kernel-unpack-", dir=output) as temporary:
        with tarfile.open(archive, "r:xz") as package:
            # Python's data filter rejects escaping links, traversal and devices.
            for member in package.getmembers():
                assert member.name == "linux-6.18.48" or member.name.startswith("linux-6.18.48/"), member.name
            package.extractall(temporary, filter="data")
        (Path(temporary) / "linux-6.18.48").rename(source)
    for patch in patches:
        run(["patch", "--batch", "--forward", "-d", source, "-p1", "-i", patch], log)
    record = {
        "kernel": IDENTITY,
        "recipe_sha256": recipe,
        "archive_sha256": base["base_archive_sha256"],
        "patches": [{"path": str(path.relative_to(root)), "sha256": sha(path)} for path in patches],
        "previous_artifacts_required": False,
    }
    (output / "kernel-source.json").write_text(json.dumps(record, indent=2) + "\n")
    return verify_source(root, output)


def check_config(path: Path) -> dict:
    config = parse_config(path)
    required = ["SMP", "CPU_FREQ", "CPUFREQ_DT", "CPU_FREQ_GOV_USERSPACE",
                "CPU_FREQ_GOV_SCHEDUTIL", "CPU_FREQ_DEFAULT_GOV_PERFORMANCE",
                "REGULATOR_CISCO_PERRIER_VC", "OMAP_WATCHDOG", "WATCHDOG_NOWAYOUT",
                "TOUCHSCREEN_CYTTSP4", "DRM_OMAP", "BLK_DEV_INITRD", "MMC_BLOCK",
                "CMDLINE_FORCE", "TWL6030_GPADC", "ARM_PMU"]
    for name in required:
        assert config.get("CONFIG_" + name) == "y", "Required RAM image option: " + name
    for name in ("HOTPLUG_CPU", "POWER_AVS_OMAP", "ARM_OMAP2PLUS_CPUFREQ", "ARM_TI_CPUFREQ",
                 "RTC_HCTOSYS", "RTC_SYSTOHC"):
        assert config.get("CONFIG_" + name) != "y", "Unsafe RAM image option: " + name
    assert config["CONFIG_NR_CPUS"] == "2"
    assert config["CONFIG_LOCALVERSION"] == '"-perrier-ram116"'
    cmdline = config["CONFIG_CMDLINE"].strip('"')
    assert "initcall_blacklist=omap2_common_pm_late_init" in cmdline
    assert "omap_wdt.early_enable=1" in cmdline and "omap_wdt.timer_margin=120" in cmdline
    assert "maxcpus=" not in cmdline and "root=" not in cmdline
    assert config["CONFIG_INITRAMFS_SOURCE"] != '""'
    return {"required_options": required, "smp_cpus": 2,
            "watchdog_nowayout": True, "generic_omap_pm_late_init_blacklisted": True}


def check_dtb(path: Path) -> dict:
    nodes = fdt_nodes(path.read_bytes())

    def cell(raw):
        assert len(raw) == 4
        return struct.unpack(">I", raw)[0]

    assert b"cisco,perrier-ram\0" in nodes["/"]["compatible"]
    assert nodes["/memory@80000000"]["reg"] == struct.pack(">II", 0x80000000, 0x19000000)
    supply = "/regulator@4a306000"
    p = nodes[supply]
    assert p["compatible"] == b"cisco,perrier-omap4-mpu-vc\0"
    assert p["reg"] == struct.pack(">II", 0x4a306000, 0x2000)
    assert p["regulator-name"] == b"perrier-vdd-mpu\0"
    assert cell(p["regulator-min-microvolt"]) == 1152100
    assert cell(p["regulator-max-microvolt"]) == 1215400
    assert "regulator-always-on" in p
    handles = {cell(props["phandle"]): name for name, props in nodes.items() if "phandle" in props}
    mpu_clock = handles[cell(nodes["/cpus/cpu@0"]["clocks"])]
    assert mpu_clock.rsplit("/", 1)[-1].startswith("dpll_mpu_m2_ck@"), "CPUfreq must use the inherited M2 divider"
    for cpu in ("/cpus/cpu@0", "/cpus/cpu@1"):
        assert nodes[cpu].get("status", b"okay\0") == b"okay\0"
        assert handles[cell(nodes[cpu]["cpu-supply"])] == supply
        assert handles[cell(nodes[cpu]["operating-points-v2"])] == "/opp-table-cpu"
    points = {name for name in nodes if name.startswith("/opp-table-cpu/opp-")}
    assert points == {"/opp-table-cpu/opp-350000000", "/opp-table-cpu/opp-700000000"}
    for hz, uv in ((350000000, 1152100), (700000000, 1215400)):
        p = nodes[f"/opp-table-cpu/opp-{hz}"]
        assert p["opp-hz"] == struct.pack(">Q", hz)
        assert cell(p["opp-microvolt"]) == uv
    watchdogs = [props for name, props in nodes.items()
                 if name.endswith("/wdt@0") and cell(props.get("timeout-sec", bytes(4))) == 120
                 and props.get("status", b"okay\0") == b"okay\0"]
    assert len(watchdogs) == 1
    assert any(p.get("compatible") == b"cisco,perrier-cyttsp4\0" for p in nodes.values())
    assert cell(nodes["/panel/panel-timing"]["hactive"]) == 1280
    assert cell(nodes["/panel/panel-timing"]["vactive"]) == 800
    assert cell(nodes["/thermal-zones/cpu_thermal/trips/cpu_alert"]["temperature"]) == 85000
    assert cell(nodes["/thermal-zones/cpu_thermal/trips/cpu_crit"]["temperature"]) == 95000
    return {"opp_hz_uv": [[350000000, 1152100], [700000000, 1215400]],
            "mpu_selectors": ["0x24", "0x29"], "smp_cpus_enabled": 2,
            "watchdog_timeout_seconds": 120, "panel_pixels": [1280, 800],
            "cpu_thermal_passive_critical_millicelsius": [85000, 95000]}


def audit(root: Path, output: Path, initramfs: Path) -> dict:
    """Audit source, RAM safeguards, DT and the newly linked embedded archive."""
    verify_source(root, output)
    source, build_dir = output / "kernel-source", output / "kernel-build"
    config = check_config(build_dir / ".config")
    assert parse_config(build_dir / ".config")["CONFIG_INITRAMFS_SOURCE"] == json.dumps(str(initramfs))
    dtb = check_dtb(output / "board.dtb")
    packed = (build_dir / "usr/initramfs_inc_data").read_bytes()
    assert gzip.decompress(packed) == initramfs.read_bytes(), "Embedded initramfs differs from fresh archive"
    assert packed in (build_dir / "vmlinux").read_bytes()
    symbols = (build_dir / "System.map").read_text().splitlines()
    end = next(int(line.split()[0], 16) for line in symbols if line.endswith(" _end"))
    span = end - 0xc0000000
    assert 0 < span < MAX_KERNEL_SPAN, "Kernel exceeds the reviewed RAM load window"
    assert any(line.endswith(" perrier_vc_probe") for line in symbols)
    driver = (source / "drivers/regulator/cisco-perrier-vc.c").read_text()
    assert "static const unsigned int perrier_mpu_selectors[] = { 0x24, 0x29 };" in driver
    assert "VC_COMMAND(perrier_mpu_selectors[selector])" in driver
    assert "!(observed & VC_VALID)" in driver and "(status & VC_STATUS) != VC_ACK" in driver
    assert "perrier_vc_state_valid(vc)" in driver
    mmc = (source / "drivers/mmc/core/block.c").read_text()
    assert 'if (of_machine_is_compatible("cisco,perrier-ram"))\n\t\tmd->read_only = 1;' in mmc
    image = build_dir / "arch/arm/boot/zImage"
    assert image.stat().st_size < MAX_KERNEL_SPAN, "Compressed kernel exceeds the reviewed RAM load window"
    with image.open("rb") as stream:
        header = stream.read(0x30)
    assert struct.unpack_from("<I", header, 0x24)[0] == 0x016f2818, "Invalid ARM zImage header"
    artifacts = {"zImage": image, "board.dtb": output / "board.dtb",
                 "kernel.config": output / "kernel.config", "initramfs.cpio": initramfs}
    report = {
        "passed": True, "scope": "host build and static image audit",
        "kernel": IDENTITY, "profile": PROFILE, "live_tested": False,
        "previous_artifacts_required": False, "kernel_span_bytes": span,
        "config_audit": config, "dtb_audit": dtb,
        "emmc_write_opens_forced_readonly": True, "embedded_initramfs_verified": True,
        "artifacts": {name: {"path": str(path.relative_to(output)) if path.is_relative_to(output) else str(path),
                             "size": path.stat().st_size, "sha256": sha(path)} for name, path in artifacts.items()},
        "compiler": subprocess.check_output(["clang", "--version"], text=True).splitlines()[0],
        "dt_sources": json.loads((root / "development/standalone/kernel/manifest.json").read_text())["dt_sources"],
    }
    (output / "kernel-build.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def build(root: Path, output: Path, initramfs: Path, *, archive: Path | None = None) -> dict:
    root, output, initramfs = Path(root).resolve(), Path(output).resolve(), Path(initramfs).resolve()
    assert initramfs.is_file(), "Build a fresh rootfs archive first"
    prepare(root, output, archive)
    source, build_dir = output / "kernel-source", output / "kernel-build"
    build_dir.mkdir(exist_ok=True)
    profile = root / "development/standalone/kernel"
    log = output / "kernel-build.log"
    shutil.copy2(profile / "ram116.config", build_dir / ".config")
    run([source / "scripts/config", "--file", build_dir / ".config",
         "--set-str", "INITRAMFS_SOURCE", initramfs], log)
    make = ["make", "-C", source, f"O={build_dir}", "ARCH=arm", "LLVM=1"]
    env = dict(os.environ, KBUILD_BUILD_USER="touch10", KBUILD_BUILD_HOST="perrier-dev",
               KBUILD_BUILD_TIMESTAMP="2026-11-13 00:00:00 UTC")
    print("Configuring ram116 kernel", flush=True)
    run(make + ["olddefconfig"], log, env=env)
    check_config(build_dir / ".config")
    shutil.copy2(build_dir / ".config", output / "kernel.config")
    print("Compiling ram116 kernel (log: " + str(log) + ")", flush=True)
    # This is GNU Make, not Ninja. Use the available CPUs as historical builds do.
    run(make + ["-j" + str(os.cpu_count() or 1), "zImage"], log, env=env)
    dt_source = root / "development/kernel/power/omap4-cisco-perrier-cpu-dvfs-mid-ram.dts"
    include = source / "arch/arm/boot/dts/ti/omap"
    with (output / "board.pre.dts").open("w") as stream:
        run(["cpp", "-x", "assembler-with-cpp", "-P", "-nostdinc", "-undef", "-D__DTS__",
             "-I", source / "include", "-I", include,
             "-I", root / "development/kernel/source/arch/arm/boot/dts/ti/omap", dt_source],
            log, stdout=stream)
    run(["dtc", "-q", "-I", "dts", "-O", "dtb", "-i", include,
         "-o", output / "board.dtb", output / "board.pre.dts"], log)
    print("Auditing freshly built ram116 image", flush=True)
    return audit(root, output, initramfs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=HERE.parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--initramfs", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    output = args.output or args.root / "development/standalone/out/ram116"
    if args.prepare_only:
        result = prepare(args.root, output, args.archive)
    else:
        result = build(args.root, output, args.initramfs or output / "initramfs.cpio", archive=args.archive)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
