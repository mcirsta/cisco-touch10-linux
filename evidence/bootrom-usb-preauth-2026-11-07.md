# OMAP4460 USB Boot ROM: pre-authentication configuration audit

Date: 2026-11-07. This is an offline review of the Touch 10's captured
48 KiB ROM (`sha256:7fd0176dbdf06cfa42f147a5c0a923abb1f2fa269b82d0352fa02a5bd3b8efff`),
the saved USB ASIC ID, and the exact CE9.9.0 MLO and signed PPA. ROM
addresses use the low alias `0x30000..0x3bfff`. No device command, upload,
or state change was made for this audit.

## The configuration gate is enabled on this unit

The earlier Linux `/dev/mem` read of `0x4a002220` failed, but the saved
ROM GET_ID response resolves the relevant bit. At `0x317c6..0x317d6`, the
ROM reads bit 13 of that register and returns it as 0 or 1. The ASIC-ID
builder at `0x348dc` and `0x3490e..0x34912` places that result in bit 4
of response byte 6. The captured type-`0x01` block in
[`omap-rom-asic-id.json`](omap-rom-asic-id.json) has payload
`44 40 07 01`: response byte 6 is `0x07`, with bit 4 clear. Therefore
`STD_FUSE_CH_SPEEDUP_DISABLE=0` on this unit. The CH and speedup parsers
pass their fuse gate. Other runtime flags and input-format checks still
apply.

## CH records from USB

After the peripheral receiver completes an image, `0x332b6` calls
`0x32fd6` before the selected-image security services. `0x32fd6` maps
names in the first 512-byte TOC and enters `0x32f74` when `CHSETTINGS`
(map index 10) is present. `0x32f74` reads each present CH entry's 32-bit
section offset and computes `image_base + offset` with 32-bit wrap at
`0x32fa6..0x32fae`. No comparison to the received span occurs on this
path. Its caller then advances to the second TOC, so the first CH sector
precedes any ordinary signed `2ND`/`KEYS`/`PRIMAPP` sections. These steps
are in [`bootrom-ch-parser-2026-11-07.md`](bootrom-ch-parser-2026-11-07.md).

The four pointers are passed to `0x34774`: CHRAM is processed first,
followed by CHSETTINGS and CHFLASH. Each nonnull pointer is read as a
four-byte magic by `0x37380`; matching records also require byte `+4`
to be nonzero. `CHMMCSD` is forcibly skipped for USB because `0x32fc8`
sets flag bit 8. Context bit 6 can separately skip CHRAM; that bit starts
clear at `0x30a1e` but can be set by an optional boot configuration
record (`0x30af2..0x30b00`). The saved GET_ID resolves the fuse gate,
not this runtime bit. The USB wrapper discards the CH handler's return at
`0x32fd0`. Consequently this is a confirmed pre-authentication,
out-of-received-image **read and conditional handler-dispatch** path,
with the fuse gate known open on this panel and CHRAM subject to context
bit 6. It is not a USB data-readback interface.

### Concrete ROM-literal CHRAM alias

The exact ROM contains one CH record magic: `0xc0c0c0c2` at low alias
`0x348b8`, a literal used by the CH handler itself. The next byte,
at `0x348bc`, is `0x2d` (the start of Thumb code) and satisfies the
nonzero-valid-byte check. The USB type-2 image base is `0x40304000`.
For a CHRAM TOC entry, offset `0xbfd308b8` makes the 32-bit addition
produce `0x000348b8`. A first TOC can include a `CHSETTINGS` entry to
activate the CH route while giving that entry an offset of zero: its
pointer then addresses the TOC itself and fails the C1 magic check.
The CHRAM entry uses the wrapped offset. The TOC name scanner at
`0x34308` checks names and entry count, not these section extents.
This establishes a concrete static path through the ROM's magic and
valid-byte checks when context bit 6 is clear. **It has not been tried
on the unit.**

At `0x347a6..0x347ac` that path passes `0x348c0` (ROM instructions
misread as record fields) to `0x32346`. The field at record `+0x4c`
(`0x3490c`) is `0xea4101c6`; its low nibble `6` passes the handler's
early-return check. The field at `+0x48` (`0x34908`) is `0xeb012107`;
`0x32386..0x32392` would write it to fixed DMM and controller addresses
`0x4e000040` and `0x482af040`. Low bits 1 and 2 of the first field
select subsequent EMIF1 and EMIF2 setup through `0x3228e`, `0x32236`,
and `0x320dc`. Those routines use fixed register bases and fixed record
indexes. The caller supplies `R1=0` to `0x32346`, so its optional result
copy to a caller-supplied pointer is disabled. The misinterpreted code
words could disturb memory-controller state or stall boot; this is not a
demonstrated general memory-write primitive or control-flow hijack.

The ROM has no C1, C3, or C4 magic occurrence. The exact MLO and exact
PPA contain no C1–C4 occurrence. Thus this particular ROM-alias match
is specific to CHRAM. An in-buffer forged CH record could supply its own
configuration values; that is the visible configuration feature, still
subject to each sub-handler's fixed hardware destinations. `CHSETTINGS`
at `0x30c44` reads a flag word and fixed fields through record `+0x60`;
it calls fixed PRCM helpers `0x31d44`, `0x31d9c`, `0x31e1c`, and
`0x31f16`. Its calls to switch helpers `0x31ae6` and `0x31ca0` use
constant index 9, not a record-derived jump-table index. There is no
variable-size copy or indirect branch in that path. `CHFLASH` uses the
`0x50000000` controller block (`0x30566`, `0x304fc` with fixed
selector 0). We found no branch from these handlers to a USB-provided
code pointer or ordinary SRAM destination.

## Speedup table before verification

The selected-image path calls `0x344fa`; unless context flag bit 3 skips
it, `0x3451a..0x3451e` invokes `0x36e74` on selected section pointer
`+0xa4` **before** secure services 0, optional 1, and 2 at `0x3452c`,
`0x3453a`, and `0x3454e`. The table is accepted when its first word is
`0x16793a22`; exactly `0x110` bytes are copied to a `0x114`-byte local
stack area, then exactly 32 entries are interpreted. The selected
pointer comes from TOC offset arithmetic at `0x34572..0x3460e`, with no
received-span comparison there. Therefore a host-edited table can cause
permitted register writes or polls before its later signature failure.
The saved ASIC ID shows the fuse does not disable this path. The exact
Cisco MLO table's ten nonzero entries all fail the visible address filter.

The filter at `0x36ebc..0x36efa` admits a broad low range
`0x0002c000..0x3ffffffe` and narrow GPMC, EMIF, DMM, and PRCM windows.
It excludes OCMC SRAM `0x4030xxxx`, fuse address `0x4a002220`, the
firewall region, and the main MMC controller. Each entry can write a
word (or a low-range halfword) or poll a register. The polls have no
visible timeout. A control-register write can affect subsequent boot,
but we have not found a direct path to overwrite executable SRAM or to
disable signature checking. See
[`bootrom-config-interpreter-2026-11-07.md`](bootrom-config-interpreter-2026-11-07.md)
for the exact allowlist and modes.

One proposed indirect route was to use an allowed DMM_LISA_MAP write to
remap the interpreter's broad low range into executable SRAM or DDR, then
use a second table entry to write there. [TI's OMAP4460 memory map,
§2.2/Table 2-1, pp. 293–294](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=294)
places `0x00000000..0x3fffffff` in boot/GPMC quarter Q0, on-chip ROM/SRAM
in Q1, and DDR in Q2/Q3. The [DMM LISA description,
§15.2.3.5.1.2](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=3265)
maps external EMIF memory within the DDR address space; it does not remap
Q0 into Q1 on-chip SRAM. This closes that particular two-entry route to an
executable-SRAM write. It does not characterize every permitted GPMC or
PRCM register side effect.

The ROM itself contains the speedup magic once, at `0x36f54`. A wrapped
selected-section offset `0xbfd32eb0` from USB base `0x40304000`
would set its `+0xa4` table pointer to that literal. Offline decoding of
the following ROM code as a table yields active mask `0x3ffd3fff`;
entries 0–6 fail the address filter. Entry 7 is an equality poll for
`0x1c40d104` at low address `0x07dbf300`. Its mapping and return are
unknown, and a failed poll could hang forever. This ROM alias supplies
no attacker-selected values and offers no evident execution advantage.

## Conclusion and remaining proof gap

The USB ROM has a **real fuse-enabled pre-authentication configuration
surface** on this panel: CH section offsets lack a received-span bound,
one wrapped CHRAM pointer meets the ROM's own record checks when context
bit 6 is clear, and the
speedup table can perform allowlisted operations before authentication.
Neither route has yielded a code pointer, executable-SRAM overwrite,
signature bypass, or useful ROM readback in the visible code. The
CHRAM ROM alias is especially likely to disrupt boot because it treats
instruction words as DRAM setup values. A cold power cycle should clear
the transient configuration, but that outcome has not been tested.
Further work should model concrete controller side effects and the
selected-image secure-service transition offline before any live input.
