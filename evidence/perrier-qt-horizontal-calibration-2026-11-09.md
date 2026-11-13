# Touch 10 horizontal calibration, 2026-11-09

The factory Touch 10 input orientation is direct X/Y. In the first interactive
Linux 6.18.48 RAM boot, the LCD displayed framebuffer content rotated right
by about 214 pixels modulo the 1280-pixel line. This is a scanout issue, not
a mirrored touchscreen:

| Framebuffer target | Physical tap before correction | Result |
| --- | --- | --- |
| `CENTER` at X=430 | raw X=646, 643, 664 | appears near physical center |
| `LL` at X=90 | raw X=303 | +213 px |
| `LR` at X=1190 | raw X=124 | `(1190+214) % 1280 = 124` |

The [before photo](perrier-qt-before-wrap-2026-11-09.jpg) shows both corner
pairs on the left. A read-only `/dev/fb0` capture showed that Qt had actually
drawn its targets at their requested framebuffer coordinates. The DISPC GFX
plane had a zero position and pan offset. The mismatch arose after memory
scanout, in the display pipeline. The
[compensated framebuffer](perrier-fb-scene-shift-2026-11-09.png) is visibly
rotated left in memory, while the corresponding physical panel photo is
correctly aligned.

A temporary Qt scene rotation of -214 pixels made all targets and touch
markers align in the [after photo](perrier-qt-aligned-2026-11-09.jpg). On the
same RAM boot ID `669f6850-ea36-4857-82d8-698feb103627`, the app logged:

| Target | Intended `(x,y)` | Touch `(x,y)` |
| --- | ---: | ---: |
| CENTER | `(640,400)` | `(635,399)` |
| UL | `(90,130)` | `(78,121)` |
| UR | `(1190,130)` | `(1155,137)` |
| LL | `(90,710)` | `(98,709)` |
| LR | `(1190,710)` | `(1172,704)` |

The user confirmed that the red marker followed their finger. This validated
direct touch coordinates and measured the display shift; the Qt correction
was a diagnostic workaround.

## Verified kernel clock correction

The saved [stock clock report](perrier-stock-dss-clk-2026-11-08.txt) uses
DSI PLL1:1 at 142,147,324 Hz for both DISPC core and LCD logic, with a
71,073,662 Hz LCD pixel clock. The first RAM kernel's
[clock report](perrier-ram-dss-clk-2026-11-09.txt) used 170,666,667 Hz PRCM
FCK for the DISPC core while keeping the same LCD and pixel clocks.

`1280 * (1 - 142147324 / 170666667) = 213.895` pixels. The agreement with
the measured 214-pixel rotation supports a DISPC/DSI timing explanation;
the exact internal phase mechanism has not been established. The active DSI
video timing and TC358765 bridge timing
registers matched stock; the readback differences are chiefly inactive
DSI VCs, status/error counters, and unrelated DISPC settings. A live write
to `DSS_CONTROL` bit 8 changed the mux register but did not move the image;
the original value was restored. Clock and line alignment may be latched at
display enable, so that result does not exclude the source selection.

The board-gated [kernel patch](../development/perrier-native/kernel-patches/08-perrier-dispc-core-clock.patch)
selects PLL1:1 for the DISPC core at LCD modeset and restores FCK at
teardown. The [confirmed RAM run](../development/runs/20261109T140725Z-interactive-172d37)
uses kernel boot ID `3bd1c2f8-cfda-443c-9162-2986e4618e50` and reports the
stock clock rates and `DSS_CONTROL=0x103`. Qt used zero scene shift,
the normal center X=640, and direct touch coordinates. The user confirmed
**"Everything aligns"** after being asked to check target positions and
whether the red marker followed their finger.

The [captured logs](perrier-clockfix-confirmed-2026-11-09.txt) include direct
touches `(653,389)`, `(92,712)`, `(102,126)`, and `(1192,700)` near the center,
lower-left, upper-left, and lower-right targets, respectively. Changing the
core source during display enable therefore fixes the physical alignment;
the touch coordinates need no mirror or offset.

The diagnostic scene rotation and movable-center controls have been removed
from the active Qt source and runner. The cleaned app was rebuilt, passed its
Cortex-A9 QEMU start/exit check, and restarted over SSH on this same kernel
boot. The [post-cleanup capture](perrier-clockfix-clean-qt-2026-11-09.txt)
records the executable hash, further direct touch events, unchanged boot ID,
and active watchdog. It uses normal Qt layout with `anchors.centerIn: parent`. The old
diagnostic sources and hashes are saved in
[the diagnostic archive](../development/perrier-qt/archive/ram44-display-shift-diagnostic/manifest.json).
The photos above document the earlier Qt workaround, not this kernel test.

The previous [clock-fix run](../development/runs/20261109T125053Z-interactive-e4a741/result.json)
already completed automatic recovery at 13:22:52 UTC: stock Linux 3.4 and
Phoenix returned, and the U-Boot environment hash was unchanged. Its
[unshifted framebuffer](perrier-fb-kernel-clockfix-2026-11-09.png) also has all
targets at their expected coordinates. The current interactive run retains
the same proven watchdog feeder and a 60-minute host lease.

Both rebuilt image audits passed after the Qt cleanup. The interactive image,
DTB, app, patches, and validation hashes are saved in
[the cleaned clock-fix baseline](../development/perrier-ramenv/baselines/ram44-clockfix-clean-qt/validation.json).
The archived combined image was rebuilt after the live kernel test; the
cleaned app was exercised on that same live kernel, without another reboot.
