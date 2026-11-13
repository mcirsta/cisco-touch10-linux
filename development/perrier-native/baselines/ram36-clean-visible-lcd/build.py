#!/usr/bin/env python3
"""Build the audited Perrier RAM image from a small, exact patch set."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "development/sources/linux-6.18.48"
OUT = HERE / "build"
PATCHES = HERE / "kernel-patches"
KERNEL_VERSION = "6.18.48-perrier-ram36"


def call(args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_kernel_patches():
    """Accept only exact vanilla or exact reviewed contents for each file."""
    manifest = json.loads((PATCHES / "manifest.json").read_text())
    assert manifest["kernel"] == "linux-6.18.48"
    for entry in manifest["patches"]:
        source_file = SRC / entry["path"]
        patch_file = PATCHES / entry["patch"]
        assert digest(patch_file) == entry["patch_sha256"], patch_file
        found = digest(source_file)
        if found == entry["patched_sha256"]:
            continue
        if found != entry["vanilla_sha256"]:
            raise RuntimeError(f"unexpected kernel source contents: {source_file}")
        call(["patch", "--batch", "--forward", "--fuzz=0", "-d", SRC,
              "-p1", "-i", patch_file])
        if digest(source_file) != entry["patched_sha256"]:
            raise RuntimeError(f"patch verification failed: {source_file}")


def cpio_entry(name, mode, data=b"", major=0, minor=0):
    filename = name.encode() + b"\0"
    fields = [1, mode, 0, 0, 1, 0, len(data), 0, 0, major, minor,
              len(filename), 0]
    header = b"070701" + b"".join(f"{number:08x}".encode()
                                   for number in fields) + filename
    return header + bytes((-len(header)) % 4) + data + bytes((-len(data)) % 4)


def build_initramfs():
    compiler = ROOT / "development/toolchain/arm-cc"
    call([compiler, "-O2", "-static", "-o", HERE / "init", HERE / "init.c"])
    call([compiler, "-O2", "-static", "-D__user=", "-I", SRC / "include/uapi",
          "-o", HERE / "kms-probe", HERE / "kms_probe.c"])
    call([compiler, "-O2", "-static", "-D__user=", "-idirafter",
          SRC / "include/uapi", "-o", HERE / "kms-pattern",
          HERE / "kms_pattern.c"])
    call([compiler, "-Os", "-static", "-o", HERE / "backlight-state",
          HERE / "stock-analysis/backlight_state.c"])
    archive = b""
    for name in ("dev", "proc", "sys", "mnt", "mnt/base", "extra", "gui", "apps"):
        archive += cpio_entry(name, 0o040755)
    archive += cpio_entry("dev/console", 0o020600, major=5, minor=1)
    archive += cpio_entry("dev/mem", 0o020600, major=1, minor=1)
    for name in ("init", "kms-probe", "kms-pattern", "backlight-state"):
        archive += cpio_entry(name, 0o100755, (HERE / name).read_bytes())
    archive += cpio_entry("TRAILER!!!", 0)
    (HERE / "initramfs.cpio").write_bytes(archive)


def build_kernel():
    fragment = (HERE / "minimal.config").read_text()
    fragment += f'\nCONFIG_INITRAMFS_SOURCE="{HERE / "initramfs.cpio"}"\n'
    (HERE / "resolved.config").write_text(fragment)
    env = dict(os.environ, KCONFIG_ALLCONFIG=str(HERE / "resolved.config"),
               KBUILD_BUILD_USER="touch10", KBUILD_BUILD_HOST="perrier-dev",
               KBUILD_BUILD_TIMESTAMP="2026-11-08 00:00:00 UTC")
    make = ["make", "-C", SRC, f"O={OUT}", "ARCH=arm", "LLVM=1"]
    call(make + ["allnoconfig"], env=env)
    call(make + [f"-j{os.cpu_count() or 1}", "zImage"], env=env)
    dts = HERE / "omap4-perrier-ram.dts"
    with (OUT / "perrier.preprocessed.dts").open("wb") as stream:
        call(["clang", "-E", "-P", "-x", "assembler-with-cpp", "-nostdinc",
              "-undef", "-D__DTS__", "-I", SRC / "arch/arm/boot/dts/ti/omap",
              "-I", SRC / "scripts/dtc/include-prefixes", dts], stdout=stream)
    dtc = OUT / "scripts/dtc/dtc"
    call([dtc, "-i", SRC / "arch/arm/boot/dts/ti/omap", "-I", "dts", "-O",
          "dtb", "-o", OUT / "omap4-perrier-ram.dtb",
          OUT / "perrier.preprocessed.dts"])
    call([dtc, "-I", "dtb", "-O", "dts", "-o", OUT / "compiled.dts",
          OUT / "omap4-perrier-ram.dtb"])


def write_manifest():
    files = [OUT / "arch/arm/boot/zImage", OUT / "vmlinux", OUT / "System.map",
             OUT / ".config", OUT / "omap4-perrier-ram.dtb", HERE / "initramfs.cpio",
             HERE / "init", HERE / "kms-probe", HERE / "kms-pattern",
             HERE / "backlight-state"]
    record = {
        "kernel": KERNEL_VERSION,
        "source_sha256": "5ebdadb10a4b5708fc6b1c457764a110bc49f8150cc3502c59b921ead8c6fc8c",
        "source_signature_key": "647F28654894E3BD457199BE38DBBDC86092693E",
        "patch_manifest_sha256": digest(PATCHES / "manifest.json"),
        "files": {str(path.relative_to(ROOT)): {"size": path.stat().st_size,
                                              "sha256": digest(path)} for path in files},
    }
    (HERE / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


def main():
    OUT.mkdir(exist_ok=True)
    apply_kernel_patches()
    build_initramfs()
    build_kernel()
    write_manifest()


if __name__ == "__main__":
    main()
