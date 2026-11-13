# Pre-verification USB configuration: permitted MMIO effects

Date: 2026-11-07. This is an offline follow-up to the [fuse and parser
trace](bootrom-usb-preauth-2026-11-07.md). The captured ROM's speedup
interpreter at `0x36e74` can process a host-supplied table before secure
services authenticate the image. Its address filter at `0x36ebc`–`0x36efa`
allows a broad low-address Q0 range and narrow DMM, EMIF, GPMC, and PRCM
register windows. No image was uploaded for this follow-up.

| Allowed target | What the controller can affect | Security assessment |
| --- | --- | --- |
| `0x0002c000..0x3ffffffe` | Boot/GPMC Q0 space. [TI's global memory map, Table 2-1](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=294) routes this quarter separately from on-chip ROM/OCMC in Q1 and DDR in Q2/Q3. | A low-range write does not directly reach executable OCMC at `0x4030xxxx` or DDR at `0x80000000` and above. An external GPMC device could respond if attached and configured; no useful device is established on this board. |
| DMM `0x4e000000..0x4e00063f` | DMM_LISA_MAP sections select external EMIF memory and interleaving ([TI §15.2.3.5.1.2](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=3265)). | Programming LISA_MAP cannot change L3's Q0 routing into Q1 OCMC or Q2/Q3 DDR. This closes the proposed two-entry write: remap low range, then use the broad low-range write to overwrite code. Other DMM side effects remain possible. |
| GPMC `0x50000000..0x50000378` | [GPMC_CONFIG7_i](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=3424) changes base and size of an *external* chip select within Q0. The [register inventory](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=3519) covers timing/configuration, NAND data/commands, prefetch, ECC, and status. | No register here remaps on-chip SRAM/ROM, selects eMMC as a GPMC device, or chooses a general system-memory DMA destination. Bad settings can disrupt an external device or boot. The [saved kernel configuration](ce990-kernel-config-2026-11-07.txt) has `CONFIG_MTD` unset, and the [boot log](console-inventory.log) says `hwmod gpmc not found`; that is evidence against, not proof of absence of, an attached usable GPMC device. |
| PRCM `0x4a004100..0x4a0042ff`, `0x4a008100..0x4a0085ff` | These cover [CM1 clock generators](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=804) and [CM2 clock generators](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=890), including MPU/core/USB DPLL settings and EMIF/GPMC frequency updates. Module clock gates, PRM reset, firewall, and fuse controls are outside the allowed windows. | An attacker-supplied table could perturb clocks before verification, but no specific signature-bypass or controlled memory-write effect follows from the mapped registers. A malformed clock change is a credible hang/boot-failure path. |

The allowed `CM_SHADOW_FREQ_CONFIG1` at `0x4a004260` requests an EMIF
frequency update. [TI errata i728 and i729](https://www.ti.com/lit/er/swpz017l/swpz017l.pdf#page=73)
document an unstable DDR clock when a frequency update coincides with an
EMIF self-refresh timeout and access, and possible DDR protocol/data
corruption when an update overlaps a **SoC warm reset** and access. Erratum
[i755](https://www.ti.com/lit/er/swpz017l/swpz017l.pdf#page=83)
documents a PRCM hang if CORE DPLL dividers M2 and M5 are updated together.
These are conditional fault effects, not evidence that an image with a bad
signature could execute. A USB bus reset is not the SoC warm reset in i729.
The ROM's exact DRAM state and access pattern at the pre-verification point
have not been shown to meet these erratum conditions.

## Unsigned table placement and proof gap

The [previously tested compact `2ND` format](rom-exact-ppa-2nd-20261107T013700Z-usb.log)
keeps the exact signed KEYS
section at image offset `0x200` and PRIMAPP at `0x0c00`. Its selected
section currently starts at `0x0c00`, which puts `selected+0xa4` inside
the signed CertPPA. An offline layout review found a way to keep those
signed bytes intact: change the unsigned outer `2ND` TOC item's start to
zero and size to `0x200`, then place the 272-byte speedup table at image
offsets `0x00a4..0x01b3`. The TOC terminator is at `0x60`, and the table
ends before KEYS. ROM `0x344ac`–`0x344ca` has no zero-start rejection;
`0x345d4`–`0x3460e` forms the selected pointer and passes it toward the
interpreter. This is a **static reachability candidate**, not a live proof:
the unavailable secure-side code could reject the modified selected
section before the interpreter is reached.

A writable marker with safe readback is still missing. The closest candidate,
[GPMC_ECC_SIZE_CONFIG at `0x500001fc`](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=3544),
could affect NAND reads if that path is active. A bad selected image may
also halt before Linux can read the register, and the ROM USB protocol
provides no post-BOOT register readback. Consequently this candidate has
not been sent to the panel; a forced hang would only prove dispatch and
would not advance a signature bypass.

**Later live follow-up:** [a read-only equality-poll pair](bootrom-speedup-poll-2026-11-07/README.md)
provided a controlled reachability test without touching an MMIO register.
It compares the ROM's own word at `0x36f54` to either its known value or a
one-bit-different value. Both 16,284-byte images preserve the exact signed
KEYS and application region, and differ from each other only at offset
`0xb0`. Under the user's separate authorization, the pass image reached the
PPA fatal banner, while the stall image transferred fully but produced no
PPA banner during 120 seconds of serial capture. A cold cycle restored
Linux. This strongly supports pre-verification table execution; it does not
establish a signature bypass.

**Ranking after this check:** The pre-verification configuration interpreter
remains the strongest *USB* research lead because the fuse gate is open and
host-selected, filtered MMIO operations occur before authentication. The
CH offset/record path is next; it has out-of-received-image reads but only
fixed-purpose handlers. DMA reset/count is a hardware-lifetime hypothesis,
and EP0/TOC-extent reviews have not shown a useful memory effect. None is
a reproduced ROM exploit. The next offline check is to trace whether any
specific permitted clock operation can affect the secure-service verifier
while preserving enough of the boot environment to observe an outcome.
