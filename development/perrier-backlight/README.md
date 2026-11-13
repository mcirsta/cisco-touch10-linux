# Perrier timer10 backlight RAM trial

The historical GPIO151 pad label in this record was corrected on
2026-11-10: MCSPI4_CLK/GPIO151 is at `0x154`, stock mode 3; `0x156` is
a different pad. See the [erratum](../../evidence/perrier-backlight-pad-erratum-2026-11-10.md)
and the [Gen4 cold-boot work](../perrier-gen4/README.md) for the explicit
GPIO151 enable, GPIO157 supply and PWM pinmux implementation. The ram51
handoff artifacts and captures below remain preserved.

`ram51` extends the validated `ram50` native display and touch image with
mainline `pwm-omap-dmtimer` and `pwm-backlight`. The image is separate from
`ram50`; it uses the same key-only SSH session, host lease, WDT2 watchdog,
read-only eMMC policy, and automatic return to stock.

The stock CE9.9.0 pad snapshot identifies the actual PWM route. The
`dpm_emu18` pad is mux mode 1 (`dmtimer10_pwm_evt`); the other timer10-capable
pad, `usbb1_ulpitll_dat6`, is mux mode 4. GPIO157 is mux mode 3 and high
while the stock display is lit. GPIO151 is in safe mode 7, and its GPIO bank
direction is input. The read-only measurements are in
[perrier-stock-backlight-pads-2026-11-09.txt](../../evidence/perrier-stock-backlight-pads-2026-11-09.txt)
and [perrier-stock-backlight-mmio-2026-11-08.txt](../../evidence/perrier-stock-backlight-mmio-2026-11-08.txt).

The RAM trial's DTS adds timer10, a PWM provider, a PWM backlight, and the
panel backlight link. It does not set any pinctrl state, GPIO157, GPIO151,
or PMIC voltage. The PWM pad and 5 V enable remain inherited from stock;
this stage does not establish cold-boot power sequencing.

The audited image [ram51 manifest](../perrier-ramenv/native-backlight/reviewed-image.json)
booted over kexec and registered `/sys/class/pwm/pwmchip0` and
`/sys/class/backlight/backlight`. At full brightness, timer10 retained the
stock `TCLR=0x1843` and `TLDR=0xfffff880`, giving a 20 kHz period from
38.4 MHz. The mainline driver set `TMAR=0xfffffffe` at full brightness.
A brief brightness change from 4 to 2 moved `TMAR` to `0xfffffc43`, then
restoring 4 returned it to `0xfffffffe`; the timer kept running. GPIO157
stayed high, GPIO151 stayed input, and all four sampled pad mux values
matched stock. The DRM connector reported `connected` at 1280×800, Qt
opened fb0 and the native Cypress event device, and the WDT2 lease kept
renewing. See the [live capture](../../evidence/perrier-ram51-backlight-live-2026-11-09.txt).
The user observed the aligned grid on the physical panel, then confirmed
that the Qt slider changed brightness and tracked touch in a second RAM
session. The [clean Qt screenshot](../../evidence/perrier-ram51-slider-clean-fb-2026-11-09.png)
is saved locally. The slider stops at 25% rather than switching the light off.
The [slider log](../../evidence/perrier-ram51-slider-live-2026-11-09.txt)
records all four levels. Both RAM sessions returned to stock with the U-Boot
environment hash unchanged:
[first recovery](../../development/runs/20261109T181423Z-interactive-8dd93f/result.json),
[second recovery](../../development/runs/20261109T182403Z-interactive-df784e/result.json).

Build and audit:

```sh
python3 development/perrier-ramenv/build_image.py --profile native-backlight
python3 development/perrier-backlight/audit_image.py
python3 tools/touch10_ram.py session --profile native-backlight --minutes 8
```

For Qt-only changes during a running RAM session, rebuild and stage the Qt
app, then run `python3 tools/touch10_ram.py qt-restart`. This replaces the
app in RAM over SSH without rebuilding or rebooting the kernel.

The next cold-start step is to model the GPIO157 5 V enable and the
`dpm_emu18` pinctrl state, after checking their power ordering against the
stock callbacks. A kexec handoff starts with those circuits active and cannot
by itself prove a cold boot. The stock kernel, U-Boot environment, and eMMC
boot contents remain unchanged by this trial.
