# Linux 6.18.48 Perrier RAM patch set

These are exact diffs against `development/sources/linux-6.18.48.tar.xz`.
`manifest.json` records original, patched, and patch hashes. Run
`python3 development/perrier-native/verify_patchset.py` to prove they apply
without fuzz to pristine source. The active build applies them only when the
source file has the expected original hash; it refuses unknown contents.

| Patch | Purpose | Current evidence |
| --- | --- | --- |
| `01-preserve-stock-clocks` | Leave the stock OMAP USB/audio PLL configuration intact during kexec | RAM trial safety; not a display claim |
| `02-avoid-stock-pmic-reinit` | Avoid new low-power/voltage policy without a board PMIC description | RAM trial safety; not a display claim |
| `03-force-readonly-emmc` | Force MMC block areas read-only in this board's RAM image | Recovery guard; storage readback and stock recovery passed |
| `04-tc358765-perrier` | Correct bridge regulator consumer names and DSI attach ordering; use the stock TC358765 reset, LVDS PHY, VPCTRL and LVCFG sequence | Bridge IDs and key registers match stock; visible ram36 pattern |
| `05-omap-dsi-pll` | Include the last valid PLL multiplier and choose the observed N=38 for this board | Exact stock DSI DCO and byte clock |
| `06-omap-dsi-timing` | Match stock non-burst line length, H porch rounding, VC0 source, HSYNC polarity and pad state | Exact DSI VC0/line readback; FIFO empty |
| `07-omap-dispc-polarity` | Match stock DISPC polarity/align bits | Exact stock POL_FREQ readback |
| `08-perrier-dispc-core-clock` | Select DSI PLL1:1 for Perrier's DISPC core at LCD enable and restore FCK at disable | Stock-matching 142.147 MHz core; user confirmed aligned targets and touch with unshifted Qt; automatic stock recovery passed |

The board description in `omap4-perrier-ram.dts` uses existing `panel-lvds`,
`regulator-fixed`, and `gpio-omap` drivers to restore the stock-high GPIO163
LCD rail. The rail was low in ram35 and high in the visible ram36 run. Ram33
had stock-matching bridge registers but did not log GPIO163, so this is
strong evidence for the rail rather than a strict one-variable comparison.
The bridge and OMAP patches' individual necessity for visible pixels remains
unproven, although they match observed stock hardware state.

A cleaner long-term driver design would make the TC358765 register layout
and PHY sequence an explicit chip variant in `tc358775.c`, retain only real
generic fixes in the OMAP DSI/PLL code, and move board electrical policy to
DT. Test each reduction against the saved ram36 control image. Until then,
this board-gated patch set preserves the only confirmed visible output.
