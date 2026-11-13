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

## Current quirk inventory

| Area | Behavior | Current disposition |
| --- | --- | --- |
| DISPC | Suppress normal ONOFF and ALIGN bits | Keep for now: removing both produced a red column after the matched display cycle |
| OMAP PLL | Force N search to start at 38 | Removed and physically qualified in ram69, with ram66 DISPC behavior retained |
| OMAP PLL | Inclusive multiplier upper bound | Generic arithmetic fix; keep separately from board quirks |
| DSS | Use DSI PLL1:1 as DISPC core source | Previously fixed the horizontal wrap; retain until isolated |
| DSI | Rounded non-burst line clocks and original panel H timings | Needed by the current clock solution; retain for a dedicated timing review |
| DSI | VP_HSYNC polarity, GP pad mode and VC0 source | Separate later reductions; do not bundle with PLL testing |
| DSI/bridge | Prepare receiver/PHY before starting video | Retain the working enable/disable sequence for the first tests |
| Bridge | Reset handoff, PHY settings, VPCTRL and LVCFG layout | Retain until chip/host/panel constraints can be separated |
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

## Qualified outcome

Ram69 is the default `display-pll-only` U-Boot development profile. Its
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

## Packaging observation

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
