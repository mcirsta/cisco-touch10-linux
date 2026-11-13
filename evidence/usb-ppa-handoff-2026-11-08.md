# USB speedup table versus the signed PPA handoff

Review of this unit's 48 KiB OMAP4460 ROM capture and exact CE9.9.0 signed
PPA, followed by the separately authorized RAM-only read-poll pair below.
The static review used no device command. ROM addresses use the low alias;
PPA addresses use its `0x4030xxxx` load address.

## A numerical overlap worth testing

The PPA instruction at `0x40303c4c` loads the **literal** `0x00402100`, then
reads words at `[0x00402100]` and `[0x00402104]` into PPA globals `R9+0xd0`
and `R9+0xd4`. The first literal is present as bytes `00 21 40 00` in the
saved PPA. The second word is also read directly in the PPA's outbound
service lookup at `0x40302c4c`. That lookup loads `[0x00402104]` at
`0x40302c56`, loads the first word at the resulting pointer at
`0x40302c66`/`0x40302c6e`/`0x40302c76`, adds 9, then calls through
`BLX R1` at `0x40302c80`. Control of the handoff word **and** the pointed-to
structure could therefore control a PPA indirect call. `0x40301880` also
writes a fatal callback through the pointer obtained from that word. The
PPA uses other low addresses,
including `0x00401000` for a temporary stack and `0x00400c00`/`0x00401880`
for saved context and stacks at `0x4030349c..0x40303510`.

The ROM's unsigned speedup interpreter at `0x36e74` **numerically admits**
both `0x00402100` and `0x00402104`: its low-address test at `0x36ebc..0x36efa`
accepts the inclusive range `0x0002c000..0x3ffffffe`. In mode 0, aligned
targets reach `STR R1,[R0]` at `0x36f2c`. The ROM calls this interpreter from
`0x3451a` before visible secure selectors 0, 1, and 2. The live pass/stall
pair already demonstrated that a USB-controlled speedup table is interpreted
before the signed PPA banner appears. Thus a candidate bridge is an unsigned
write to one of these handoff words before PPA startup.

This is **not yet a demonstrated patch of the PPA's handoff**. TI's
[OMAP4460 memory map, Table 2.1](https://www.ti.com.cn/cn/lit/pdf/swpu278)
places physical `0x00402104` in Q0 boot/GPMC space, while the PPA's
`0x4030xxxx` load address is in Q1 on-chip RAM. The PPA entry at
`0x40300df8` calls `0x403031b4` -> `0x40301f38` -> `0x403038d4`.
At `0x403038d8`, it first calls `0x40303c64`, which reads `0x6f102204`
and extracts the `0xb94e` OMAP4460 chip ID. TI's
[device-identification register table](https://www.ti.com.cn/cn/lit/pdf/swpu278)
locates the corresponding physical `ID_CODE` register at `0x4a002204`.
The earlier live PPA banner printed `Detected device: 04460e11 HS`, so that
chip-ID read succeeded. Only afterward, at `0x403038e4`, does the PPA call
`0x40303c4c` to read `0x00402100/104`. This is strong evidence that the PPA
uses an address translation or secure alias before the handoff read. It does
not tell us where its `0x00402104` maps physically.

The PPA has a TTBR1 write at `0x40303472`, but this is not on the visible
direct entry path before those reads. Its image does not show the secure
monitor's earlier MMU setup or mapping. The speedup interpreter runs before
the visible SMC entry, potentially under a different mapping or security
context. In the captured public ROM, the only visible SCTLR read/write at
`0x30990/0x30998` ORs `0x1800` and does not set MMU bit 0; no visible TTBR
write was found. Physical addressing in this ROM stage is consistent with
that code if the MMU was still off, but hidden secure-side code could have
changed the state. The 48 KiB ROM capture contains no direct literal
reference to `0x00402100/104`; the unavailable monitor may also initialize
or replace the PPA's handoff word after the speedup table. Numeric equality
alone cannot establish that ROM and PPA access the same physical word.

## CHSETTINGS and CHRAM do not provide a direct write bridge

The USB CH path can read host-selected records before authentication, but
the visible `CHSETTINGS` handler `0x30c44` sends record values to fixed
PRCM/timer register helpers (`0x31d44`, `0x31f16`, `0x31d9c`, `0x31e1c`,
`0x31ca0`, `0x31ae6`, `0x32338`). The jump-table cases at
`0x31800..0x31ca0` write fixed `0x4a00xxxx`/`0x4a30xxxx` targets.
`CHRAM` at `0x32346` and its helpers `0x3228e`, `0x32236`, `0x320dc`,
`0x31f9c`, `0x31fd6`, `0x32046`, and `0x31f7c` write fixed DMM, EMIF,
PRCM, and `0x482af040/44` registers. None of these reviewed stores takes
its destination from a CH record or targets `0x00402100/104`,
`0x4030xxxx`, or the device-type register `0x4a0022c4`. DMM/EMIF
configuration could affect memory behavior indirectly; no controlled
remap of Q0 into on-chip OCMC has been found in the
[earlier MMIO follow-up](bootrom-usb-preauth-mmio-followup-2026-11-07.md).

## Read-only poll result

The [live complementary pair](bootrom-handoff-poll-2026-11-08/README.md)
used two 16,284-byte compact signed-PPA USB images with byte-identical signed
KEYS/PPA data. Both tested bit 0 of `0x00402104` through the unsigned ROM
speedup table. The mode-1 **clear** image transferred fully and reached the
PPA 1.8.5 banner; the mode-2 **set** image transferred fully and produced no
PPA banner in the 120-second post-transfer capture. The prior
[known-ROM-word pair](bootrom-speedup-poll-2026-11-07/README.md) controls for
the poll and serial-capture method. Together, these results are consistent
with a successful ROM-stage read whose bit 0 was clear across the two cold
boots. The second poll paused the panel, and a subsequent cold power cycle
restored normal boot. Neither image requested a memory or storage write.

Only that single bit was tested. It could be a default value at an unmapped
target, and the result does not prove ROM and PPA see the same physical word.
It also does not show that an unsigned write would survive the secure handoff
or safely affect PPA behavior. Those mapping and lifetime questions remain
before treating the indirect call as an exploitable bridge.
