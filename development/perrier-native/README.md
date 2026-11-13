# Historical native LCD bring-up

The active kernel and consolidated DTS are now in
[development/kernel](../kernel/README.md). This record describes earlier
kexec trials. Cold/U-Boot backlight support is now verified: standard
`pwm-backlight` owns GPIO151 (pad `0x4a100154`) and the GPIO157 5 V supply.
See the [corrected stock evidence](../../evidence/perrier-backlight-pad-erratum-2026-11-10.md).

# Perrier native LCD RAM image

Linux 6.18.48 now displays a visible 1280×800 color pattern on this Touch 10.
The [clean ram36 run](../runs/20261109T085657Z-perrier-simpledrm-trial-69ffd7/result.json)
was confirmed on the panel and passed the automatic return-to-stock checks:
stock Linux 3.4 and Phoenix resumed, the bridge registers matched the stock
capture, and the U-Boot environment hash did not change. The tested image is
saved in [baselines/ram36-clean-visible-lcd](baselines/ram36-clean-visible-lcd).
This is a bounded kexec test, not a cold-boot image.

## What made the screen visible

Stock drives GPIO163, named `lcd_3_3v_enable`, high while the LCD is active.
The [ram35 diagnostic](../runs/20261109T084119Z-perrier-simpledrm-trial-808085/result.json)
showed GPIO163 configured as an output but low during the temporary kernel;
its screen was black. Timer10 PWM and GPIO157 still matched stock. Ram36
restores GPIO163 high through the standard `regulator-fixed` and `gpio-omap`
drivers, with the regulator connected to the `panel-lvds` power supply. The
[ram36 capture](../runs/20261109T084946Z-perrier-simpledrm-trial-672c92/result.json)
shows GPIO163 high, stock-matching bridge registers, and the user saw the
pattern. The cleaned rebuild was confirmed visible in the second run.
This strongly implicates the missing LCD rail in the black screen. Ram33 had
stock-matching bridge registers and was black, but its GPIO163 level was not
logged, so the comparison is not a strict one-variable test. The fixed
regulator switches the already identified rail; it does not program a PMIC
voltage.

## Driver path

| Function | Current implementation | Status |
| --- | --- | --- |
| Scanout and DSI | Mainline OMAP DRM/DSS/DSI with board-gated timing changes | Visible 1280×800 RAM pattern |
| DSI-to-LVDS bridge | Mainline `tc358775.c` TC358765 variant with Perrier-specific reset and register settings | ID `0x6500`; VPCTRL `00f02110`, LVCFG `00000001`, LVPHY0 `00004006` match stock |
| LCD panel | Mainline `panel-lvds` | Connected `LVDS-1`; panel supply is a fixed regulator |
| LCD 3.3 V enable | Mainline `gpio-omap` and `regulator-fixed` on GPIO163 | High throughout the successful pattern window |
| Backlight PWM and 5 V enable | Mainline timer10 PWM/backlight in ram51; GPIO157 remains inherited | User confirmed brightness slider; cold boot still needs 5 V sequencing |
| Front volume and mute keys | Mainline OMAP4 matrix keypad in ram52 | Three physical keys produced matching press/release events; stock key and repeat masks match |

The earlier ram36 candidate does not program GPIO151, GPIO157, timer10, PMIC voltages, or
unmapped rails. GPIO4 and GPIO6 use `ti,no-reset-on-init` so their other
outputs keep the state left by stock. The temporary kernel forces eMMC block
areas read-only; its init mounts stock volumes read-only and never feeds the
watchdog. The runner checks stock recovery and the U-Boot environment hash.

## Clean build

The active build uses nine exact patches against the original Linux 6.18.48
source archive. Old incremental patches from failed ram34/ram35 ordering
experiments are preserved under `archive/ram35-incremental-patches` and are
not applied. [kernel-patches/README.md](kernel-patches/README.md) explains
which changes are board-specific and which are RAM-test safety guards.
The [driver review](driver-review.md) records which parts use existing
drivers and which patches still need controlled reduction.

```sh
python3 development/perrier-native/verify_patchset.py
python3 development/perrier-native/build.py
python3 development/perrier-native/audit_native.py
```

`verify_patchset.py` applies every patch to a fresh extraction of the eight
affected files and checks exact hashes. `build.py` accepts only the exact
vanilla or reviewed patched contents, then builds the initramfs, kernel and
DTB. The clean rebuild was tested through RAM-only kexec. The successful
[run record](../runs/20261109T085657Z-perrier-simpledrm-trial-69ffd7/result.json)
contains the recovery proof and captured serial log.

## Qt and touch development

The [Touch 10 userspace toolchain](../toolchain/README-touch10.md) is GCC
15.3 with an ARMv7 hard-float musl sysroot. [Qt 6.12 and the calibration
app](../perrier-qt/README.md) are built from source for Cortex-A9, NEON,
and VFPv3. The staged 30.5 MB runtime passes a QEMU Cortex-A9 start and
clean-exit preflight. The [interactive RAM environment](../perrier-ramenv/README.md)
adds key-only SSH, file transfer, tracing, a debugger, and a temporary Gen4
I2C-to-uinput bridge, with hardware watchdog recovery. It does not install
Qt or change firmware on eMMC.

The ram41 and ram42 runs displayed the Qt grid and captured real touch
events. The interactive ram44 session resolved their apparent orientation
conflict: the first RAM kernel's framebuffer scanout wrapped horizontally by
about +214 pixels, while touch X/Y are direct. A temporary -214-pixel Qt
scene rotation aligned all five targets and red touch markers in the
[physical panel photo](../../evidence/perrier-qt-aligned-2026-11-09.jpg)
and coordinated taps. The interactive run also reproduced the Qt shutdown
crash in linuxfb's evdev worker thread. Disabling that worker and reading
evdev in the app's main loop gives clean timed and SIGTERM exits on one
continuous RAM boot. The Qt app rebuilds, uploads, and restarts over SSH.
The eighth kernel patch selects the stock DISPC core clock at display enable.
Clock readback matches stock, and the user confirmed that all targets and the
red touch marker align with zero Qt shift. The active Qt app and runner no
longer include scene compensation or a movable-center control. The cleaned
app was rebuilt and restarted over SSH on the same confirmed kernel boot.
Automatic stock recovery with the clock patch already passed in the previous
interactive run, with an unchanged U-Boot environment. See the
[touchscreen record](../perrier/touchscreen.md) and
[calibration evidence](../../evidence/perrier-qt-horizontal-calibration-2026-11-09.md).

A separate [native Gen4 touch RAM profile](../perrier-touch/README.md) now
replaces the temporary userspace bridge with a kernel I2C/input driver. It
uses the same display, SSH, and watchdog recovery path. The controller
descriptor and input device have been validated live. The first native image
showed a variable horizontal display wrap despite stock-matching steady-state
clocks and bridge timing registers. A Perrier-only startup sequence now
prepares DSI video, configures the bridge, then starts pixel scanout. Ram50
read the bridge ID and stock-matching configuration registers before scanout.
The user confirmed all five targets were physically aligned, and the native
kernel driver reported direct touch coordinates near each target. The ram45
wrap shows that matching the stock DISPC clock alone was insufficient to
guarantee alignment.

## Remaining display work

The [ram51 timer10 trial](../perrier-backlight/README.md) now runs the
mainline `pwm-omap-dmtimer` and `pwm-backlight` drivers at the stock 20 kHz
period and responds to brightness changes. It still relies on stock firmware
to set the PWM pad mux and GPIO157 LCD 5 V before kexec. A cold boot needs
native pinctrl and a reviewed GPIO157 power sequence. The measured pad
settings and stock callbacks are in [backlight-notes.md](backlight-notes.md).

The Toshiba bridge patch contains a regulator lookup fix, a DSI attach-order
fix, and TC358765 settings from the stock kernel. The OMAP DSI patches match
stock clock and line timing and include an inclusive PLL search-end fix.
Several of those changes were introduced before the missing GPIO163 rail was
found; they have **not** each been proven necessary for visible pixels.
Keep the working ram36 image as the control for one-change-at-a-time RAM
comparisons. Do not remove a change merely because the register readback looks
close: the display must remain visible and recover to stock.
