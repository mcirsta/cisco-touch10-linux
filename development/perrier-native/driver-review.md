# Display driver review after visible ram36

The two visible ram36 runs establish a safe RAM-only control image. They do
not establish that every board-gated kernel patch is needed. The earlier
black-screen trials did not log GPIO163, so patch removal should start only
from this saved image and change one behavior at a time.

## What is established

- Mainline OMAP DRM/DSS/DSI, `tc358775.c` with its TC358765 compatible,
  `panel-lvds`, `gpio-omap`, and `regulator-fixed` drive a visible 1280×800
  pattern. No custom panel driver or raw LCD register writes in userspace
  are needed.
- Stock GPIO163 is an output high while the UI is lit. Ram35 logged it low.
  Ram36's fixed regulator drives it high, and the pattern became visible.
  Timer10 PWM and GPIO157 matched stock in both runs. This is strong causal
  evidence, although ram33's GPIO163 level was not captured.
- The clean ram36 bridge readback is VPCTRL `00f02110`, LVCFG `00000001`,
  LVPHY0 `00004006`, ID `00006500`; the same values were captured after the
  working image before the failed ordering experiments. The framebuffer
  modeset succeeded and stock recovery passed.

## Patch disposition

| Change | Why it exists | Disposition |
| --- | --- | --- |
| Board DT: GPIO163 fixed regulator connected to `panel-lvds` | Restores the rail to its observed stock-high level after kexec | Keep; this is the strongest demonstrated fix |
| `tc358775.c`: `vddio`/`vdd` consumer names | The regulator API appends `-supply`; the old names request different properties | Keep; candidate generic driver fix |
| `tc358775.c`: attach DSI host when the bridge attaches | Breaks the I2C bridge / DSI host probe-order cycle on this graph | Keep; candidate generic lifecycle fix |
| `tc358775.c`: TC358765 reset, PHY, VPCTRL, LVCFG sequence | Mainline defaults diverged from stock, including PHY and clock-divider fields | Keep until chip-variant handling is designed and independently tested |
| `pll.c`: inclusive final multiplier | Search could miss a single legal N/M pair | Keep; candidate generic arithmetic fix |
| `pll.c`: N=38 lower bound | Selects the measured stock PLL point | Keep as a board gate; necessity for pixels not isolated |
| `dsi.c`: non-burst line timing, VC0 source, polarities and pad mode | Matches the stock DSI line and empty transmit FIFO | Keep as board gates until controlled tests isolate each effect |
| `dispc.c`: POL_FREQ bits | Matches stock DISPC polarity/align readback | Keep until a controlled test shows whether it can use generic flags or be removed |
| Clock/PM/MMC changes | Preserve stock setup and storage safety across kexec | Keep for RAM tests; they are not display features |

## Follow the existing drivers further

For cold boot, describe timer10 using `ti,omap-dmtimer-pwm` and use
`pwm-omap-dmtimer`. Feed it to `pwm-backlight`, with an explicit supply and
safe enable/off delays, then link that backlight to `panel-lvds`. Model the
GPIO157 5 V enable as a regulator only after its electrical polarity and
power order are confirmed. Bring up `pinctrl-single` only with reviewed pad
values for DSI, timer10 PWM, and GPIO151/157/163; the current RAM image
inherits those mux settings from stock. The saved stock backlight callbacks
and register snapshots are summarized in [backlight-notes.md](backlight-notes.md).

The Toshiba bridge driver should eventually express TC358765 differences as
chip-variant data or operations, rather than checking the board compatible in
each register write. The two regulator lookup fixes and PLL search-end fix
can be separated from board behavior for upstream review. The DSI timing and
polarity changes need measured A/B validation before generalizing them to
other OMAP4 boards.

Each reduction must preserve the working ram36 image, use the bounded RAM
runner, compare GPIO163 and bridge state, confirm a visible pattern, and
verify stock recovery. No persistent boot or eMMC change is part of this
review.
