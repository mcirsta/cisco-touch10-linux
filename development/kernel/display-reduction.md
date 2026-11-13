# Reducing Perrier display quirks

This work starts from the physically confirmed ram66 mainline-bus image.
Its zImage, DTB, initramfs and source snapshot remain untouched. Every live
candidate uses the existing one-shot U-Boot RAM route, key SSH and unchanged
mainline-watchdog feeder. DT pinmux, GPIOs, supplies and panel timing must
remain byte-identical to ram66 during the first reductions.

## Sequence

1. Restore the entire mainline `dispc.c` by removing the Perrier POL_FREQ
   ONOFF/ALIGN override. Compare the resulting register value, active DRM
   state and visible aligned Qt output; verify recovery.
2. Remove the OMAP PLL N>=38 board restriction. The normal search can
   select N=19/M=211 instead of N=38/M=422, with identical integer-derived
   DCO and output clocks. Verify the actual programmed divider, output
   clocks, visible display, touch/brightness and watchdog return.
3. Review the bridge and DSI sequencing independently. Keep measured
   TC358765 reset/PHY behavior while distinguishing reusable chip-format
   fixes from panel-dependent timing. Reduce the remaining DSI timing,
   source, sync and DISPC clock assumptions one controlled change at a time.

These phases are behavioral tests. Replacing a board-name check with a
chip-type check alone would not establish that other panels need the same
sequence or constants.

## Qualified checkpoint inventory

The inventory reflects qualified behavior through ram93. The active
canonical source may contain a later, unqualified control experiment.

| Area | Behavior | Current disposition |
| --- | --- | --- |
| DISPC | Suppress ALIGN | Removed: upstream ALIGN qualified independently in ram89 and with upstream DSS in ram91; dispc.c has no source override |
| DISPC | Suppress ONOFF | Removed: mainline ONOFF=1 qualified in ram70 over two boots and four cycles |
| OMAP PLL | Force N search to start at 38 | Removed and physically qualified in ram69, with ram66 DISPC behavior retained |
| OMAP PLL | Inclusive multiplier upper bound | Generic arithmetic fix; keep separately from board quirks |
| DSS | Use DSI PLL1:1 as DISPC core source | Removed: upstream PRCM core source qualified independently in ram90 and combined in ram91; dss.c has no source override |
| DSI | Rounded-Hz non-burst line comparison | Replaced by generic common-DCO arithmetic in ram75; mainline HBP and DISPC porch allocation qualified in ram86/ram87 |
| DSI | VP_HSYNC polarity override | Removed: mainline active-high setting qualified in ram72 and ram74 |
| DSI | GP pad mode | Removed: ordinary BYPASS mode qualified in ram88; physical pinmux and GPIO wiring unchanged |
| DSI | Re-enable stopped video VC | Removed in ram93; six clean restarts and watchdog recovery qualified the quiesced shutdown |
| DSI | VC0 L4 source for priming | Removed in ram76/ram85; ordinary video-channel setup restored, and packet completion tracks the actual command channel |
| DSI/bridge | Custom early-video state | Removed; ram85 uses generic PHY power phases and ordinary video enable/disable |
| DSI/bridge | Start continuous HS clock before bridge I2C | Retain a bridge-requested HS NULL after reset release; qualified in ram85 with physical reset every cycle |
| Bridge | Retain firmware's reset handoff | Removed in ram85; normal GPIO reset and 200 ms release wait verified over three cycles |
| Bridge | PHY settings, VPCTRL and LVCFG layout | Retain documented TC358765 fields and measured panel/PHY profile; avoid applying these constants to unrelated boards |
| Bridge | Unchecked I2C reads/writes | Replaced by uncached regmap, explicit endianness and latched error handling; failure injection tests cover this path |
| Bridge | Regulator consumer names and deferred DSI host attach | Generic integration fixes rather than board electrical policy |
| Panel/backlight | Fixed supplies, standard panel/PWM/GPIO drivers | Keep the verified DT wiring unchanged |

## PLL calculation

With the actual OMAP4 driver limits and 38.4 MHz input:

| Value | Forced search | Normal search |
| --- | --- | --- |
| N / M | 38 / 422 | 19 / 211 |
| Internal reference | 1,010,526 Hz | 2,021,052 Hz |
| Integer DCO | 852,883,944 Hz | 852,883,944 Hz |
| DISPC divider / LCK divider / PCK divider | 6 / 1 / 2 | 6 / 1 / 2 |
| Pixel clock | 71,073,662 Hz | 71,073,662 Hz |
| DSI byte clock | 53,305,246 Hz | 53,305,246 Hz |

This is an offline candidate calculation, not a claim that every callback
or physical PLL characteristic is interchangeable. The internal reference
changes within the existing driver's OMAP4 limits. Live readback and visible
output decide whether the restriction can be removed.

## Source review

The current official upstream driver snapshot is pinned in
`references/upstream-display-2026-11-10/manifest.json`. Comparisons use the
pristine 6.18.48 archive, not the old mutable bring-up source tree. The PLL
search implementation is unchanged in that upstream snapshot. The generic
multiplier end-bound correction remains relevant to the narrow non-burst
clock interval.

[Toshiba's TC358764/765 datasheet](https://toshiba.semicon-storage.com/info/TC358765XBG_datasheet_en_20180404.pdf?did=36679&prodName=TC358765XBG)
describes the electrical limits and deriving LVDS clocks from DSICLK, but
provides no complete register programming model. It does not justify
applying Perrier's PHY, divider or VPCTRL constants to all TC358765 boards.

## Physical comparison and the red column

| Image | DISPC POL_FREQ1 | N / M | Physical result after blank/unblank and Qt restart |
| --- | --- | --- | --- |
| ram66, unchanged control | `0x00000000` | 38 / 422 | Owner confirmed clean before the cycle and “all fine” afterward |
| ram67, pristine mainline DISPC | `0x00060000` | 38 / 422 | Initially visible and aligned; matched-cycle recheck showed the red vertical line |
| ram68, mainline DISPC and normal PLL search | `0x00060000` | 19 / 211 | Red vertical line near the right edge; absent from captured framebuffer |
| ram69, PLL-only control | `0x00000000` | 19 / 211 | Owner confirmed “everything is fine” after the same cycle; touch and brightness exercised |

The ram67 record is therefore unqualified for display cycling. Neither
ram67 nor ram68 was promoted to the default. Stock recovery removed the
line. The raw ram68 framebuffer contains no corresponding red column,
pointing to the output path rather than a Qt-drawn marker. An independent
ram68 rebuild, with matching build identity, reproduced the original
zImage byte for byte. These findings implicate the combined DISPC change,
but do not yet isolate either bit or prove the precise bridge failure.

The unchanged control is
`development/runs/20261110T124941Z-uboot-ram66-a3d68d`; the matched ram67
recheck is `development/runs/20261110T123838Z-uboot-ram67-c9f1d0`.
The isolated ram69 run is
`development/runs/20261110T130421Z-uboot-ram69-c110ef`. Its live Qt log
contains 165 direct touch reports and backlight levels 1–4. Its pixel,
byte and DCO clocks match ram66, with N=19/M=211 read back both before and
after the display cycle. The stock-derived N>=38 search floor can therefore
be removed while retaining the working DISPC policy.
The observation record and artifact digests are in
`out/display-reduction/red-line-observation.json`.

[TI's OMAP4460 reference manual](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf),
table 10-167, defines ALIGN as HSYNC/VSYNC assertion alignment. ONOFF=0
drives sync opposite to the pixel-data edge; ONOFF=1 selects RF. At the
current IPC=0 and RF=0 both ONOFF settings select the falling sync edge.
This makes ALIGN the stronger individual candidate, an inference requiring
a separate controlled test. The manual does not state that this combined
override is universally required for DSI. In particular, its RFBI
initialization rule to clear POL_FREQ must not be applied to DSI by analogy.
The downloaded manual's digest and source URL are retained in
`references/omap4460-swpu235ab.json`.

## Ram69 checkpoint

Ram69 qualified the `display-pll-only` U-Boot development profile. Its
hardware-expiry test returned Linux 3.4.113+ and Phoenix in 152.7 seconds,
with p8 SHA-256
`f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
Ram66 is preserved as `mainline-bus`. The canonical source, six-patch
series, build configuration, tests and reports are frozen in
`baselines/ram69`; the full record is `validation-ram69.json`.

The generic inclusive PLL multiplier-bound fix is now its own patch.
The display-specific patch retains DISPC ONOFF/ALIGN, DSI timing and bridge
sequencing. A later reduction should isolate ALIGN from ONOFF before
changing the bridge reset sequence. One matched cycle and one watchdog
recovery qualify this development step; repeated cycling, full rail power
management and physical power-removal qualification remain separate work.

## Separate ONOFF and ALIGN results

This phase starts from frozen ram69, retained as the fallback. It tests
each DISPC change independently, with every other kernel source file and
all DT properties identical to ram69:

| Image | ONOFF | ALIGN | Expected POL_FREQ1 | Status |
| --- | --- | --- | --- | --- |
| ram69 fallback | 0 | 0 | `0x00000000` | Previously qualified |
| ram70 `display-onoff` | 1 | 0 | `0x00020000` | Clean on two boots and four manual display/Qt cycles |
| ram71 `display-align` | 0 | 1 | `0x00040000` | Red line in initial Qt screen, before the additional manual cycle |

Both use N=19/M=211, the same bridge preparation, GPIOs, regulators,
pinmux, panel timing and nowayout watchdog. Each trial reads the initial
DRM/bridge/clock state and obtains a physical line/alignment observation.
Ram70 passed the two-second blank, three-second unblank and Qt restart
sequence once, then three times on a second boot. Ram71's early visible
failure was captured before the planned extra cycle. Both candidates
passed hardware-watchdog expiry back to the exact factory environment:
152.8 seconds for ram70 and 150.6 seconds for ram71.
The plan and source comparisons live under `out/display-sync-isolation`.
The earlier ram69 validation and its referenced observation files are
retained without modification.

The ram71 readback confirmed ALIGN=1 and ONOFF=0; the owner reported
“red line now.” Its saved framebuffer has no red edge column and shows
zero touch reports. The repeat of the exact ram70 image was confirmed
“all fine, no red line.” All 31 sampled bridge registers match between
the two images. Of 354 DISPC/DSI registers, the intentional POL_FREQ change
and capture-dependent IRQ/scan-line state account for the differences;
PLL, video timing, pixel format and FIFO configuration match. Source
comparisons and full register comparisons are saved under
`out/display-sync-isolation`.

Ram70 qualified the `display-onoff` profile, with normal ONOFF=1
and the narrowly retained ALIGN=0 exception. Its canonical source and
image remain exactly those used in the first clean test. Ram69 remains
its fallback. See `validation-ram70.json` and the rejected
`validation-ram71.json`. The precise interaction of ALIGN with the current
DSI sequence remains a follow-up; the experiment establishes the needed
setting for this tested pipeline.

## Brightness observation

During ram70 the owner noted that maximum brightness might be lower than
stock, possibly predating the ONOFF change. This remains unconfirmed.
The recorded request is level 4/4, 50,000 ns period and duty; timer10
readback is running at 20 kHz with near-full duty. Its configuration matches
the earlier RAM driver behavior. The PWM driver's missing hardware-state
callback makes the debugfs “actual configuration” line unsuitable as a
measurement. A later comparison should use equal full-white content and a
fresh stock readback. No backlight or supply settings were changed in
these sync trials. The persistent observation is
[`perrier-brightness-observation-2026-11-10.json`](../../evidence/perrier-brightness-observation-2026-11-10.json).

## DSI and bridge startup reduction

The next phase uses frozen ram70 as its fallback. All board DT properties,
clock rates, bridge analog/PHY settings, resets, supplies and watchdog
policy remain fixed. Two independent proposals are derived from ram70:

| Image | Change | State |
| --- | --- | --- |
| ram72 `dsi-hsync` | Restore mainline VP_HSYNC_POL=1, matching active-high DISPC HSYNC | Physically clean after one cycle; watchdog recovery 154.8 s |
| ram73 `dsi-late-video` | Keep PHY pre-enable, restore pristine mainline video enable/disable and remove early-video state | Rejected: bridge ID NACK, reset/default registers, backlight on with no image |
| ram74 `dsi-standard-video` | Prime HS clock before bridge programming, then use ordinary video callbacks; mainline HSYNC retained | Clean initial output and three display/Qt cycles; touch and brightness exercised; watchdog recovery 155.8 s |

The OMAP4460 manual's DSI_CTRL table defines VP_HSYNC_POL=1 as active
high. The current DISPC mode generates active-high HSYNC; the stock-derived
DSI override instead selected active low. Ram72 changes only that bit.

The startup proposal uses the bridge's existing
`pre_enable_prev_first` requirement to prepare its host before bridge setup.
The PHY-only version removed 61 DSI lines and restored ordinary mainline
video callbacks, but failed in ram73. The early I2C read at register 0x580
returned -121 at startup and after a display cycle, so bridge programming
was skipped. Its later readback showed reset/default timing, lane and
LVDS-enable registers. Watchdog recovery returned stock in 155.8 s with
the exact p8 hash. See `validation-ram73.json`.

[OMAP4460 erratum i422](https://www.ti.com/lit/er/swpz017l/swpz017l.pdf)
states that continuous DDR clock is established by the first HS packet.
The normal setup sends its initial NULL packet on LP VC_CMD. Ram74 sends
a NULL packet on HS VC_VIDEO while it is still in command mode and waits
using the existing bounded synchronization helper before bridge setup.
Its initial serial log records `vc=20808f81` (command mode), followed by a
successful bridge ID read. After ordinary video startup, bridge timing,
LVDS-enable and PHY settings retain their programmed values. This uses
VC_VIDEO's retained L4 source during command-mode priming; keep that source
setting until its dependency is reviewed separately.

The revised startup code removes 47 DSI lines and the custom header field.
The video callbacks remain verbatim mainline, and `dsi.h` no longer needs
a canonical override. A latched bridge status of `DSI_INTSTATUS=0x2`,
`DSIERRCNT=0xc0800001` was seen after priming and stayed unchanged through
the idle interval and all three display cycles. Its bit-level interpretation
is not established by these snapshots. Source proposals and exact
comparisons are under `out/dsi-bridge-reduction`.

The owner confirmed ram74's initial screen as “all fine” and the final
screen after three blank/unblank plus Qt restart cycles as “all good.”
The final live log contains 138 direct native touch reports and backlight
levels 1–4. Hardware-watchdog expiry returned to Linux 3.4.113+ and Phoenix
in 155.8 seconds, with the exact factory p8 hash and all four serial handoff
markers verified. Ram74 is now the default `dsi-standard-video` profile;
ram70 remains the immutable `display-onoff` fallback. The frozen ram74
source snapshot has 17 canonical overrides and the same DTB as ram70.
See `validation-ram74.json` for artifact digests and the saved screenshot.

The retained ALIGN exception was isolated with the older HSYNC=0 startup
flow. That result does not establish whether ALIGN is necessary with
ram74's mainline HSYNC and revised sequence; any coupled retest should
remain a separate candidate. Full-image physical power-removal and
production rail power management are also still pending.

The timing review in `out/dsi-bridge-reduction/timing-math-review.json`
also identifies a generic-math candidate. With a common DCO, pixel divisor
12 and byte divisor 16, the measured line totals satisfy exactly
`1440 * 12 = 1080 * 16 = 17280` DCO cycles. The rounded integer-Hz rates
instead produce a 720-unit cross-product difference, which the pristine
driver rejects. Its nominal-clock truncation also selects 1079 rather than
1080 byte clocks. A generic exact-divisor comparison and feasible-line
selection merit review; HBP rounding and DISPC event timing should remain
separate behavioral tests. No timing arithmetic was changed in this phase.

The ram73 controller initially marked capture evidence incomplete because
Ethernet printk messages interrupted the userspace guard marker. The raw
record is preserved with a separate reconstruction review. The host checker
now also recognizes user markers reconstructed after timestamped printk
records are removed. Four host-only regression tests cover the real
interruption, ordinary output, a missing guard and a wrong kernel. Stock
identity, authenticated RAM guard checks and p8 verification remain required.

## Remaining-display work from ram74

Ram75 (`dsi-exact-lines`) replaced the board-dependent line rounding and
rounded-Hz tolerance with a common-DCO divider calculation. The initial
386-register comparison differed only in the current scan-line counter.
The owner confirmed clean output, native touch and all brightness stops
after three display/Qt cycles; watchdog return took 150.5 seconds. Its
source and validation are frozen under `baselines/ram75` and
`validation-ram75.json`. Ram85 is now the qualified default checkpoint;
ram70 remains the preserved fallback.

Ram76 moved clock priming onto the command channel and restored ordinary
video-channel setup. It also fixed packet-completion callbacks that read
`update_vc` instead of the waited channel; 24 host regression cases cover
the mismatch. The image was physically clean initially and after three
cycles, but the bridge counter changed from `c0800001` to `c0800004` over
those cycles. It was not promoted. Watchdog return took 154.9 seconds.
Occupied VP FIFO state alone is not a failure criterion: the owner saw
clean output with it. Host IRQ status `0x80` is the PLL-lock event.

Ram77 replaced the bridge's unchecked native-endian I2C helpers with
uncached regmap and explicit register/value byte order. Six injected I/O
failure positions verify that failed reads preserve caller data and stop
later accesses. All 31 sampled bridge registers matched ram76; the owner
confirmed the three-cycle screen remained clean. The restart-counter
behavior was unchanged, and watchdog return took 150.7 seconds.

Ram78 tested ordinary asserted reset at probe/post-disable, plus the
historical TI driver's 200 ms reset-release wait. It failed: the host had
already started HS clock while reset was asserted, and I2C ID reads NACKed
after release. The panel returned to stock in 36.1 seconds by requested
reboot, with the watchdog fallback active. Ram79–81 were offline follow-on
drafts based on that ordering; they were never uploaded and are superseded.

The corrected ram85 implementation follows the documented DRM power phases:
prepare the host PHY, release peripheral reset, wait, request an HS NULL
packet through the normal host transfer path, then program the bridge.
On shutdown it stops video, asserts peripheral reset and powers down the
host PHY in `post_disable`. A NULL packet without `REQ_ACK` now waits for
transmit completion without requesting a peripheral BTA response. Seven
NULL-transfer cases and two complete host/bridge callback cycles pass
ASan/UBSan tests. The owner confirmed clean, aligned output with touch and
brightness initially and after three display/Qt restarts. GPIO102 read
asserted during every blank and released during every active scanout.
Bridge status stayed `00000002` / `c0800001` throughout; the bit-level
meaning of this latched startup status is not established. Hardware
watchdog recovery returned to stock in 155 seconds and verified the exact
factory environment. Ram85 is the new default checkpoint; its frozen
source and [validation](validation-ram85.json) preserve the result. Exact plans,
proposals, rejected/unrun records and logs are under
`out/display-finalization`; the active continuation is
`out/display-finalization/continuation.json`.

Ram86 (`display-hbp`) restored the ordinary DSI back-porch allocation:
59 byte-clocks of HBP and 58 of HFP, with the same 1,080-byte-clock line.
The owner confirmed clean alignment, touch and brightness after three
display/Qt restarts. Bridge status stayed unchanged, and watchdog recovery
took 154.9 seconds with exact stock p8. See
[validation-ram86.json](validation-ram86.json). Ram85 remains the default
checkpoint while further reductions are tested.

Ram87 (`display-porches`) qualified ordinary DISPC event-mode porches
1/78/81 instead of the original 3/79/78; the external bridge/panel timing
and 1,440-pixel line total stay unchanged. The owner confirmed clean output,
touch and brightness after three display/Qt restarts. Watchdog return took
152.6 seconds with exact stock p8; see
[validation-ram87.json](validation-ram87.json).

Ram88 (`display-pads`) restored ordinary BYPASS mode, with the actual
`DISPC_CONTROL` GPOUT bits reading `11` as documented in OMAP4460 TRM
Table 10-632. The owner confirmed clean alignment, touch and brightness
after three cycles; watchdog recovery took 153.5 seconds. See
[validation-ram88.json](validation-ram88.json). The physical DT wiring,
voltage, GPIO, PWM and analog PHY settings remain unchanged.

Ram89 (`display-sync-align`) qualified pristine DISPC with ALIGN=1 and
the previously qualified PLL core source. The owner confirmed clean,
aligned output, touch and brightness after three cycles; watchdog return
took 153.8 seconds. See [validation-ram89.json](validation-ram89.json).

Ram90 (`display-core-fck`) independently qualified pristine DSS/PRCM core
source with ALIGN=0, starting from ram88. Actual `DSS_CONTROL` read `00000003`,
and the saved PRCM source was 170,666,667 Hz. The owner confirmed clean
alignment, touch and brightness after three cycles; watchdog return took
153 seconds. See [validation-ram90.json](validation-ram90.json).

Ram91 (`display-mainline-sync`) combined both upstream settings. Both
compiled drivers match pristine Linux 6.18.48. The owner confirmed clean,
aligned output with touch and brightness after three cycles; watchdog
return took 152.7 seconds and verified exact stock p8. See
[validation-ram91.json](validation-ram91.json). With the corrected startup
and line arithmetic, neither older DISPC/DSS exception is required.

Phase-marked ram87 logs locate the existing host `HS_TX_TIMEOUT` inside
some blanking calls. These calls take about 191 ms versus 80 ms on the
first cycle. TI documents that the timer forces EOT and clears the TX
FIFO. This supports investigating stop/drain ordering, but does not yet
prove the causal instruction. The issue also appears in ram85/ram86;
stable bridge counters do not mean the host reported no errors. Keep
timeout reporting active and resolve or delimit this issue before final
display qualification. Details are in
`out/display-finalization/host-shutdown-review.json`.

The final evening test, ram92 (`display-stop-trace`), added timing only and
preserved the hardware/locking call sequence. It localized the long wait
to `dsi_uninit_dsi()` calling `dsi_if_enable(dsi, 0)` during later PHY
teardown. The initial video-interface stop took 7.935/18.127/18.982 ms;
the later interface stop took 110.443/80.292/110.443 ms, with the timeout
reported during that phase in all three cycles. Samples are quantized
near 30.5 microseconds; zero-duration entries are below timer resolution.
Bridge status stayed stable, independently of the host timeout.

The next hypothesis is that re-enabling the video VC in command mode
leaves pending VP work while the DISPC producer stops. An offline draft
keeps that video VC disabled while preserving the dedicated command
channel. It is unbuilt and untested. Evidence and the draft are under
`out/display-finalization/ram92-finding.json` and
`out/display-finalization/proposals/dsi-stop-video-vc-draft.patch`.
The user stopped after ram92 and resumed on 2026-11-11. The temporary
instrumentation was removed before the next functional candidate.

## Video-channel shutdown fix (ram93)

Ram93 (`display-stop-fix`) starts from qualified ram91 and removes one
operation: re-enabling the stopped VP-backed video VC after switching it
back to command mode. The shared interface stays available for the
dedicated command VC. The public host-transfer path selects `VC_CMD`, and
the next video-start path explicitly enables `VC_VIDEO` again.

The candidate preserves all other source files and physical DT settings.
Timeout registers, IRQ handling, GPIOs, supplies, PWM, PLL/pixel/byte clocks
and bridge analog settings retain their previous values. All temporary
ram92 timing code is gone. The patch series now separates reusable OMAP
host changes from Toshiba bridge support, board DTS and RAM-only safety;
seven nonempty patches apply cleanly to pristine Linux 6.18.48.

| Result | Qualified ram91 control | Ram93 |
| --- | --- | --- |
| Display/Qt restart cycles | 3 | 6 |
| Host HS transmit timeouts | 2 | 0 |
| Complete blanking call | 192.077–207.763 ms | 72.418–83.984 ms |
| Image, touch and brightness | Owner confirmed | Owner confirmed |

Every ram93 cycle restored the expected video VC, bridge registers,
reset GPIO state and upstream DISPC/DSS configuration. The owner confirmed
clean, aligned output, red-marker tracking and brightness after all six.
The controlled result supports pending VP work as the cause of the old
late interface-disable wait; exact FIFO contents were not captured.
Hardware watchdog recovery returned to stock in 152.6 seconds with all
handoff markers, a new stock boot ID, Phoenix and exact factory p8 verified.
Ram93 is now the default `display-stop-fix` test profile; ram70 remains the
preserved fallback and ram91/ram85 remain available. See
[validation-ram93.json](validation-ram93.json).
Raw evidence is under `development/runs/20261111T200641Z-uboot-ram93-d31fbf/`,
with the comparison in `out/display-finalization/ram93-comparison.json`.

## Packaging observation (ram67)

The first ram67 package was rejected before upload: one bit differed inside
packed `libQt6Core.so.6`, while the source file matched its saved digest.
Three reads reproduced the rejected archive hash. The cause is unestablished.
The builder now collects entries without repeatedly copying the whole
archive, writes through a temporary file, checks its full streaming digest,
and verifies every packed file before replacing the archive. It retains the
existing embedded-initramfs check after compilation. This is an integrity
check and packaging change, not a proven diagnosis of the earlier mismatch.
The rejected archive and observation record are under
`out/display-reduction/`.
