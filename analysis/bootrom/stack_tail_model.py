#!/usr/bin/env python3
"""Offline gate and stack geometry for the ROM storage-read candidate.

Frame sizes come from the listed ROM instructions. This is a static model;
it does not prove that the secure monitor accepts a modified outer TOC or
that the panel takes the modeled MMC boot source.
"""

from pathlib import Path
from struct import unpack_from

from rom_range_model import clamp

MLO = Path("firmware/codec-ce9.9.0/extracted/MLO").read_bytes()
start, size = unpack_from("<II", MLO, 0)
assert start == 0x4000 and size == 0x6040
sector_size = 512
sectors = (size + sector_size - 1) // sector_size
transfer_bytes = sectors * sector_size
unsigned_tail = transfer_bytes - size


def section_sectors(name: bytes) -> int:
    """Match a named outer TOC record and reproduce 0x32a4c..0x32a5c."""
    entries = [MLO[i : i + 32] for i in range(0, 512, 32)]
    matches = [entry for entry in entries if entry[20:32].split(b"\0", 1)[0] == name]
    assert len(matches) == 1, name
    offset, length = unpack_from("<II", matches[0])
    return ((offset + length - 1) // sector_size) - (offset // sector_size) + 1


keys_sectors = section_sectors(b"KEYS")
ppa_sectors = section_sectors(b"PRIMAPP")
assert (keys_sectors, ppa_sectors, section_sectors(b"MLO")) == (5, 26, 49)
# 0x32aee..0x32af0 changes the fourth (selected) descriptor's first read
# count from 49 sectors to one, before both the capacity check and callback.
initial_selected_sectors = 1
initial_sectors = keys_sectors + ppa_sectors + initial_selected_sectors
buffer_sectors = (0x4030C000 - 0x40304000) // sector_size
print(f"Initial read: KEYS {keys_sectors} + PRIMAPP {ppa_sectors} + selected header {initial_selected_sectors} = {initial_sectors} sectors")
print(f"Initial 32 KiB buffer capacity: {buffer_sectors} sectors")
assert initial_sectors == 32 and initial_sectors <= buffer_sectors

# 0x308d0 resets the stack pointer. These are nested frames on the path to
# the eMMC FIFO copy: function address -> bytes pushed plus local allocation.
frames = [
    ("0x30a18 main", 16),
    ("0x30a7c boot chooser", 32 + 0x20),
    ("0x32dea storage boot", 32 + 0x240),
    ("0x32a74 section loader", 36 + 0x84),
    ("0x33bba MMC reader", 48),
    ("0x36c62 sector reader", 32),
    ("0x35f30 FIFO copy", 20),
]
sp = 0x4030D000
for name, frame in frames:
    sp -= frame
    print(f"{name}: SP=0x{sp:08x}")

fifo_saved_lr = sp + 16  # PUSH {R4-R7,LR}; later POP {R4-R7,PC}
destination = 0x40306C00  # 512-byte aligned TOC +0x10 value for this model
clamped_destination, clamped_length, lower, upper = clamp(destination, transfer_bytes)
assert (clamped_destination, clamped_length) == (destination, transfer_bytes)
assert lower <= destination <= upper
last_sector = destination + (sectors - 1) * sector_size
tail_start = destination + size
tail_end = destination + transfer_bytes - 1
matching_destinations = [
    address for address in range(lower, upper + 1, sector_size)
    if address + size <= fifo_saved_lr < address + transfer_bytes
]
assert matching_destinations == [destination]
saved_lr_image_offset = start + (fifo_saved_lr - destination)
saved_lr_emmc_offset = 0x20000 + saved_lr_image_offset
print(f"MLO section: {sectors} sectors, 0x{transfer_bytes:x} bytes")
print(f"last sector destination: 0x{last_sector:08x}")
print(f"ROM clamp leaves 0x{destination:08x}/0x{transfer_bytes:x} unchanged; overrun={max(0, tail_end-upper)} bytes")
print(f"bytes after signed ISW body: {unsigned_tail} at 0x{tail_start:08x}..0x{tail_end:08x}")
print(f"FIFO copy saved LR: 0x{fifo_saved_lr:08x}")
print(f"saved LR offset in unsigned tail: {fifo_saved_lr-tail_start} bytes")
print(f"aligned SRAM destinations placing unsigned tail over LR: {[hex(x) for x in matching_destinations]}")
print(f"corresponding MLO/eMMC offsets: 0x{saved_lr_image_offset:x}/0x{saved_lr_emmc_offset:x}")
print("saved LR within unsigned tail:", tail_start <= fifo_saved_lr <= tail_end)
assert tail_start <= fifo_saved_lr <= tail_end
assert saved_lr_image_offset == 0xA054
