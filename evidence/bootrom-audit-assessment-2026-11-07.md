# Touch 10 OMAP4460 HS Boot ROM: current security assessment

Date: 2026-11-07. This assessment combines the captured 48 KiB ROM,
the exact CE9.9.0 MLO, the saved eMMC image, serial/USB logs,
IDA disassembly, and offline models. The initial audit included a read-only
control-register attempt that returned `Bad address`. A later, separately
authorized GET_ID-only USB reset test is recorded below. No device storage
write was requested by either test.

## Primary finding: conditional ROM stack overwrite

The storage loader at ROM low alias `0x32a74` reads KEYS (5 sectors),
PRIMAPP (26 sectors), and only the first MLO sector (1 sector) into its
32 KiB SRAM window. The one-sector override is explicit at `0x32aee`–
`0x32af0`. It then calls secure services 0, optional 1, and 2. After that
gate, `0x32b40`–`0x32b66` restores the selected MLO's full 49-sector read.
Selected-image service 3 is called after this copy, at `0x32b7e`.
The skip flag checked before both reads starts at zero and remains zero
through the raw MMC open path; the LBA-slot selector is separate.

The range clamp at `0x34380` checks the full 32 KiB SRAM window rather
than the space remaining after the selected destination. For the concrete
512-byte-aligned destination `0x40306c00`, it leaves a `0x6200`-byte read
unchanged; the read extends to `0x4030cdff`, 3,584 bytes beyond the
window's `0x4030bfff` end. The MMC callback `0x33bba` advances the
destination by 512 bytes per sector; controller setup and the FIFO loop
confirm that length. The FIFO copy's saved return address is at
`0x4030cc54`, 20 bytes inside the 448-byte final-sector tail beyond the
signed ISW body. That word maps to MLO-relative offset `0xa054`, or
eMMC user-area offset `0x2a054`.
TI's public [OMAP4460 memory map](https://www.ti.com/lit/ug/swpu278d/swpu278d.pdf)
lists the 48 KiB mapped Boot ROM and on-chip SRAM through `0x4030dfff`,
consistent with the captured region, modeled destination, and stack
addresses. The actual stack frames come from this unit's captured ROM.

The installed MLO is at eMMC LBA 256, the second raw MMC slot the ROM
searches. The signed MLO reaches U-Boot only when its inherited source
code is 5 or 6, both of which use the implicated ROM MMC callback. This
strongly supports the modeled source path, although the source latch
itself was not captured.

The exact MLO's root-key hash, three RSA/SHA-256 certificate signatures,
and PPA/ISW body hashes verify offline. An in-memory edit of outer TOC
destination `+0x10` and the final-sector tail leaves those checks intact.
The visible pre-copy secure-service ABI passes section pointers and no
explicit TOC pointer. The secure handler is absent from this nonsecure
ROM capture and could inspect the retained TOC pointer or shared state.
The exact signed PPA's startup descriptor is constructed internally from
flags and constants and carries no observed TOC pointer. Its own service
IDs `0x21`–`0x32` use exact-match dispatch in a different namespace; they
do not numerically alias ROM selectors 0–3. Its external handoff pointers
and the secure SMC implementation remain unavailable, so these findings
still do not settle the gate's policy.

An independent call-chain review found no omitted active stack frame,
second MMC destination bound, or sector-count change that defeats the
modeled overwrite. Its memory-firewall check notes that the FIFO copy's
own `PUSH` writes to the saved-LR address before the sector write does.
This makes a destination fault at that exact word less likely, but does
not predict the full boot outcome.

**Confidence:** the clamp defect, sector copy, and modeled saved-PC overlap
are statically demonstrated. Acceptance of an edited TOC by the secure
handler and the resulting execution on this panel are unproven. This is
an exploit candidate, not a reproduced signature bypass or ROM execution.

Detailed evidence: [stage 3 trace](bootrom-static-audit-stage3-2026-11-07.md),
[secure-gate trace](bootrom-secure-gate-2026-11-07.md),
[MMC source trace](bootrom-source-path-2026-11-07.md),
[`stack_tail_model.py`](../analysis/bootrom/stack_tail_model.py),
[`verify_mlo_chain.py`](../analysis/bootrom/verify_mlo_chain.py),
[the independent stack challenge](bootrom-stack-challenge-2026-11-07.md),
[the clamp-caller audit](bootrom-clamp-callers-2026-11-07.md), and
[the SMC ABI trace](bootrom-smc-abi-2026-11-07.md), and
[the PPA service trace](bootrom-ppa-services-2026-11-07.md).

## Secondary findings

| Lead | Present assessment |
| --- | --- |
| Pre-verification configuration interpreter | A fixed 32-entry table can write or poll selected GPMC, EMIF, DMM, and PRCM ranges before image verification. [TI identifies bit 13](https://www.ti.com/jp/lit/pdf/swpu316) as `STD_FUSE_CH_SPEEDUP_DISABLE`; the saved USB ASIC ID proves it is **0 (enabled)** on this unit: ROM code places that bit in response byte 6 bit 4, which is clear in captured byte `0x07`. The exact MLO's entries are all denied by the visible filter; direct fuse, firewall, SRAM, and MMC targets are excluded. [MMIO follow-up](bootrom-usb-preauth-mmio-followup-2026-11-07.md) rules out a DMM remap from allowed low addresses into OCMC/DDR and maps GPMC to external Q0 chip selects. A [one-bit pass/stall pair](bootrom-speedup-poll-2026-11-07/README.md) tested this on the panel: the pass image reached the PPA banner, while the stall image transferred fully and produced no PPA banner for 120 seconds. A cold reset restored Linux. This strongly supports pre-verification interpretation of the unsigned table; it does not demonstrate a signature bypass. Allowed PRCM clock changes have documented conditional hang/corruption errata, but no controlled verification bypass has been shown. |
| CH TOC offsets | The USB CH parser does not bound 32-bit section offsets by the received image length. The saved ASIC ID proves its fuse gate is enabled. A CHRAM offset `0xbfd308b8` from USB base `0x40304000` wraps to ROM literal `0x348b8`, where the C2 magic and nonzero valid byte pass the visible checks when runtime context bit 6 is clear, dispatching ROM code bytes as a configuration record. The USB wrapper forces bit 8, skipping CHMMCSD, and discards handler status. This candidate was not run; it appears capable of disrupting DRAM setup, with no data export, general write, or authentication bypass shown. |
| USB receive count narrowing | `0x35520` and the DMA completion path at `0x35498` narrow progress to 16 bits. The visible pre-authentication requests are limited to 32,767 bytes (type 2) or 49,151 (type 3), below wrap even after one configured packet. This remains a latent API concern only if another caller can arm a larger request. |
| USB RESET/DMA lifetime | The bus RESET branch `0x35bb6`–`0x35bbe` changes only USB state, leaving an active receive descriptor pending; configuration-zero and cleanup do not explicitly abort DMA. The [live reset test](rom-usb-reset-2026-11-07.md) showed that a four-byte GET_ID succeeded after a host port reset in the same ROM session. [Controller review](bootrom-usb-dma-reset-followup-2026-11-07.md) establishes that these short packets took the FIFO path, so no DMA data write was tested. The reply constrains DMA_ADDR retention modulo 65,536, but not DMA enable or count. A late queued DMA write after stack reuse or an overrun beyond DMA_COUNT remains a hardware hypothesis; no host-directed pointer or buffer overrun was established. |
| USB EP0 descriptors | Setup copies a fixed eight bytes; descriptor indexes and reply lengths are bounded. No host-directed ROM read or write was found in the reviewed handlers. |
| TOC extent undercount | `0x343e0` can compute an incorrect extent, but the visible type-2 caller discards the computed span and type 3 skips the routine. No used output or security effect shown. |

See the [secondary-leads trace](bootrom-other-leads-2026-11-07.md),
[USB audit](bootrom-usb-audit-2026-11-07.md),
[USB memory-sink audit](bootrom-usb-memory-sinks-2026-11-07.md),
[CH parser audit](bootrom-ch-parser-2026-11-07.md),
[configuration-interpreter audit](bootrom-config-interpreter-2026-11-07.md),
[USB pre-authentication configuration audit](bootrom-usb-preauth-2026-11-07.md),
and [control-register read note](bootrom-control-register-read-2026-11-07.md).

The live speedup-poll result upgrades that table's *USB reachability* from
an offline hypothesis to strong experimental evidence. The one changed
byte is consumed only by the poll in the visible ROM path; a later hidden
secure-side effect cannot be strictly excluded without a PC trace. Modes
1 and 2 could form a one-bit-per-cold-boot progress oracle for a stable,
readable, allowlisted address, but neither secure ROM readout nor bulk USB
readback is demonstrated. The permitted writes still do not reach OCMC,
fuses, firewalls, MMC, or the secure monitor directly. DMM/GPMC mapping
reviews found no route to executable SRAM. Allowed PRCM clock changes have
documented fault conditions, not a controlled signature bypass. See the
[experiment and recovery record](bootrom-speedup-poll-2026-11-07/README.md).

## Decision for the firmware project

The existing, tested U-Boot `bootz` path already boots an unsigned Linux
image from RAM. It provides a practical development route for rewriting
firmware without relying on this unresolved ROM candidate. A persistent
eMMC TOC modification at LBA 256 could block every normal boot if the
candidate crashes or verification rejects it. The current workspace scope
keeps recovery work investigational, so no such modification was made.

The decisive ROM research step is to establish the secure handler's policy
for outer TOC destination `+0x10`, preferably from same-revision secure-side
code or a genuinely reversible boot medium. The
[reversible-probe assessment](bootrom-reversible-probe-options-2026-11-07.md)
found no demonstrated accessible route that exercises the exact storage gate
without changing LBA 256. A compact signed-PPA USB upload is only a proxy for
some secure-service behavior; it does not invoke the implicated MMC read.
The visible USB/UART path receives into a fixed destination and discards the
clamp's computed range; only the storage caller uses that range for a copy.
Repeated cold-boot logs show that the service USB port exposes TI ROM USB
before the installed MLO runs. TI's
[Flash v1.6 guide](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/791/Flash-v1.6-User-Guide-_2D00_-Texas-Instruments-Wiki.pdf)
also lists OMAP4 HS USB/UART second-stage loaders. That is a credible early
recovery *transport*, but no signed USB loader has been shown to restore
this panel's eMMC: the exact matching-key Cisco MLO exceeds the ROM
peripheral length limit, a compact signed-PPA trial reached a fatal path,
and the two local USB-format `.2nd` candidates have a different root-key
hash. The TI Flash guide documents NAND/SDRAM operations, not this board's
eMMC. See [the local loader inventory](omap4-hs-usb-loader-inventory-2026-11-07.md).
A failed service-2 check can enter a ROM infinite loop before later eMMC
slots are considered, so those slots are not a dependable rescue. A fresh
cold reset should present the observed early USB opportunity again, but an
eMMC-failure case has not been tested on this unit.
Until a separate first-stage recovery route is demonstrated, a live eMMC
edit would not be a controlled recovery-safe test.
