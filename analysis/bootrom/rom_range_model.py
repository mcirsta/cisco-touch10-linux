#!/usr/bin/env python3
"""Offline model of the ROM range clamp at low alias 0x34380.

It intentionally mirrors the observed unsigned 32-bit branches and reports
whether the resulting transfer fits its selected address window. It does not
model the storage callback, authentication, or target hardware side effects.
"""

MASK = 0xFFFFFFFF


def clamp(address: int, length: int) -> tuple[int, int, int, int]:
    address &= MASK
    length &= MASK
    test = (address - 0x2C000) & MASK
    if test < 0x3FFD3FFF:
        lower, upper = 0x2C000, 0x3FFFFFFF
    else:
        wrapped = (address - 0x80000000) & MASK
        if wrapped < 0x80000000:
            lower, upper = 0x80000000, 0xFFFFFFFF
        else:
            lower, upper = 0x40304000, 0x4030BFFF
            in_sram = ((address + 0xBFCFC000) & MASK) < 0x8000
            if not in_sram:
                address = lower
    maximum = (upper - lower + 1) & MASK
    if length > maximum:
        length = maximum
    if length == 0:
        length = 0x200
    return address, length, lower, upper


if __name__ == "__main__":
    for address, length in [(0x40304000, 0x2000), (0x4030BE00, 0x2000), (0x40307E00, 0x6200), (0x4030BFF0, 0x2000), (0x4030DC00, 0x2000)]:
        out, size, lower, upper = clamp(address, length)
        end = out + size - 1
        print(
            f"in=0x{address:08x}/0x{length:x} "
            f"out=0x{out:08x}/0x{size:x} "
            f"window=0x{lower:08x}-0x{upper:08x} "
            f"end=0x{end:08x} overrun={max(0, end-upper)}"
        )
