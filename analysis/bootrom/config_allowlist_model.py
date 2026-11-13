#!/usr/bin/env python3
"""Offline address-filter model for ROM configuration interpreter 0x36e74.

This models only the visible address tests. It does not model fuse policy,
interconnect permissions, register side effects, or secure verification.
"""

from pathlib import Path
from struct import unpack_from

MASK = 0xFFFFFFFF


def allowed(address: int) -> bool:
    address &= MASK
    if ((address - 0x2C000) & MASK) < 0x3FFD3FFF:
        return True
    if ((address - 0x50000000) & MASK) <= 0x378:
        return True
    if ((address - 0x4C000000) & MASK) < 0xEC:
        return True
    if ((address - 0x4D000000) & MASK) < 0xEC:
        return True
    if ((address - 0x4E000000) & MASK) < 0x640:
        return True
    if ((address + 0xB5FFBF00) & MASK) < 0x200:
        return True
    if ((address + 0xB5FF7F00) & MASK) < 0x500:
        return True
    return False


if __name__ == "__main__":
    mlo = Path("firmware/codec-ce9.9.0/extracted/MLO").read_bytes()
    block = mlo[0x40A4 : 0x40A4 + 0x110]
    magic, active = unpack_from("<II", block)
    print(f"magic=0x{magic:08x} active=0x{active:08x}")
    for index in range(32):
        address, value = unpack_from("<II", block, 8 + 8 * index)
        if active & (1 << index) and (address or value):
            print(f"{index:02d} address=0x{address:08x} value=0x{value:08x} allowed={allowed(address)}")
    print("example allowed 0x4a004100:", allowed(0x4A004100))
    print("example denied  0x4030d000:", allowed(0x4030D000))
