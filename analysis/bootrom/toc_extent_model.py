#!/usr/bin/env python3
"""Model the OMAP4460 ROM's TOC-extent routine at low alias 0x343e0.

This is an offline arithmetic model, not a full ROM emulator or exploit PoC.
The routine scans at most 16 records of 32 bytes and stops at start=0xffffffff.
It chooses the record with the largest *start*, returning start+size in u32.
"""

import argparse
from pathlib import Path
import struct


def extents(blob: bytes) -> tuple[int, int, list[tuple[int, int, int, str]]]:
    if len(blob) < 512:
        raise ValueError("TOC must have at least 512 bytes")
    largest_start = 0
    rom_result = 0
    true_max = 0
    records = []
    for index in range(16):
        rec = blob[index * 32 : (index + 1) * 32]
        start, size = struct.unpack_from("<II", rec)
        if start == 0xFFFFFFFF:
            break
        name = rec[20:32].split(b"\0", 1)[0].decode("ascii", "replace")
        records.append((index, start, size, name))
        if start > largest_start:
            largest_start = start
            rom_result = (start + size) & 0xFFFFFFFF
        true_max = max(true_max, start + size)
    return rom_result, true_max, records


def synthetic_case() -> bytes:
    blob = bytearray(512)
    for index, (start, size, name) in enumerate(
        [(0x1000, 0x100, b"2ND"), (0x800, 0x10000, b"PRIMAPP")]
    ):
        struct.pack_into("<II", blob, index * 32, start, size)
        blob[index * 32 + 20 : index * 32 + 20 + len(name)] = name
    struct.pack_into("<I", blob, 2 * 32, 0xFFFFFFFF)
    return bytes(blob)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path, help="image with TOC at offset 0")
    args = parser.parse_args()
    data = args.image.read_bytes() if args.image else synthetic_case()
    rom_result, true_max, records = extents(data)
    for index, start, size, name in records:
        print(f"{index:2d}: start=0x{start:08x} size=0x{size:08x} name={name}")
    print(f"ROM result=0x{rom_result:08x}; maximum end=0x{true_max:x}")
    print(f"undercount={max(0, true_max - rom_result)} bytes")


if __name__ == "__main__":
    main()
