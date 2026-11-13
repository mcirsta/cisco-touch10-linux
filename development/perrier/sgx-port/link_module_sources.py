#!/usr/bin/env python3
"""Materialize TI SGX source links for Linux 6.18 external-module kbuild.

The TI 1.17 generated Makefile creates source symlinks on demand. Linux 6.18
does not apply that pattern rule to the composite module's nested object
paths, so create the same links before invoking kbuild.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DDK = ROOT / "development/reference/ti-sgx-km-1.17"
OUT = DDK / "eurasiacon/binary_ti443x_linux_lws-generic_release/target_armhf/kbuild"

if not (OUT / "Makefile").is_file():
    raise SystemExit("Run the TI DDK make once to generate its kbuild directory")

count = 0
for base in ("services4", "include4"):
    for source in (DDK / base).rglob("*"):
        if source.suffix not in (".c", ".S") or not source.is_file():
            continue
        target = OUT / source.relative_to(DDK)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() and target.resolve() == source:
            continue
        if target.exists() or target.is_symlink():
            raise SystemExit(f"Refusing to replace {target}")
        target.symlink_to(source)
        count += 1
print(f"Linked {count} TI SGX module sources into {OUT}")
