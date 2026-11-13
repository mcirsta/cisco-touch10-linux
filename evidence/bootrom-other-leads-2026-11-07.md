# OMAP4460 Boot ROM: secondary parser and USB leads

Scope: offline disassembly of this Touch 10's captured 48 KiB ROM and the
exact CE9.9.0 MLO. ROM addresses below use the low alias. No live device
command or firmware change was made. These are reachable-code observations,
not demonstrated security bypasses.

## TOC extent undercount (candidate B)

`0x343e0` scans at most sixteen 32-byte TOC entries. It updates its result
only when an entry's **start** is greater than every previous start, then
returns that entry's `start + size` (`0x343ea`–`0x34402`). It can therefore
return less than the largest end. The synthetic offline case in
`analysis/bootrom/toc_extent_model.py` returns `0x1100` for entries whose
true largest end is `0x10800`, an undercount of 63,232 bytes. The exact MLO
has no undercount (`0xa040` both ways).

On the type-2 peripheral path, `0x33038` calls `0x34406`, which computes
this extent and clamps it through `0x34380`. However, the caller stores the
computed destination and extent in separate stack slots that it does not
read afterward (`0x33028`–`0x33054`). It checks only the success/failure
return from `0x34406`. The other visible caller, `0x32d08`, takes the
type-3 branch inside `0x34406` and does not call `0x343e0`. Thus the
undercount is a real arithmetic defect but **no effect from the incorrect
result is established on either visible caller**.

Separately, after USB reception `0x332b6` calls `0x32fd6` and eventually
`0x346ec`; its nonzero selected-name branch `0x34572` derives KEYS,
PRIMAPP, and selected-image pointers directly from TOC offsets without a
visible comparison against the received span before passing them to secure
services (`0x34598`–`0x34618`). These pointers can exceed the data
received, but that concern is independent of the `0x343e0` undercount. The
public ROM code does not establish whether the secure services reject or
dereference such pointers, nor any way to return the pointed-to bytes to
the host. Classification: **candidate B undercount has no visible used
output; separate out-of-received-span pointer effect unproved**.

## Configuration interpreter (candidate C)

`0x344fa` calls `0x36e74` on selected-image header offset `+0xa4` before
its visible services 0, optional 1, and 2. The interpreter first checks
bit 13 of register `0x4a002220` via `0x317c6`, then requires magic
`0x16793a22`, copies exactly `0x110` bytes to its stack, and processes up
to 32 active entries. The fixed copy fits within the selected image's
first 512-byte sector. The permitted target ranges visible at
`0x36ebc`–`0x36efa` are:

- `0x0002c000..0x3ffffffe`
- `0x50000000..0x50000378`
- `0x4c000000..0x4c0000eb` and `0x4d000000..0x4d0000eb`
- `0x4e000000..0x4e00063f`
- `0x4a004100..0x4a0042ff` and `0x4a008100..0x4a0085ff`

For an active entry, `0x36f20`–`0x36f2e` can write a word or halfword;
other mode bits poll a target register. The exact signed MLO's ten nonzero
entries all target `0x480049xx` or `0x48004dxx`, outside these permitted
ranges. The 22 zero entries are also denied. The offline model
`analysis/bootrom/config_allowlist_model.py` reproduces those results.
An edited, unauthenticated selected header might supply an allowed target
before service 3 validates that image, but the fuse gate's value on this
unit and any security-relevant effect of an allowed write are unestablished.
Classification: **pre-verification MMIO interpreter, conditional on fuse and
target effects; no bypass demonstrated**.

## CH offsets

On the USB path, `0x332b6` calls `0x32fd6` after a completed image receive.
If its first TOC includes `CHSETTINGS`, `0x33002` calls `0x32f74` before
advancing to a second TOC at image `+0x200`. `0x32f74` takes up to four
recognized CH entry offsets and makes pointers by `image_base + offset`
(`0x32f9c`–`0x32fb0`), without a visible received-length check. It passes
those pointers to `0x34774`, which, if the same bit-13 fuse gate permits,
tests record magics and dispatches CH settings/RAM/flash/MMC handlers.
Thus attacker-selected offsets can make the ROM probe beyond received USB
bytes before the later image security services. The visible checks require
a matching magic and additional record flags before handler calls. We have
not found a readback channel, a reliable out-of-bounds write, or a route
past the HS image checks. Classification: **unbounded pointer construction
and conditional read/handler dispatch; exploit effect unproved**.

## USB receive-completion count

The USB receive ISR at `0x354dc` computes a cumulative byte count from the
current destination pointer minus the start pointer, plus current RXCOUNT,
then truncates it to 16 bits with `UXTH R4,R2` at `0x35520`. It compares that count
with the requested count at `0x35524`, but the FIFO copy at `0x35538` uses
the current RXCOUNT (`R5`), and the destination pointer is updated in full
width at `0x35548`–`0x3554c`. The generic USB image path at `0x33092`
accepts at most 32,767 bytes on this type-2 unit; its separate framing
reads are four bytes. No reachable caller requesting 64 KiB or more was
identified in this pass. Classification: **16-bit completion-state concern,
no demonstrated buffer overrun**.

None of these secondary leads currently outranks the storage-path range
clamp candidate. The most useful next evidence is the value of the CH
disable fuse on this unit and secure-service behavior when a TOC section
pointer exceeds the received image. Those are not established by
the public ROM alias alone.
