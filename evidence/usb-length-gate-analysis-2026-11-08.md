# Exact OMAP4460 HS ROM USB length gate

Offline review of the saved 48 KiB ROM and the CE9.9.0 MLO. ROM addresses
below are its low alias (`0x3xxxx`). No panel command or storage change was
made for this review.

## The gate is before the image body and configuration interpreter

USB BOOT sends a four-byte length to `0x33092`. The ROM receives that length
into a stack word (`0x33200`–`0x33218`). After confirming successful transfer,
it executes:

| Address | Instruction | Effect |
| --- | --- | --- |
| `0x33254` | `LDR R1,[SP+length]` | Reads the full 32-bit host length. |
| `0x33256` | `CBZ R1,error` | Rejects zero. |
| `0x33258` | `LDR R2,=0x4030bfff` | Sets the fixed end of the receiving window. |
| `0x3325a` | `SUBS R2,R2,R7` | On this unit, `R7=0x40304000`, so `R2=0x7fff`. |
| `0x3325c` | `CMP R2,R1` | Compares the full 32-bit words. |
| `0x3325e` | `BCC error` | Rejects host length greater than `0x7fff` **unsigned**. |
| `0x33260`–`0x33270` | transfer setup | Only now arms the body receiver at fixed destination `R7`. |

The use of `BCC` rules out a signed-negative or high-bit length encoding as
a bypass. The largest accepted body is **32,767 bytes**. The rejected-length
path closes the transport at `0x332c4`–`0x332d6`; no image-body receive is
armed by that path. The previous boundary tests rejected 32,768 and 34,816
declared bytes after the first sector; see `ROOT-AND-BACKUP.md` and the
[USB state-machine audit](bootrom-usb-state-machine-2026-11-07.md).

`R7` is set at `0x330d6`–`0x330e0` after `0x3179c` reads
`CONTROL_STATUS=0x4a0022c4` bits 10:8. Only hardware type 3 selects the
lower base `0x40300000` and a 49,151-byte cap; the panel is type 2 and uses
`0x40304000`. GET_ID and BOOT packet contents do not select this type.
[TI's OMAP4 U-Boot register definitions](https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/include/asm/arch-omap4/omap.h?id=e79de74103d9d411aa6b4e63582c5d7075c6a7a8)
identify the same control-status address and device-type bit position.

The USB body receiver programs the checked destination and count into MUSB
RX DMA registers at `0x35226`–`0x3522e`. Its later completion calculation
narrows an observed byte count to 16 bits at `0x35498`, but that occurs
**after** the length check and does not alter the programmed DMA count.
Ordinary DMA completion therefore cannot use a 16-bit wrap to request a
larger body. A controller reset/count fault would be a separate hardware
behavior, not a bypass visible in this ROM code; see
[the DMA follow-up](bootrom-usb-dma-reset-followup-2026-11-07.md).

Only after the complete, accepted body does `0x332b6` call the TOC/CH parser
at `0x32fd6`, which can later reach the unsigned speedup table at `0x36e74`.
Consequently the proven speedup write/poll capability cannot change the
length check for **that same BOOT transaction**. The table's address filter
excludes OCMC SRAM and the control-status/fuse registers. It numerically
includes the low Boot ROM alias, but that alias is read-only; no direct write
to executable ROM code, the current length value, or receiver state has been
observed. The [separate low-address handoff audit](usb-ppa-handoff-2026-11-08.md)
identifies two PPA handoff literals within
the allowed numeric range whose physical mapping remains unresolved.

## Packing the existing signed stages

The exact CE9.9.0 sections are KEYS `0x960`, PRIMAPP/PPA `0x339c`, and
Cisco ISW `0x6040`. The three byte-exact signed sections alone total
`0x9d3c = 40,252` bytes, **7,485 bytes beyond the USB limit before any
TOC**. Pairwise suffix/prefix checks found no compatible overlap between
their bytes. The existing `0x200`-byte TOC layout would make the packed image
`0x9f3c = 40,764` bytes; even a hypothetical zero-byte TOC would still be
too large. KEYS+ISW without
PRIMAPP would be `0x6ba0 = 27,552` bytes, but the ROM checks that the
selected, KEYS, **and PRIMAPP** TOC indexes are present at
`0x34586`–`0x34596`; an absent PRIMAPP returns before the security calls.
At `0x3454c`–`0x3454e` it invokes secure selector 2 on the PRIMAPP pointer
unconditionally, and at `0x34552` branches to fatal on failure.
Adding a dummy PRIMAPP TOC entry without the signed PPA bytes does not supply
the certificate/body the selector needs. Whether a pointer into preexisting
SRAM could satisfy it requires a separate, unproven SRAM-retention and
security-policy path; no cold USB boot supplies those bytes there.

The only other local signed MLO has the same KEYS and PPA but a larger
`0x629c` ISW. No smaller ISW under this unit's matching root key is available
in the local CE9.9.0 inventory; smaller phone loaders use a different key.
The full packed body would end at `0x4030df3b` if simply received at this
unit's fixed USB base, past the `0x4030bfff` receiving window and into ROM
workspace near `0x4030d000`. Raising the count without a new destination or
staging scheme would therefore also overwrite active ROM state.

## Remaining routes

1. A *separate* pre-authentication memory corruption or control-flow flaw
   would be needed to change the ROM receiver's destination/count or call a
   ROM receive API again. The current CH and speedup findings have not
   provided such a write or branch.
2. A shorter **genuinely signed** ISW under the panel's accepted keys could
   make a complete compact image fit, if one exists. The two local MLOs do
   not. Repacking cannot change the signed body lengths or hashes.
3. A retained-SRAM scheme would require a demonstrated warm reset into USB
   boot with known signed PPA bytes still at an accepted pointer. Neither
   condition has been established on this panel, and the ROM/secure monitor
   may validate pointer ranges independently.

The current USB flaw gives a reliable pre-verification configuration effect
and a confirmed route to executing the existing signed PPA, but it does not
itself patch the 32,767-byte receive gate.
