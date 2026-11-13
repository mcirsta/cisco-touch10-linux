#!/usr/bin/env python3
"""Verify the exact Cisco MLO's ISW body hash and RSA certificate signature.

This is an offline consistency check of the bytes in the local MLO. It does
not emulate the ROM's secure monitor or prove that any modified TOC boots.
"""

from hashlib import sha1, sha256
from pathlib import Path
from struct import pack_into, unpack_from

MLO = Path("firmware/codec-ce9.9.0/extracted/MLO")
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def verify_isw(image: bytes) -> tuple[bool, bool, bytes, bytes]:
    toc_offset, toc_size = unpack_from("<II", image, 0)
    if image[20:24] != b"MLO\0" or image[toc_offset : toc_offset + 8] != b"CertISW\0":
        raise ValueError("Unexpected MLO TOC or CertISW marker")
    if toc_size != 0x6040:
        raise ValueError("Unexpected ISW section size")
    cert = toc_offset
    body_offset, body_size = unpack_from("<II", image, cert + 0x34)
    body = image[cert + body_offset : cert + body_offset + body_size]
    if len(body) != body_size:
        raise ValueError("Truncated ISW body")
    stored_body_sha1 = image[cert + 0x3C : cert + 0x50]
    body_ok = sha1(body).digest() == stored_body_sha1

    key_offset = 0x200 + 52 + 276 + 4
    key_id, _, _, modulus_size, exponent = unpack_from("<5I", image, key_offset)
    signer_key_id = unpack_from("<I", image, cert + 0x24C)[0]
    if key_id != 2 or signer_key_id != key_id or modulus_size != 256 or exponent != 65537:
        raise ValueError("Unexpected ISW signer key")
    modulus = int.from_bytes(image[key_offset + 20 : key_offset + 276], "little")
    signature = int.from_bytes(image[cert + 0x250 : cert + 0x350], "big")
    recovered = pow(signature, exponent, modulus).to_bytes(256, "big")
    cert_hash = sha256(image[cert : cert + 0x238]).digest()
    padding = recovered[: -len(SHA256_DIGEST_INFO) - 32]
    expected_padding = b"\x00\x01" + b"\xff" * (len(padding) - 3) + b"\x00"
    cert_ok = (
        padding == expected_padding
        and recovered[-len(SHA256_DIGEST_INFO) - 32 : -32] == SHA256_DIGEST_INFO
        and recovered[-32:] == cert_hash
    )
    return body_ok, cert_ok, stored_body_sha1, cert_hash


if __name__ == "__main__":
    original = MLO.read_bytes()
    original_result = verify_isw(original)
    modified_toc = bytearray(original)
    pack_into("<I", modified_toc, 0x10, 0x40307E00)
    modified_result = verify_isw(modified_toc)
    print("original body SHA-1 valid:", original_result[0])
    print("original ISW RSA/SHA-256 valid:", original_result[1])
    print("modified TOC body SHA-1 valid:", modified_result[0])
    print("modified TOC ISW RSA/SHA-256 valid:", modified_result[1])
    print("body SHA-1:", original_result[2].hex())
    print("certificate SHA-256:", original_result[3].hex())
    if not all(original_result[:2] + modified_result[:2]):
        raise SystemExit("Signature or body hash check failed")
