#!/usr/bin/env python3
"""Build an isolated ram114 350/700 MHz OPP and MPU VC regulator candidate."""
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
BASE = ROOT / "development/perrier-ramenv/cpu-m2-smp-safe"
DEST = ROOT / "development/perrier-ramenv/cpu-dvfs-trial"
FS = DEST / "rootfs"
OUT = DEST / "kernel-build"
sys.path.insert(0, str(KERNEL))
from common import audit_archive, cpio_entry


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*argv: object, env: dict[str, str] | None = None) -> None:
    subprocess.run([str(arg) for arg in argv], env=env, check=True)


def pack_rootfs() -> None:
    previous = json.loads((BASE / "rootfs-manifest.json").read_text())
    for name, item in previous.items():
        path = BASE / "rootfs" / name
        if "symlink" in item:
            assert path.is_symlink() and str(path.readlink()) == item["symlink"]
        else:
            assert path.stat().st_size == item["bytes"] and sha(path) == item["sha256"]
    if FS.exists():
        shutil.rmtree(FS)
    shutil.copytree(BASE / "rootfs", FS, symlinks=True)
    startup = FS / "etc/init.d/rcS"
    text = startup.read_text()
    assert text.count("ram113") == 2
    startup.write_text(text.replace("ram113", "ram114"))
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
                assert entries[name] == previous[name], name
    chunks.extend((cpio_entry("dev/console", stat.S_IFCHR | 0o600, major=5, minor=1),
                   cpio_entry("dev/null", stat.S_IFCHR | 0o666, major=1, minor=3),
                   cpio_entry("TRAILER!!!", 0)))
    image = DEST / "initramfs.cpio"
    temporary = image.with_suffix(".cpio.new")
    with temporary.open("wb") as stream:
        for chunk in chunks:
            stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    audit_archive(temporary, entries)
    temporary.replace(image)
    (DEST / "rootfs-manifest.json").write_text(json.dumps(entries, indent=2) + "\n")
    assert {name for name in previous if previous[name] != entries[name]} == {"etc/init.d/rcS"}


def build_dtb() -> None:
    source = HERE / "omap4-cisco-perrier-cpu-dvfs-ram.dts"
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
    run(SRC / "scripts/config", "--file", OUT / ".config",
        "--set-str", "LOCALVERSION", "-perrier-ram114",
        "--set-str", "INITRAMFS_SOURCE", DEST / "initramfs.cpio",
        "--enable", "REGULATOR_CISCO_PERRIER_VC")
    make = ["make", "-C", SRC, f"O={OUT}", "ARCH=arm", "LLVM=1"]
    env = dict(os.environ, KBUILD_BUILD_USER="touch10", KBUILD_BUILD_HOST="perrier-dev",
               KBUILD_BUILD_TIMESTAMP="2026-11-13 00:00:00 UTC")
    run(*make, "olddefconfig", env=env)
    config = (OUT / ".config").read_text()
    assert "CONFIG_REGULATOR_CISCO_PERRIER_VC=y\n" in config
    shutil.copy2(OUT / ".config", DEST / "kernel.config")
    run(*make, "-j" + str(os.cpu_count() or 1), "zImage", env=env)


def main() -> None:
    os.umask(0o077)
    base = json.loads((BASE / "reviewed-image.json").read_text())
    live = json.loads((KERNEL / "validation-cpu-m2-smp-safe.json").read_text())
    vc_runs = [json.loads((ROOT / "development/runs" / name / "result.json").read_text())
               for name in ("20261113T155643Z-ram113-mpu-vc-step",
                            "20261113T160032Z-ram113-mpu-vc-step")]
    assert base["passed"] and base["kernel"] == "6.18.48-perrier-ram113"
    assert live["status"] == "passed"
    assert all(run["passed"] and run["transport_acknowledged"] and
               run["rail_drop_observed_mv"] >= 8 for run in vc_runs)
    assert vc_runs[1]["two_core_load"]
    for item in base["artifacts"].values():
        path = Path(item["path"])
        assert path.stat().st_size == item["size"] and sha(path) == item["sha256"]
    DEST.mkdir(exist_ok=True)
    pack_rootfs()
    build_dtb()
    build_kernel()
    artifacts = {"zImage": OUT / "arch/arm/boot/zImage", "board.dtb": DEST / "board.dtb"}
    inputs = {"base_review": BASE / "reviewed-image.json",
              "cpu_m2_validation": KERNEL / "validation-cpu-m2-smp-safe.json",
              "candidate_dts": HERE / "omap4-cisco-perrier-cpu-dvfs-ram.dts",
              "driver": SRC / "drivers/regulator/cisco-perrier-vc.c",
              "regulator_kconfig": SRC / "drivers/regulator/Kconfig",
              "regulator_makefile": SRC / "drivers/regulator/Makefile",
              "vc_idle_result": ROOT / "development/runs/20261113T155643Z-ram113-mpu-vc-step/result.json",
              "vc_loaded_result": ROOT / "development/runs/20261113T160032Z-ram113-mpu-vc-step/result.json",
              "vc_idle_recovery": ROOT / "development/runs/20261113T155524Z-uboot-ram113-99c94f/result.json",
              "vc_loaded_recovery": ROOT / "development/runs/20261113T155918Z-uboot-ram113-258b20/result.json",
              "source_manifest": KERNEL / "patches/manifest.json"}
    manifest = {
        "kernel": "6.18.48-perrier-ram114", "profile": "cpu-dvfs-trial",
        "artifacts": {name: {"path": str(path), "size": path.stat().st_size,
                             "sha256": sha(path)} for name, path in artifacts.items()},
        "inputs": {name: {"path": str(path), "sha256": sha(path)} for name, path in inputs.items()},
        "rootfs_manifest_sha256": sha(DEST / "rootfs-manifest.json"),
        "initramfs_sha256": sha(DEST / "initramfs.cpio"),
        "kernel_config_sha256": sha(OUT / ".config"),
        "guard_sha256": sha(FS / "usr/sbin/ram-guard"),
        "watchdog_backend": "linux-watchdog",
        "voltage_policy": "CPU OPP 350 MHz/1202740 uV and 700 MHz/1215400 uV; VC bypass only",
        "live_tested": False,
    }
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"built": True, "kernel": manifest["kernel"],
                      "zImage_sha256": manifest["artifacts"]["zImage"]["sha256"],
                      "dtb_sha256": manifest["artifacts"]["board.dtb"]["sha256"]}, indent=2))


if __name__ == "__main__":
    main()
