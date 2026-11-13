#!/usr/bin/env python3
"""Compare a captured OMAP ROM MPKH with the root key in a reference MLO.

This reads local files only. It does not validate certificate signatures or
predict whether the ROM will accept the complete boot image.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct


CERTPK_OFFSET = 0x200
ROOT_KEY_OFFSET_IN_CERT = 52
ROOT_KEY_LENGTH = 20 + 256


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom-id", type=Path, required=True)
    parser.add_argument("--mlo", type=Path, required=True)
    args = parser.parse_args()

    rom = json.loads(args.rom_id.read_text())
    blocks = [b for b in rom["blocks"] if b["type"] == "0x14"]
    if len(blocks) != 1 or blocks[0]["bytes"] != 33 or blocks[0]["format_marker"] != 1:
        raise ValueError("Expected exactly one format-1 32-byte MPKH block")
    mpkh = bytes.fromhex(blocks[0]["payload_hex"])
    if len(mpkh) != 32:
        raise ValueError("MPKH must be 32 bytes")

    mlo = args.mlo.read_bytes()
    if mlo[CERTPK_OFFSET:CERTPK_OFFSET + 8] != b"CertPK_\0":
        raise ValueError("MLO has no CertPK_ marker at offset 0x200")
    start = CERTPK_OFFSET + ROOT_KEY_OFFSET_IN_CERT
    key = mlo[start:start + ROOT_KEY_LENGTH]
    if len(key) != ROOT_KEY_LENGTH:
        raise ValueError("Truncated root key")
    key_id, key_type, rights, modulus_length, exponent = struct.unpack_from("<5I", key)
    if modulus_length != 256 or exponent != 65537:
        raise ValueError("Unexpected reference RSA root-key format")
    digest = hashlib.sha256(key).digest()
    result = {
        "reference_mlo_sha256": hashlib.sha256(mlo).hexdigest(),
        "root_key_file_offset": f"0x{start:x}",
        "root_key_bytes": len(key),
        "root_key_metadata": {
            "id": key_id,
            "type": key_type,
            "rights": rights,
            "modulus_bytes": modulus_length,
            "exponent": exponent,
        },
        "root_key_sha256": digest.hex(),
        "rom_mpkh": mpkh.hex(),
        "equal": digest == mpkh,
        "scope": "Root public-key record equality only; no image acceptance or code execution test",
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
