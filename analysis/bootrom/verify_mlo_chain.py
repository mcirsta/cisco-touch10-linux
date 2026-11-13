#!/usr/bin/env python3
"""Offline verification of the exact Touch 10 MLO certificate chain.

Checks the captured ROM MPKH, CertPK/CertPPA/CertISW RSA PKCS#1 v1.5
signatures, and the PPA/ISW body hashes. Also checks that changing only the
outer TOC destination leaves all these cryptographic checks unchanged.
This does not emulate the secure ROM's independent structural checks.
"""

import json
from hashlib import sha1, sha256
from pathlib import Path
from struct import pack_into, unpack_from

MLO_PATH = Path("firmware/codec-ce9.9.0/extracted/MLO")
ROM_ID_PATH = Path("evidence/omap-rom-asic-id.json")
EMMC_BACKUP_PATH = Path("backups/touch10-2026-11-07/mmcblk0.img")
SHA256_DER = bytes.fromhex("3031300d060960864801650304020105000420")


def key_record(image: bytes, offset: int) -> tuple[int, int, int, bytes]:
    key_id, _, _, modulus_size, exponent = unpack_from("<5I", image, offset)
    if modulus_size != 256 or exponent != 65537:
        raise ValueError(f"Unexpected key format at 0x{offset:x}")
    raw = image[offset : offset + 276]
    if len(raw) != 276:
        raise ValueError("Truncated key record")
    modulus = int.from_bytes(raw[20:], "little")
    return key_id, modulus, exponent, raw


def check_certificate(image: bytes, cert: int, signed_size: int, sig_offset: int,
                      signer_key_offset: int) -> str:
    key_id, modulus, exponent, _ = key_record(image, signer_key_offset)
    signer_id = unpack_from("<I", image, cert + sig_offset - 4)[0]
    if signer_id != key_id:
        raise ValueError(f"Signer key ID mismatch at 0x{cert:x}")
    signature = image[cert + sig_offset : cert + sig_offset + 256]
    if len(signature) != 256:
        raise ValueError("Truncated RSA signature")
    recovered = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(256, "big")
    digest = sha256(image[cert : cert + signed_size]).digest()
    expected = b"\x00\x01" + b"\xff" * (256 - 3 - len(SHA256_DER) - 32) + b"\x00" + SHA256_DER + digest
    if recovered != expected:
        raise ValueError(f"RSA/SHA-256 check failed at 0x{cert:x}")
    return digest.hex()


def check_body(image: bytes, cert: int, descriptor: int, stored_hash: int) -> str:
    offset, size = unpack_from("<II", image, cert + descriptor)
    body = image[cert + offset : cert + offset + size]
    if len(body) != size:
        raise ValueError("Truncated image body")
    digest = sha1(body).digest()
    if digest != image[cert + stored_hash : cert + stored_hash + 20]:
        raise ValueError(f"Body SHA-1 mismatch at 0x{cert:x}")
    return digest.hex()


def verify(image: bytes, expected_mpkh: bytes) -> dict[str, str]:
    if image[0x200:0x208] != b"CertPK_\0" or image[0xC00:0xC08] != b"CertPPA\0":
        raise ValueError("Unexpected PK or PPA certificate marker")
    isw = unpack_from("<I", image, 0)[0]
    if image[20:24] != b"MLO\0" or image[isw : isw + 8] != b"CertISW\0":
        raise ValueError("Unexpected TOC or ISW marker")

    root_key = 0x200 + 52
    signer_key = root_key + 276 + 4
    root_id, _, _, root_raw = key_record(image, root_key)
    if root_id != 1 or sha256(root_raw).digest() != expected_mpkh:
        raise ValueError("Root public-key hash does not match captured ROM MPKH")

    return {
        "root_key_sha256": sha256(root_raw).hexdigest(),
        "certpk_sha256": check_certificate(image, 0x200, 0x848, 0x860, root_key),
        "certppa_sha256": check_certificate(image, 0xC00, 0xC4, 0xDC, signer_key),
        "ppa_body_sha1": check_body(image, 0xC00, 0x28, 0x30),
        "certisw_sha256": check_certificate(image, isw, 0x238, 0x250, signer_key),
        "isw_body_sha1": check_body(image, isw, 0x34, 0x3C),
    }


if __name__ == "__main__":
    rom_id = json.loads(ROM_ID_PATH.read_text())
    mpkh_blocks = [b for b in rom_id["blocks"] if b["type"] == "0x14"]
    if len(mpkh_blocks) != 1:
        raise ValueError("Expected one MPKH block")
    mpkh = bytes.fromhex(mpkh_blocks[0]["payload_hex"])
    original = MLO_PATH.read_bytes()
    original_result = verify(original, mpkh)
    with EMMC_BACKUP_PATH.open("rb") as backup:
        backup.seek(0x20000)
        sector_span = bytearray(backup.read(0xA200))
    if len(sector_span) != 0xA200 or sector_span[:len(original)] != original:
        raise ValueError("eMMC backup does not contain the exact MLO at 0x20000")
    pack_into("<I", sector_span, 0x10, 0x40306C00)
    sector_span[0xA040:0xA200] = b"\xA5" * 0x1C0
    modified_result = verify(sector_span, mpkh)
    if modified_result != original_result:
        raise ValueError("TOC or sector-tail mutation changed a certificate/body hash")
    print(json.dumps({
        "mlo_sha256": sha256(original).hexdigest(),
        "checks": original_result,
        "toc_destination_mutation": "0x00000000 -> 0x40306c00",
        "modified_bytes_outside_mlo": "0x1c0-byte final-sector tail in memory only",
        "cryptographic_checks_unchanged_after_toc_and_tail_mutation": True,
        "scope": "Offline cryptographic consistency only; ROM acceptance not tested",
    }, indent=2))
