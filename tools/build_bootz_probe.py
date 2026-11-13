#!/usr/bin/env python3
"""Build an offline, one-instruction unsigned zImage probe for U-Boot bootz.

This tool only reads the recovered CE9.9.0 kernel and writes local evidence.
It never connects to the Touch 10 or changes device storage.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "firmware/codec-ce9.9.0/extracted/kernel"
OUTPUT_DIR = ROOT / "evidence/uboot-bootz-probe-2026-11-07"
SOURCE_SHA256 = "f54f815915e6ebd555c5f682072937cf5289a5fa25320bb5cdb7561f2aaddc1f"
WRAPPER_SIZE = 0x390
ZIMAGE_MAGIC = 0x016F2818
OLD_NOP = bytes.fromhex("0000a0e1")  # ARM mov r0, r0
NEW_NOP = bytes.fromhex("0110a0e1")  # ARM mov r1, r1


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    source = SOURCE.read_bytes()
    if sha256(source) != SOURCE_SHA256 or struct.unpack_from(">I", source)[0] != 0x27051956:
        raise ValueError("Input is not the pinned CE9.9.0 Cisco kernel wrapper")
    original = source[WRAPPER_SIZE:]
    if original[4:8] != OLD_NOP:
        raise ValueError("Expected ARM NOP is absent")
    magic, start, end = struct.unpack_from("<III", original, 0x24)
    if (magic, start, end) != (ZIMAGE_MAGIC, 0, 0x38D400):
        raise ValueError("Unexpected zImage header")
    if len(original) != end:
        raise ValueError("zImage length does not match its header")

    modified = bytearray(original)
    modified[4:8] = NEW_NOP
    modified = bytes(modified)
    differences = [i for i, (a, b) in enumerate(zip(original, modified)) if a != b]
    if differences != [4, 5] or modified[0x24:0x30] != original[0x24:0x30]:
        raise ValueError("Probe differs outside the intended NOP bytes")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    probe_path = OUTPUT_DIR / "unsigned-nop-variant-zImage.bin"
    probe_path.write_bytes(modified)
    manifest = {
        "status": "local comparison artifact; equivalent NOP substitution was executed in RAM during the live bootz proof",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha256(source),
        "wrapper_size": WRAPPER_SIZE,
        "raw_zimage_size": len(original),
        "raw_zimage_sha256": sha256(original),
        "probe_file": probe_path.name,
        "probe_sha256": sha256(modified),
        "changed_byte_offsets": differences,
        "old_instruction_le": OLD_NOP.hex(),
        "new_instruction_le": NEW_NOP.hex(),
        "zimage_magic": f"{magic:08x}",
        "zimage_start": start,
        "zimage_end": end,
    }
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
