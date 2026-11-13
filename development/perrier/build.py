#!/usr/bin/env python3
"""Reproducible, board-gated first Perrier RAM kernel build."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "development/sources/linux-6.18.48"
OUT = HERE / "build"

def call(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)

def patch_file(relative, old, new):
    path = SRC / relative
    before = path.read_text()
    if new in before:
        return
    assert before.count(old) == 1, relative
    after = before.replace(old, new)
    patches = HERE / "patches"
    patches.mkdir(exist_ok=True)
    with (patches / (path.name + ".patch")).open("a") as stream:
        stream.write("".join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile="a/"+relative, tofile="b/"+relative)))
    path.write_text(after)

def cpio_entry(name, mode, data=b"", major=0, minor=0):
    filename = name.encode() + b"\0"
    fields = [1, mode, 0, 0, 1, 0, len(data), 0, 0, major, minor, len(filename), 0]
    header = b"070701" + b"".join(f"{n:08x}".encode() for n in fields) + filename
    return header + bytes((-len(header)) % 4) + data + bytes((-len(data)) % 4)

def main():
    OUT.mkdir(exist_ok=True)
    patch_file("drivers/clk/ti/clk-44xx.c", "\tti_clk_add_aliases();\n",
        "\tti_clk_add_aliases();\n\n\t/* Perrier RAM trial: retain stock USB/audio PLL configuration. */\n"
        "\tif (of_machine_is_compatible(\"cisco,perrier-ram\"))\n\t\treturn 0;\n")
    patch_file("arch/arm/mach-omap2/io.c", "void __init omap4430_init_late(void)\n{\n",
        "void __init omap4430_init_late(void)\n{\n"
        "\t/* No PMIC, voltage or low-power policy changes in the RAM trial. */\n"
        "\tif (of_machine_is_compatible(\"cisco,perrier-ram\"))\n\t\treturn;\n")
    patch_file("drivers/mmc/core/block.c", "#include <linux/rpmb.h>\n",
        "#include <linux/rpmb.h>\n#include <linux/of.h>\n")
    patch_file("drivers/mmc/core/block.c", "\tmd->read_only = mmc_blk_readonly(card);\n",
        "\tmd->read_only = mmc_blk_readonly(card);\n"
        "\t/* Perrier RAM trial: all eMMC areas reject write opens. */\n"
        "\tif (of_machine_is_compatible(\"cisco,perrier-ram\"))\n"
        "\t\tmd->read_only = 1;\n")
    call([ROOT / "development/toolchain/arm-cc", "-O2", "-static", "-o", HERE / "init", HERE / "init.c"])
    archive = b""
    for name in ["dev", "proc", "sys", "mnt", "mnt/base", "extra", "gui", "apps"]:
        archive += cpio_entry(name, 0o040755)
    archive += cpio_entry("dev/console", 0o020600, major=5, minor=1)
    archive += cpio_entry("dev/mem", 0o020600, major=1, minor=1)
    archive += cpio_entry("init", 0o100755, (HERE / "init").read_bytes())
    archive += cpio_entry("TRAILER!!!", 0)
    (HERE / "initramfs.cpio").write_bytes(archive)
    fragment = (HERE / "minimal.config").read_text()
    fragment += f'\nCONFIG_INITRAMFS_SOURCE="{HERE / "initramfs.cpio"}"\n'
    (HERE / "resolved.config").write_text(fragment)
    env = dict(os.environ, KCONFIG_ALLCONFIG=str(HERE / "resolved.config"),
               KBUILD_BUILD_USER="touch10", KBUILD_BUILD_HOST="perrier-dev",
               KBUILD_BUILD_TIMESTAMP="2026-11-08 00:00:00 UTC")
    base = ["make", "-C", SRC, f"O={OUT}", "ARCH=arm", "LLVM=1"]
    call(base + ["allnoconfig"], env=env)
    call(base + [f"-j{os.cpu_count()}", "zImage"], env=env)
    dts = HERE / "omap4-perrier-ram.dts"
    with (OUT / "perrier.preprocessed.dts").open("wb") as stream:
        call(["clang", "-E", "-P", "-x", "assembler-with-cpp", "-nostdinc", "-undef", "-D__DTS__",
              "-I", SRC / "arch/arm/boot/dts/ti/omap", "-I", SRC / "scripts/dtc/include-prefixes", dts], stdout=stream)
    call([OUT / "scripts/dtc/dtc", "-i", SRC / "arch/arm/boot/dts/ti/omap", "-I", "dts", "-O", "dtb", "-o", OUT / "omap4-perrier-ram.dtb", OUT / "perrier.preprocessed.dts"])
    call([OUT / "scripts/dtc/dtc", "-I", "dtb", "-O", "dts", "-o", OUT / "compiled.dts", OUT / "omap4-perrier-ram.dtb"])
    files = [OUT / "arch/arm/boot/zImage", OUT / "vmlinux", OUT / "System.map", OUT / ".config",
             OUT / "omap4-perrier-ram.dtb", HERE / "initramfs.cpio", HERE / "init"]
    record = {"kernel": "6.18.48-perrier-ram14", "source_sha256": "5ebdadb10a4b5708fc6b1c457764a110bc49f8150cc3502c59b921ead8c6fc8c",
              "source_signature_key": "647F28654894E3BD457199BE38DBBDC86092693E", "files": {}}
    for path in files:
        record["files"][str(path.relative_to(ROOT))] = {"size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (HERE / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))

if __name__ == "__main__":
    main()
