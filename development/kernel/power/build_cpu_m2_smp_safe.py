#!/usr/bin/env python3
"""Build a RAM-only two-core CPUfreq image without runtime CPU hotplug.

Host-only preparation. This does not stage files or change the Touch 10.
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
KERNEL = ROOT / "development/kernel"
SRC = KERNEL / "work/linux-6.18.48"
BASE = ROOT / "development/perrier-ramenv/cpu-m2-trial"
DEST = ROOT / "development/perrier-ramenv/cpu-m2-smp-safe"
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
    assert text.count("ram112") == 2
    startup.write_text(text.replace("ram112", "ram113"))
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


def build_kernel() -> None:
    OUT.mkdir(exist_ok=True)
    shutil.copy2(BASE / "kernel-build/.config", OUT / ".config")
    old_cmdline = next(line.split("=", 1)[1].strip('"') for line in
                       (BASE / "kernel-build/.config").read_text().splitlines()
                       if line.startswith("CONFIG_CMDLINE="))
    assert old_cmdline.endswith(" maxcpus=1")
    run(SRC / "scripts/config", "--file", OUT / ".config",
        "--set-str", "LOCALVERSION", "-perrier-ram113",
        "--set-str", "INITRAMFS_SOURCE", DEST / "initramfs.cpio",
        "--set-str", "CMDLINE", old_cmdline.removesuffix(" maxcpus=1"),
        "--disable", "HOTPLUG_CPU",
        "--enable", "CPU_FREQ_GOV_SCHEDUTIL")
    make = ["make", "-C", SRC, f"O={OUT}", "ARCH=arm", "LLVM=1"]
    env = dict(os.environ, KBUILD_BUILD_USER="touch10", KBUILD_BUILD_HOST="perrier-dev",
               KBUILD_BUILD_TIMESTAMP="2026-11-13 00:00:00 UTC")
    run(*make, "olddefconfig", env=env)
    shutil.copy2(OUT / ".config", DEST / "kernel.config")
    run(*make, "-j" + str(os.cpu_count() or 1), "zImage", env=env)


def main() -> None:
    os.umask(0o077)
    base = json.loads((BASE / "reviewed-image.json").read_text())
    observed = json.loads((KERNEL / "validation-cpu-m2-trial.json").read_text())
    assert base["passed"] and base["kernel"] == "6.18.48-perrier-ram112"
    assert observed["clock_transition"]["passed"] and not observed["hotplug_cleanup"]["passed"]
    for item in base["artifacts"].values():
        path = Path(item["path"])
        assert path.stat().st_size == item["size"] and sha(path) == item["sha256"]
    DEST.mkdir(exist_ok=True)
    pack_rootfs()
    shutil.copy2(BASE / "board.dtb", DEST / "board.dtb")
    build_kernel()
    artifacts = {"zImage": OUT / "arch/arm/boot/zImage", "board.dtb": DEST / "board.dtb"}
    inputs = {"base_review": BASE / "reviewed-image.json",
              "base_manifest": BASE / "manifest.json",
              "cpu_m2_validation": KERNEL / "validation-cpu-m2-trial.json",
              "watchdog_proof": ROOT / "development/perrier-ramenv/native-watchdog/watchdog-proof.json",
              "source_manifest": KERNEL / "patches/manifest.json"}
    manifest = {
        "kernel": "6.18.48-perrier-ram113", "profile": "cpu-m2-smp-safe",
        "artifacts": {name: {"path": str(path), "size": path.stat().st_size,
                             "sha256": sha(path)} for name, path in artifacts.items()},
        "inputs": {name: {"path": str(path), "sha256": sha(path)} for name, path in inputs.items()},
        "rootfs_manifest_sha256": sha(DEST / "rootfs-manifest.json"),
        "initramfs_sha256": sha(DEST / "initramfs.cpio"),
        "kernel_config_sha256": sha(OUT / ".config"),
        "guard_sha256": sha(FS / "usr/sbin/ram-guard"),
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
