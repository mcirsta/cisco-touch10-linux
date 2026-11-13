#!/usr/bin/env python3
"""Construct an offline, read-only speedup poll pair for the PPA handoff address.

This script never opens a device. It preserves the exact signed KEYS/PPA
region and changes only the unsigned outer TOC and one speedup table.
"""

from hashlib import sha256
import json
from pathlib import Path
from struct import pack_into, unpack_from


SOURCE = Path("firmware/codec-ce9.9.0/extracted/MLO")
ROM = Path("analysis/bootrom/omap4460-bootrom-lowalias.bin")
OUTPUT = Path("evidence/bootrom-handoff-poll-2026-11-08")
SOURCE_SHA256 = "2b80cf8b398c3cb109d4da028831ff4881c8b0ea0fa8c33167a6d6b00e62e427"
ROM_SHA256 = "7fd0176dbdf06cfa42f147a5c0a923abb1f2fa269b82d0352fa02a5bd3b8efff"
SIZE = 0x3F9C
TABLE = 0xA4
TABLE_SIZE = 0x110
MAGIC = 0x16793A22
TARGET = 0x00402104
BIT = 0


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def build(source: bytes, wait_for: str) -> bytes:
    image = bytearray(source[:SIZE])
    pack_into("<II", image, 0, 0, 0x200)
    image[0x14:0x18] = b"2ND\0"
    table = bytearray(TABLE_SIZE)
    pack_into("<II", table, 0, MAGIC, 1)
    pack_into("<II", table, 8, TARGET, BIT)
    # ROM mode = low_bitmap_bit + 2 * high_bitmap_bit.
    # Mode 1 waits while bit is set; mode 2 waits while it is clear.
    modes = {"clear": (1, 0), "set": (0, 1)}
    low, high = modes[wait_for]
    pack_into("<II", table, 0x108, low, high)
    image[TABLE:TABLE + TABLE_SIZE] = table

    assert image[0x60:0x80] == b"\xff" * 32
    assert image[0x200:SIZE] == source[0x200:SIZE]
    assert image[0x200:0x208] == b"CertPK_\0"
    assert image[0xC00:0xC08] == b"CertPPA\0"
    assert unpack_from("<II", image, 0) == (0, 0x200)
    assert image[0x14:0x18] == b"2ND\0"
    assert unpack_from("<II", image, TABLE) == (MAGIC, 1)
    assert unpack_from("<II", image, TABLE + 8) == (TARGET, BIT)
    assert unpack_from("<II", image, TABLE + 0x108) == (low, high)
    assert len(image) == SIZE and TABLE + TABLE_SIZE <= 0x200
    allowed = set(range(0, 8)) | set(range(0x14, 0x18)) | set(range(TABLE, TABLE + TABLE_SIZE))
    assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(source, image)))
    return bytes(image)


def main() -> None:
    source = SOURCE.read_bytes()
    rom = ROM.read_bytes()
    assert len(source) == 41024 and digest(source) == SOURCE_SHA256
    assert len(rom) == 49152 and digest(rom) == ROM_SHA256
    assert unpack_from("<II", source, 0) == (0x4000, 0x6040)
    assert source[0x14:0x18] == b"MLO\0"
    assert unpack_from("<II", source, 0x20) == (0xC00, 0x339C)
    assert unpack_from("<II", source, 0x40) == (0x200, 0x960)
    assert source[0x60:0x80] == b"\xff" * 32
    assert 0x2C000 <= TARGET <= 0x3FFFFFFE

    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "scope": "offline construction only; no upload or device write",
        "source_sha256": SOURCE_SHA256,
        "rom_sha256": ROM_SHA256,
        "target": f"0x{TARGET:08x}",
        "bit": BIT,
        "image_size": SIZE,
        "signed_keys_and_ppa_sha256": digest(source[0x200:SIZE]),
        "images": {},
    }
    for name in ("clear", "set"):
        image = build(source, name)
        path = OUTPUT / f"{name}.bin"
        path.write_bytes(image)
        manifest["images"][name] = {"sha256": digest(image), "passes_if_bit": name}

    clear = (OUTPUT / "clear.bin").read_bytes()
    set_ = (OUTPUT / "set.bin").read_bytes()
    differences = [i for i, (a, b) in enumerate(zip(clear, set_)) if a != b]
    assert differences == [TABLE + 0x108, TABLE + 0x10C]
    manifest["differing_offsets"] = [f"0x{i:x}" for i in differences]
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
