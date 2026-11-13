#!/usr/bin/env python3
"""Build two offline-only, read-only ROM speedup poll images.

No device interface is used here. The images are for a separately reviewed
USB ROM reachability experiment; this script does not upload them.
"""

from hashlib import sha256
import json
from pathlib import Path
from struct import pack_into, unpack_from


SOURCE = Path("firmware/codec-ce9.9.0/extracted/MLO")
ROM = Path("analysis/bootrom/omap4460-bootrom-lowalias.bin")
OUTPUT = Path("evidence/bootrom-speedup-poll-2026-11-07")
SOURCE_SHA256 = "2b80cf8b398c3cb109d4da028831ff4881c8b0ea0fa8c33167a6d6b00e62e427"
ROM_SHA256 = "7fd0176dbdf06cfa42f147a5c0a923abb1f2fa269b82d0352fa02a5bd3b8efff"
IMAGE_SIZE = 0x3F9C
TABLE_START = 0xA4
TABLE_SIZE = 0x110
POLL_ADDRESS = 0x36F54
ROM_LITERAL = 0x16793A22


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def build(source: bytes, expected: int) -> bytes:
    image = bytearray(source[:IMAGE_SIZE])
    pack_into("<II", image, 0, 0, 0x200)  # 2ND selected section: outer header.
    image[0x14:0x18] = b"2ND\0"
    table = bytearray(TABLE_SIZE)
    pack_into("<II", table, 0, ROM_LITERAL, 1)  # Magic, entry-0 active.
    pack_into("<II", table, 8, POLL_ADDRESS, expected)
    pack_into("<II", table, 0x108, 1, 1)  # Mode 3: both bitmap bits set.
    image[TABLE_START:TABLE_START + TABLE_SIZE] = table

    assert image[0x60:0x80] == b"\xff" * 32  # TOC terminator precedes table.
    assert image[0x200:IMAGE_SIZE] == source[0x200:IMAGE_SIZE]
    assert len(image) == IMAGE_SIZE and TABLE_START + TABLE_SIZE <= 0x200
    assert unpack_from("<II", image, 0) == (0, 0x200)
    assert image[0x14:0x18] == b"2ND\0"
    assert unpack_from("<II", image, TABLE_START) == (ROM_LITERAL, 1)
    assert unpack_from("<II", image, TABLE_START + 8) == (POLL_ADDRESS, expected)
    assert unpack_from("<II", image, TABLE_START + 0x108) == (1, 1)
    assert image[0x200:0x208] == b"CertPK_\0"
    assert image[0xC00:0xC08] == b"CertPPA\0"
    allowed_changes = set(range(0, 8)) | set(range(0x14, 0x18)) | set(range(TABLE_START, TABLE_START + TABLE_SIZE))
    assert all(a == b or i in allowed_changes for i, (a, b) in enumerate(zip(source, image)))
    return bytes(image)


def main() -> None:
    source = SOURCE.read_bytes()
    rom = ROM.read_bytes()
    assert len(source) == 41024 and digest(source) == SOURCE_SHA256
    assert len(rom) == 49152 and digest(rom) == ROM_SHA256
    assert unpack_from("<I", rom, POLL_ADDRESS - 0x30000)[0] == ROM_LITERAL
    assert unpack_from("<II", source, 0) == (0x4000, 0x6040)
    assert source[0x14:0x18] == b"MLO\0"
    assert unpack_from("<II", source, 0x20) == (0xC00, 0x339C)
    assert unpack_from("<II", source, 0x40) == (0x200, 0x960)
    assert source[0x60:0x80] == b"\xff" * 32

    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "scope": "offline construction only; no upload or device write",
        "source_sha256": SOURCE_SHA256,
        "rom_sha256": ROM_SHA256,
        "image_size": IMAGE_SIZE,
        "selected_toc": {"name": "2ND", "start": 0, "size": 0x200},
        "table": {"offset": TABLE_START, "size": TABLE_SIZE,
                  "active_mask": 1, "mode": "entry 0 equality poll",
                  "address": f"0x{POLL_ADDRESS:08x}"},
        "signed_keys_and_primapp_bytes_sha256": digest(source[0x200:IMAGE_SIZE]),
        "images": {},
    }
    for name, value in (("pass", ROM_LITERAL), ("stall", ROM_LITERAL + 1)):
        image = build(source, value)
        path = OUTPUT / f"{name}.bin"
        path.write_bytes(image)
        manifest["images"][name] = {
            "sha256": digest(image),
            "expected_word": f"0x{value:08x}",
            "equality_with_rom_literal": value == ROM_LITERAL,
        }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
