#!/usr/bin/env python3
"""Build an isolated 350/700 MHz, fixed-voltage CPUfreq RAM candidate.

All outputs remain on the host. This script never contacts the Touch 10.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
KERNEL = ROOT / "development/kernel"
SRC = KERNEL / "work/linux-6.18.48"
UPSTREAM = ROOT / "development/sources/linux-6.18.48"
BASE = ROOT / "development/perrier-ramenv/smp-boot-two"
DEST = ROOT / "development/perrier-ramenv/cpu-m2-trial"
FS = DEST / "rootfs"
OUT = DEST / "kernel-build"
sys.path.insert(0, str(KERNEL))
from common import audit_archive, cpio_entry


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*argv: object, env: dict[str, str] | None = None) -> None:
    subprocess.run([str(arg) for arg in argv], env=env, check=True)


def pack_rootfs(previous: dict) -> None:
    old_entries = json.loads((BASE / "rootfs-manifest.json").read_text())
    assert digest(BASE / "rootfs-manifest.json") == previous["rootfs_manifest_sha256"]
    for name, item in old_entries.items():
        path = BASE / "rootfs" / name
        if "symlink" in item:
            assert path.is_symlink() and str(path.readlink()) == item["symlink"]
        else:
            assert digest(path) == item["sha256"] and path.stat().st_size == item["bytes"]
    if FS.exists():
        shutil.rmtree(FS)
    shutil.copytree(BASE / "rootfs", FS, symlinks=True)
    startup = (FS / "etc/init.d/rcS").read_text()
    assert startup.count("ram110") == 2
    (FS / "etc/init.d/rcS").write_text(startup.replace("ram110", "ram112"))
    entries: dict[str, dict] = {}
    chunks = []
    for path in sorted(FS.rglob("*")):
        name = str(path.relative_to(FS))
        if path.is_symlink():
            target = str(path.readlink())
            chunks.append(cpio_entry(name, stat.S_IFLNK | 0o777, target.encode()))
            entries[name] = {"symlink": target}
        elif path.is_dir():
            chunks.append(cpio_entry(name, stat.S_IFDIR | stat.S_IMODE(path.stat().st_mode)))
        else:
            data = path.read_bytes()
            chunks.append(cpio_entry(name, stat.S_IFREG | stat.S_IMODE(path.stat().st_mode), data))
            entries[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            if name != "etc/init.d/rcS":
                assert entries[name] == old_entries[name], name
    chunks.extend((cpio_entry("dev/console", stat.S_IFCHR | 0o600, major=5, minor=1),
                   cpio_entry("dev/null", stat.S_IFCHR | 0o666, major=1, minor=3),
                   cpio_entry("TRAILER!!!", 0)))
    image = DEST / "initramfs.cpio"
    temporary = image.with_suffix(".cpio.new")
    expected = hashlib.sha256()
    with temporary.open("wb") as stream:
        for chunk in chunks:
            stream.write(chunk)
            expected.update(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    assert digest(temporary) == expected.hexdigest()
    audit_archive(temporary, entries)
    temporary.replace(image)
    (DEST / "rootfs-manifest.json").write_text(json.dumps(entries, indent=2) + "\n")
    assert {name for name in old_entries if old_entries[name] != entries[name]} == {"etc/init.d/rcS"}


def build_dtb() -> None:
    source = HERE / "omap4-cisco-perrier-cpu-m2-ram.dts"
    preprocessed = DEST / "board.pre.dts"
    candidate = DEST / "board.dtb"
    with preprocessed.open("w") as stream:
        subprocess.run([
            "cpp", "-x", "assembler-with-cpp", "-P", "-nostdinc", "-undef",
            "-D__DTS__", "-I", str(UPSTREAM / "include"),
            "-I", str(UPSTREAM / "arch/arm/boot/dts/ti/omap"),
            "-I", str(KERNEL / "source/arch/arm/boot/dts/ti/omap"),
            str(source),
        ], stdout=stream, check=True)
    run("dtc", "-q", "-I", "dts", "-O", "dtb",
        "-i", UPSTREAM / "arch/arm/boot/dts/ti/omap", "-o", candidate,
        preprocessed)


def build_kernel() -> None:
    OUT.mkdir(exist_ok=True)
    shutil.copy2(BASE / "kernel-build/.config", OUT / ".config")
    base_cmdline = next(line.split("=", 1)[1].strip('"') for line in
                        (BASE / "kernel-build/.config").read_text().splitlines()
                        if line.startswith("CONFIG_CMDLINE="))
    assert "maxcpus=" not in base_cmdline
    assert "initcall_blacklist=omap2_common_pm_late_init" in base_cmdline
    run(SRC / "scripts/config", "--file", OUT / ".config",
        "--set-str", "LOCALVERSION", "-perrier-ram112",
        "--set-str", "INITRAMFS_SOURCE", DEST / "initramfs.cpio",
        "--set-str", "CMDLINE", base_cmdline + " maxcpus=1",
        "--enable", "CPU_FREQ", "--enable", "CPUFREQ_DT",
        "--enable", "CPU_FREQ_GOV_USERSPACE", "--enable", "CPU_FREQ_STAT",
        "--enable", "CPU_FREQ_DEFAULT_GOV_PERFORMANCE",
        "--disable", "ARM_OMAP2PLUS_CPUFREQ", "--disable", "ARM_TI_CPUFREQ",
        "--disable", "POWER_AVS_OMAP")
    make = ["make", "-C", SRC, f"O={OUT}", "ARCH=arm", "LLVM=1"]
    env = dict(os.environ, KBUILD_BUILD_USER="touch10", KBUILD_BUILD_HOST="perrier-dev",
               KBUILD_BUILD_TIMESTAMP="2026-11-13 00:00:00 UTC")
    run(*make, "olddefconfig", env=env)
    shutil.copy2(OUT / ".config", DEST / "kernel.config")
    run(*make, "-j" + str(os.cpu_count() or 1), "zImage", env=env)


def main() -> None:
    os.umask(0o077)
    base = json.loads((BASE / "reviewed-image.json").read_text())
    previous = json.loads((BASE / "manifest.json").read_text())
    assert base["passed"] and base["kernel"] == previous["kernel"] == "6.18.48-perrier-ram110"
    assert base["profile"] == "smp-boot-two"
    for item in base["artifacts"].values():
        path = Path(item["path"])
        assert path.stat().st_size == item["size"] and digest(path) == item["sha256"]
    proof = json.loads((ROOT / "development/perrier-ramenv/native-watchdog/watchdog-proof.json").read_text())
    assert proof["status"] == "passed" and proof["stock_recovered"]
    assert proof["guard_sha256"] == base["guard_sha256"]
    DEST.mkdir(exist_ok=True)
    pack_rootfs(previous)
    build_dtb()
    archive_hash = digest(DEST / "initramfs.cpio")
    build_kernel()
    assert digest(DEST / "initramfs.cpio") == archive_hash
    artifacts = {"zImage": OUT / "arch/arm/boot/zImage", "board.dtb": DEST / "board.dtb"}
    inputs = {"base_review": BASE / "reviewed-image.json",
              "base_manifest": BASE / "manifest.json",
              "watchdog_proof": ROOT / "development/perrier-ramenv/native-watchdog/watchdog-proof.json",
              "candidate_dts": HERE / "omap4-cisco-perrier-cpu-m2-ram.dts",
              "thermal_dts": HERE / "omap4-cisco-perrier-thermal-ram.dts",
              "board_dtsi": KERNEL / "source/arch/arm/boot/dts/ti/omap/omap4-cisco-perrier.dtsi",
              "source_manifest": KERNEL / "patches/manifest.json"}
    manifest = {
        "kernel": "6.18.48-perrier-ram112", "profile": "cpu-m2-trial",
        "artifacts": {name: {"path": str(path), "size": path.stat().st_size,
                             "sha256": digest(path)} for name, path in artifacts.items()},
        "inputs": {name: {"path": str(path), "sha256": digest(path)} for name, path in inputs.items()},
        "rootfs_manifest_sha256": digest(DEST / "rootfs-manifest.json"),
        "initramfs_sha256": archive_hash,
        "kernel_config_sha256": digest(OUT / ".config"),
        "guard_sha256": digest(FS / "usr/sbin/ram-guard"),
        "watchdog_backend": "linux-watchdog",
        "voltage_policy": "fixed inherited MLO rails; no CPU supply or regulator transition",
        "live_tested": False,
    }
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"built": True, "kernel": manifest["kernel"],
                      "zImage_sha256": manifest["artifacts"]["zImage"]["sha256"],
                      "dtb_sha256": manifest["artifacts"]["board.dtb"]["sha256"]}, indent=2))


if __name__ == "__main__":
    main()
