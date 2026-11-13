# OMAP4460 ROM USB image-size alternatives

Offline-only review of this panel's captured 48 KiB ROM and saved signed
images. No device access or boot-state change was made.

## Can the exact signed chain be packed below the ROM limit?

The type-2 ROM USB receiver fixes its body destination at `0x40304000` and
rejects declared length zero or greater than `0x4030bfff - 0x40304000 =
0x7fff` at ROM `0x33254..0x3325e`. It receives one body, then enters the
in-memory TOC/CH and authentication path at `0x332b6`; it does not request a
second body. [USB state-machine trace](bootrom-usb-state-machine-2026-11-07.md).

The exact CE9.9.0 MLO has signed sections KEYS `0x960`, PRIMAPP `0x339c`,
and ISW `0x6040` bytes. Ignoring all inter-section padding, these signed
sections alone total `0x9d3c = 40,252` bytes, **7,485 bytes over** the
`0x7fff` USB ceiling before any TOC. The tested `0x200`-byte TOC layout
would make a compact package `0x9f3c = 40,764` bytes. The ROM name scanner
stops at its sentinel, so a shorter table may be possible, but even a
zero-byte table cannot make this signed chain fit. A byte-level suffix/prefix
overlap check of these three exact sections found zero bytes of compatible
overlap in any order; none is wholly contained in another. The signed
certificates fix each body's size and digest, so compressing or truncating
the exact ISW
would require a new signed loader or a verification flaw.

The ROM peripheral-image path at `0x34572` checks that both TOC map byte 6
(PRIMAPP) and byte 7 (KEYS) are present at `0x3458c..0x34596`. It then calls
secure selector 0 for KEYS and selector 2 for PRIMAPP at `0x344fa..0x34552`;
a nonzero selector-2 result branches to the fatal loop at `0x300a8`.
Therefore omitting PRIMAPP to fit KEYS plus the Cisco ISW does not pass this
visible gate. R&D at map byte 8 is optional. The existing 16,284-byte
KEYS+PPA USB image reaches the signed PPA but has no valid ISW.

## Local signed-image inventory

The shortest locally available same-root signed ISW is the exact Cisco
CE9.9.0 stage, `0x6040` bytes. The older reference MLO uses the same root
key hash but its ISW is longer, `0x629c`. The two OMAP4 phone `.2nd` images
contain approximately 15 KiB signed ISWs and would fit, but their `CertPK_`
root-key SHA-256 begins `5f4092ec...`, whereas this panel's burned MPKH
begins `8b846a5a...`. They are not an authenticated stage for this unit.
Scans of the saved Cisco package, its extracted kernel/rootfs/U-Boot, and
the reference eMMC/ext4 files found no shorter matching-key `CertISW`.
[Local loader inventory](omap4-hs-usb-loader-inventory-2026-11-07.md).

## Out-of-body pointer reuse is a conditional lab lead

The ROM copies each named TOC offset at `0x344ac` and, in the USB path,
computes `image_base + offset` for selected, KEYS, PRIMAPP, and optional
R&D at `0x345aa..0x34600`, without a visible received-length check. A
32-bit offset can wrap this addition to an address outside the received
USB body. The TOC-extent path at `0x343e0/0x34406` may compute a strange
span for a high offset, but its type-2 USB caller at `0x33038` retains only
the return code and name mask, discarding destination/span. It does not
block this pointer calculation in the visible ROM. Secure-side pointer
validation is absent from the 48 KiB capture and could reject it.

For example, a hypothetical warm-reset experiment could carry the exact
KEYS+ISW in a `27,552`-byte USB body while a PRIMAPP TOC entry points to a
previously loaded exact PPA in retained on-chip RAM. Targeting the known PPA
load address `0x40300dd0` from USB base `0x40304000` would require TOC offset
`0xffffcdd0` under 32-bit addition. Conversely, a USB body containing
KEYS+PPA could point its selected ISW item to preseeded DDR at `0x80000000`
using offset `0x3fcfc000`. Neither calculation proves that the secure monitor
accepts the pointer or that those bytes persist.
[TI's OMAP4460 erratum i727](https://www.ti.com/lit/er/swpz017l/swpz017l.pdf)
further warns that DDR
contents cannot be relied on after a warm reset. This is **not** a
standalone cold-boot recovery method: no reliable preseed survives a PoE
power cycle, the secure monitor may clear or reject the stale bytes, and
the board has not been observed entering USB from a warm reset.

The converse layout carries the already-tested KEYS+PPA body and points the
selected `2ND` entry at a full signed ISW preloaded in DDR before a warm
reset. That would avoid relying on a retained PPA certificate in secure
on-chip RAM, but still needs DDR to remain initialized and intact and the
secure monitor to accept an out-of-window selected pointer. [TI's OMAP4460
erratum i727](https://www.ti.com/lit/er/swpz017l/swpz017l.pdf) explicitly
says DDR contents cannot be guaranteed after warm reset. Neither layout has
been tested on this panel.

There is a concrete volatile boot-order mechanism worth a separate review.
The captured ROM reads a software-configuration pointer from `0x4a326a00`
and validates that it lies before `0x4a327000` (`0x336e6`). A type-1 record
has `word0 >> 8 == 0xCF00AA`, type byte 1, a word1 payload length, and a
payload starting at pointer+8. On success `0x30a7c` sets boot-context bit
`0x200`; `0x30e72` then takes four source codes from payload byte offsets
2, 4, 6, and 8. Source codes `E`/`F`/`G` use the same USB vtable, and the
chooser at `0x30b50..0x30b8a` invokes the USB receiver for those codes.
When its reset-reason word equals 1, ROM `0x30a44..0x30a5c` clears the
software-configuration pointer; on other reasons it can parse the record.
This suggests a RAM/SAR-only way to request USB on a warm reset, but the
record has not been exercised on this panel and the mapping of reset-reason
values has not been live-confirmed. It depends on an already bootable unit
and does not solve recovery after a failed cold boot.

The visible reset-time relocation table at ROM `0x38080..0x380bf` copies
only into `0x4030d000..0x4030d19f` and zeros
`0x4030d1a0..0x4030dc5b`. It does not clear the PPA or USB image regions.
Hardware reset/retention and hidden secure-ROM cleanup are unresolved.

## Timing of the demonstrated unsigned table

The USB length check and full body receive happen before `0x3451a` invokes
the unsigned speedup-table interpreter. Therefore that interpreter cannot
change the same transfer's `0x7fff` check. It has a filtered MMIO write/poll
surface but no visible write to ROM code, USB DMA registers, or OCMC image
memory. It could at most affect later hardware state or a subsequent boot,
for which no controlled bypass has been established.
