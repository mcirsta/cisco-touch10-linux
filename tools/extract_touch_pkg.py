#!/usr/bin/env python3
"""Extract the observed Cisco Touch 10 ``pkg\0`` package format.

The original package is never modified. The table format was derived from
the CE9.9.0 idefix.pkg served by this owner's codec; other packages may differ.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct


def safe_name(raw: bytes) -> str:
    # The last signature entry in this format has a one-byte type prefix.
    raw = raw.removeprefix(b"\x01")
    name = raw.rstrip(b"\0").decode("ascii")
    path = PurePosixPath(name.lstrip("/"))
    if not name or path.is_absolute() or any(p in ("", ".", "..") for p in path.parts):
        raise ValueError(f"unsafe member name: {name!r}")
    return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    data = args.package.read_bytes()
    if data[:4] != b"pkg\0" or len(data) < 32:
        raise ValueError("not an observed pkg format")
    declared_size = struct.unpack_from(">I", data, 8)[0]
    table_start = struct.unpack_from(">H", data, 0x10)[0]
    count = struct.unpack_from(">I", data, 0x12)[0]
    if declared_size != len(data) or not 1 <= count <= 256 or not 32 <= table_start < len(data):
        raise ValueError("invalid package size or table header")

    entries = []
    cursor = table_start
    names = set()
    for _ in range(count):
        if cursor + 14 > len(data):
            raise ValueError("truncated member table")
        record_len, offset, size, flags = struct.unpack_from(">HIII", data, cursor)
        if not 15 <= record_len <= 4096 or cursor + record_len > len(data):
            raise ValueError("invalid member record length")
        raw_name = data[cursor + 14:cursor + record_len]
        name = safe_name(raw_name)
        if name in names or offset + size > len(data):
            raise ValueError("duplicate member or out-of-bounds payload")
        names.add(name)
        entries.append({"name": name, "offset": offset, "size": size,
                        "flags": flags})
        cursor += record_len
    table_padding = data[cursor:entries[0]["offset"]]
    if not 0 <= len(table_padding) <= 16:
        raise ValueError("unexpected bytes between table and first payload")
    previous_end = entries[0]["offset"]
    for entry in entries:
        if entry["offset"] != previous_end:
            raise ValueError("member payloads are not contiguous")
        previous_end = entry["offset"] + entry["size"]
    if previous_end != len(data):
        raise ValueError("unaccounted bytes after last member")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        content = data[entry["offset"]:entry["offset"] + entry["size"]]
        entry["sha256"] = hashlib.sha256(content).hexdigest()
        dest = args.output_dir / entry["name"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    manifest = {"package": str(args.package), "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "declared_size": declared_size, "table_start": table_start,
                "table_padding_hex": table_padding.hex(),
                "member_count": count, "entries": entries}
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Extracted {count} members into {args.output_dir}")
    for entry in entries:
        print(f"{entry['size']:>10}  {entry['name']}")


if __name__ == "__main__":
    main()
