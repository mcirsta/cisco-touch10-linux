# Stock backlight path for later native enablement

2026-11-10 correction: the historical pad inspector used `0x156` for
GPIO151; the correct MCSPI4_CLK/GPIO151 pad is `0x154`, stock mux mode 3.
The GPIO151 safe-mode interpretation below is superseded by the
[fresh readback and erratum](../../evidence/perrier-backlight-pad-erratum-2026-11-10.md).
The Gen4 cold-boot DT now gives `pwm-backlight` explicit GPIO151 enable
control as well as the GPIO157 5 V supply and actual timer10 PWM pad.

Offline analysis of the saved CE9.9.0 kernel at
`development/stock-kernel/ce990-Image.bin` and the captured kallsyms locates
`omap_pwm_led_apply` at `0xc0322268`. The Perrier LED platform data begins at
`0xc07add70` and points to the string `lcd_backlight` at `0xc060bf46`.
Its timer number is 10, the frequency field at offset `+28` is `0x4e20`
(20,000 Hz), its output scaling byte at `+32` is `0xfe`, and its polarity
field at `+36` is zero. The apply routine uses `clk_get_rate()` divided by
that frequency to set the timer load and match registers. Its output setup
calls `omap_dm_timer_set_pwm()`, then starts timer 10.

The platform callbacks are `idefix_backlight_set_power` at `0xc0032330`
and `idefix_backlight_set_pad` at `0xc00322ec`. Kallsyms identifies their
GPIO helper as `__gpio_set_value`. The power callback drives GPIO157 to its
argument and delays when turning it on. The pad callback drives GPIO151 to
its argument; on the off path it delays after dropping the pin. The stock
GPIO snapshot shows GPIO157 (`lcd_5v_enable`) high while the UI is lit, and
the stock LED reports brightness 255/255. A read-only register snapshot
shows GPIO151's output latch high but its direction set to input; timer10
is running. A subsequent stock padconf read found GPIO151 in safe mode 7
while the UI was lit, with its GPIO direction set to input. GPIO157 was in
GPIO mode 3. Timer10's actual PWM output is the `dpm_emu18` pad in mode 1;
the other timer10-capable `usbb1_ulpitll_dat6` pad was in mode 4. The raw
register values are saved in [the stock pad capture](../../evidence/perrier-stock-backlight-pads-2026-11-09.txt).

This is useful for a safe mainline port: timer 10 maps to the existing
`pwm-omap-dmtimer` driver, and `pwm-backlight` can use a board GPIO. Neither
has been enabled in the RAM image. The generic PWM driver's probe stops an
already active timer before it reconfigures it, and generic `pwm-backlight`
updates PWM before its supply and enable GPIO. That order differs from the
stock callbacks, which power GPIO157 before programming PWM and raise
GPIO151 afterward. A cold-boot driver must account for this sequence. The
separate `ram51` trial uses the existing PWM and backlight drivers with
GPIO157 and the pad mux inherited from stock. It does not exercise the 5 V
power-on sequence.

Ram35 inherited timer10 PWM and GPIO157 high but had GPIO163, the LCD 3.3 V
enable, low; the screen was black. Ram36 uses a fixed regulator to restore
the stock-high GPIO163 level, and the pattern became visible. The later
ram51 handoff now controls timer10 natively while GPIO157 remains inherited.
This confirms the RAM handoff path, not the cold-boot power sequence.

Linux 6.18.48 already has the `ti,omap-dmtimer-pwm` binding and
`pwm-omap-dmtimer` driver for timer10, plus the generic `pwm-backlight`
driver. The latter supports a `power-supply`, `enable-gpios`,
`post-pwm-on-delay-ms`, and `pwm-off-delay-ms`; `panel-lvds` accepts a
backlight phandle. Those are the preferred building blocks for cold boot.
The stock callback order and GPIO157 5 V behavior need a board-specific
review before native power control is enabled. A normal kexec test starts
with the power circuit already on, so it cannot alone validate the
cold-boot transition. The `ram51` handoff did validate native timer10
control: the mainline drivers produced stock-matching 20 kHz timer
configuration, responded to a 50% brightness request, and restored full
brightness while GPIO157 remained high. See
[the trial record](../perrier-backlight/README.md).
