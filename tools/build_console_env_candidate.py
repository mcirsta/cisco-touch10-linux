#!/usr/bin/env python3
"""Rebuild the Touch 10 U-Boot console environment image from exact firmware.

This program never opens a device or writes the Touch 10. The first build was
used in one owner-authorized test; see the live proof in evidence/.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGNED_UBOOT = ROOT / "firmware/codec-ce9.9.0/extracted/u-boot_signed.bin"
UBOOT_CODE = ROOT / "firmware/codec-ce9.9.0/analysis/touch10-ce990-uboot-code.bin"
OUTPUT_DIR = ROOT / "evidence/uboot-console-candidate-2026-11-07"
SIGNED_SHA256 = "9550311050968123a53d7c0be6aa309d1c3b8629515aa0eaddebba628fb161d5"
CODE_OFFSET = 0x390
ENV_SIZE = 0x40000
DATA_SIZE = ENV_SIZE - 4
ENV_OFFSET = 0x08B60000

# The first boot changes bootcmd to `run normalboot` and saves the environment
# before returning to U-Boot's command loop. Any reported failure attempts
# the original factory boot command immediately.
TRAMPOLINE = (
    "if setenv bootcmd run normalboot; then "
    "if saveenv; then echo CONSOLE_READY; "
    "else run normalboot; fi; "
    "else run normalboot; fi"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_entries(data: bytes) -> list[tuple[str, str]]:
    body = data.split(b"\0\0", 1)[0]
    entries: list[tuple[str, str]] = []
    for item in body.split(b"\0"):
        if not item:
            continue
        name, sep, value = item.partition(b"=")
        if not sep or not name:
            raise ValueError("Malformed U-Boot environment entry")
        entries.append((name.decode("ascii"), value.decode("ascii")))
    names = [name for name, _ in entries]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate U-Boot environment variable")
    return entries


def encode_image(entries: list[tuple[str, str]]) -> bytes:
    data = b"\0".join(f"{name}={value}".encode("ascii") for name, value in entries)
    data += b"\0\0"
    if len(data) > DATA_SIZE:
        raise ValueError("Environment exceeds partition capacity")
    data = data.ljust(DATA_SIZE, b"\0")
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return struct.pack("<I", crc) + data


def check_image(image: bytes, expected: dict[str, str]) -> None:
    if len(image) != ENV_SIZE:
        raise ValueError("Wrong environment size")
    stored_crc = struct.unpack_from("<I", image)[0]
    actual_crc = zlib.crc32(image[4:]) & 0xFFFFFFFF
    if stored_crc != actual_crc:
        raise ValueError("Environment CRC mismatch")
    got = dict(parse_entries(image[4:]))
    if got != expected:
        raise ValueError("Environment variable mismatch")
    if "bootdelay" in got:
        raise ValueError("Unexpected persistent bootdelay")


def main() -> None:
    signed = SIGNED_UBOOT.read_bytes()
    code = UBOOT_CODE.read_bytes()
    if sha256(signed) != SIGNED_SHA256 or signed[CODE_OFFSET:] != code:
        raise ValueError("Exact CE9.9.0 U-Boot input does not match pinned package")

    anchor = code.find(b"bootcmd=")
    terminator = code.find(b"\0\0", anchor)
    if anchor < 0 or terminator < 0:
        raise ValueError("Compiled default environment not found")
    defaults = parse_entries(code[anchor : terminator + 2])
    if len(defaults) != 25 or defaults[0][0] != "bootcmd":
        raise ValueError("Unexpected compiled default environment layout")
    factory = dict(defaults)
    if factory.get("autoupgrade") != "0" or factory.get("diag_booting") != "0":
        raise ValueError("Unexpected factory boot selectors")
    if "bootdelay" in factory:
        raise ValueError("Factory environment unexpectedly has bootdelay")

    candidate = [(name, TRAMPOLINE if name == "bootcmd" else value) for name, value in defaults]
    candidate.append(("normalboot", factory["bootcmd"]))
    expected_candidate = dict(candidate)
    image = encode_image(candidate)
    check_image(image, expected_candidate)

    # This checks the intended variable values only. U-Boot's saveenv exports
    # its live hash table, which can include board-created variables and use a
    # different ordering. Its exact post-save bytes cannot be predicted here.
    after_save = [(name, "run normalboot" if name == "bootcmd" else value) for name, value in candidate]
    check_image(encode_image(after_save), dict(after_save))

    # Reproduce the earlier independent bootdelay=-1 reference CRC as a format
    # sanity check. This image is neither emitted nor recommended for use.
    delay_image = encode_image(defaults + [("bootdelay", "-1")])
    if struct.unpack_from("<I", delay_image)[0] != 0x4EE27B1F:
        raise ValueError("Environment CRC format differs from prior reference")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / "candidate-not-flashed.bin"
    output.write_bytes(image)
    manifest = {
        "status": "source image used in one owner-authorized partition-8 test; see live proof",
        "source": str(SIGNED_UBOOT.relative_to(ROOT)),
        "source_sha256": sha256(signed),
        "uboot_code_offset": CODE_OFFSET,
        "default_variable_count": len(defaults),
        "candidate_variable_count": len(candidate),
        "environment_offset_bytes": ENV_OFFSET,
        "environment_size_bytes": ENV_SIZE,
        "candidate_file": output.name,
        "candidate_sha256": sha256(image),
        "candidate_crc32": f"{struct.unpack_from('<I', image)[0]:08x}",
        "trampoline_bootcmd": TRAMPOLINE,
        "intended_post_save_bootcmd": "run normalboot",
        "post_save_exact_bytes_known": False,
        "factory_bootcmd": factory["bootcmd"],
        "restore_note": "Restores boot behavior, not the original invalid partition bytes",
    }
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"candidate: {output}")
    print(f"sha256: {manifest['candidate_sha256']}")
    print(f"crc32: {manifest['candidate_crc32']}")
    print(f"intended post-save bootcmd: {manifest['intended_post_save_bootcmd']}")


if __name__ == "__main__":
    main()
