# OMAP4460 ROM pre-verification configuration interpreter

Scope: offline disassembly of this Touch 10's captured 48 KiB ROM and the
exact CE9.9.0 MLO. Addresses below use the ROM low alias. No live device
command or state change was made.

## Entry and ordering

The storage section loader first reads KEYS, PRIMAPP, and one 512-byte sector
of the selected MLO. At `0x32b38` it calls `0x344fa` before the later full
MLO read. In `0x344fa`, a context-halfword bit 3 can skip the interpreter
(`0x3450e`–`0x34512`); the raw storage context is initialized to zero at
`0x32e36`–`0x32e42`, and no setter for that bit was identified on its raw
open path. Otherwise `0x3451a` passes the selected header pointer plus
`0xa4` to `0x36e74`. Its return value affects a trace code but does not stop
the subsequent secure-service 0, optional 1, and 2 calls at `0x3452c`,
`0x3453a`, and `0x3454e`. Selected-image service 3 occurs only after the
full read. Thus any permitted configuration operation happens before the
selected-image signature check.

The type-2 peripheral path also builds selected-section pointers from the
received TOC at `0x34572`–`0x3460e` and calls the same `0x344fa`. Its
receiver is limited to 32,767 bytes, but the previously tested compact
16,284-byte signed-PPA `2ND` form reaches this security sequence. A changed
configuration table over USB is a plausible *conditional* input to this
interpreter, not a demonstrated useful register write on the panel.

## Gate and table format

`0x36e7a` calls `0x317c6`, which reads register `0x4a002220` and extracts
bit 13. When the bit is 1, `0x36e74` returns before checking the image
header. TI labels this read-only fuse bit
[`STD_FUSE_CH_SPEEDUP_DISABLE`](https://www.ti.com/jp/lit/pdf/swpu316):
1 disables CH/speedup, 0 enables them. A previous read-only Linux attempt
to read this register returned `Bad address`. The saved ROM GET_ID response
nevertheless resolves bit 13: `0x317c6` supplies response byte 6 bit 4 at
`0x3490e`, and the captured byte is `0x07`. The bit is **0** on this unit,
so this fuse gate is enabled. See
[`bootrom-usb-preauth-2026-11-07.md`](bootrom-usb-preauth-2026-11-07.md).

If enabled, the interpreter requires magic `0x16793a22` at header `+0xa4`
(`0x36e80`–`0x36e86`) and copies exactly `0x110` bytes to a `0x114`-byte
local area (`0x36e8e`–`0x36e96`). There is no variable-length copy here.
The copied layout is magic, a 32-bit active-entry mask, 32 address/value
pairs of eight bytes each, and two 32-bit operation-mode bitmaps. The loop
at `0x36ea6`–`0x36f4e` visits exactly 32 entries. The source buffer for
the exact MLO lies at file offsets `0x40a4..0x41b3`, entirely inside its
first MLO sector and the `CertISW` signed prefix (`0x4000..0x4237`). An
attacker can change those bytes before authentication, but the later
signature check would reject the edited certificate unless another bypass
exists.

## Address and operation constraints

For an active entry, `0x36ebc`–`0x36efa` admits these target addresses:

| Inclusive address range | Hardware class from OMAP4 maps |
| --- | --- |
| `0x0002c000..0x3ffffffe` | Low boot/GPMC address space, including the ROM's low alias; actual writability depends on its mapping. |
| `0x50000000..0x50000378` | GPMC controller registers. |
| `0x4c000000..0x4c0000eb`, `0x4d000000..0x4d0000eb` | EMIF1 and EMIF2 controller registers. |
| `0x4e000000..0x4e00063f` | DMM registers. |
| `0x4a004100..0x4a0042ff`, `0x4a008100..0x4a0085ff` | PRCM clock/PLL control windows. |

The hardware labels follow [TI's OMAP4 U-Boot register map](https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/mach-omap2/omap4/prcm-regs.c?id=e79de74103d9d411aa6b4e63582c5d7075c6a7a8),
its [EMIF definitions](https://android.googlesource.com/platform/external/u-boot/+/refs/heads/android-tv-s-beta3/arch/arm/include/asm/emif.h),
and the [OMAP4 DMM address map](https://cos.googlesource.com/third_party/kernel/+/9f9d2760da8c7f94fae119fac3e13d5a1702f8f0/arch/arm/mach-omap2/omap_hwmod_44xx_data.c).
This mapping identifies register classes, not the effect of an arbitrary
value at each offset.

Mode 0 writes the supplied value as a word, except an odd target in the
low-address range becomes a halfword write to the even address (`0x36f20`–
`0x36f2e`). Modes 1 and 2 poll a selected bit until clear or set; mode 3
polls for exact equality (`0x36f30`–`0x36f48`). The poll loops have no
visible timeout, so a permitted malformed entry could stall boot if the
fuse allows the interpreter. The filter excludes the fuse register
`0x4a002220`, on-chip SRAM at `0x4030xxxx`, L3 firewall registers at
`0x4a20xxxx`, and the main MMC controller region. No direct security-fuse
or firewall-disable write is visible through this interpreter. Most
indirect effects through memory clocks or address mapping remain untested.

A later [USB-path follow-up](bootrom-usb-preauth-2026-11-07.md) checked one
two-entry address-mapping idea: an allowed DMM_LISA_MAP write cannot turn
the interpreter's Q0 low-address target range into Q1 on-chip SRAM or
Q2/Q3 DDR. TI's L3 quarter routing fixes those regions before DMM section
mapping. Other permitted register side effects still require review.

The exact Cisco MLO has active mask `0xffffffff` and ten nonzero entries.
All ten target `0x480049xx` or `0x48004dxx`; the remaining 22 entries
target zero. Every one is rejected by the visible allowlist. Mode bits
for entries 8 and 9 are set in the second mode bitmap, but their addresses
are rejected before polling. The existing
[`config_allowlist_model.py`](../analysis/bootrom/config_allowlist_model.py)
reproduces the boundary checks, including denial of `0x4030d000` and
`0x4a002220`.

## Assessment

The parser is a deliberate pre-verification configuration feature with a
fixed-size table and restrictive target filter. The exact installed MLO
does not exercise its write or poll operations. A modified image could
present allowed clock, memory-controller, or GPMC values before its later
signature failure if the addressed register accepts the access. The fuse
gate is enabled, but no security-relevant side effect has been shown on
this panel. This is a conditional attack
surface and possible boot-stall path, not a demonstrated ROM code-execution
or signature-bypass vulnerability.
