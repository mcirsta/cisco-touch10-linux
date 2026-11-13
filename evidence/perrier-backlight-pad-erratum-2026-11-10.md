# Correction to the historical GPIO151 pad label

The earlier `perrier-stock-backlight-pads-2026-11-09.txt` inspector labeled
address `0x4a100156` as MCSPI4_CLK/GPIO151. This is incorrect: GPIO151 is
MCSPI4_CLK at `0x4a100154`. The `0x156` safe-mode value belongs to
MCSPI4_SIMO and says nothing about GPIO151's routing. The original raw
capture is preserved byte for byte for its archived image manifests.

The fresh stock debugfs mux capture in
`perrier-stock-display-supplies-2026-11-10.txt` reports
`mcspi4_clk.gpio_151` at `0x154`, value `0x0003`. The official Linux 3.4
OMAP4 mux header and this unit's `idefix_display_init` disassembly agree.
`idefix_backlight_set_pad` at `0xc00322ec` writes GPIO151 high on the on
path and low on the off path. The fresh PROT_READ helper capture in
`perrier-stock-backlight-enable-corrected-2026-11-10.txt` shows GPIO151
input, with its output latch high, while stock is lit. Ram63 instead had
GPIO151 configured as an output with a low latch. Leaving this output low
is a concrete difference from the working stock/kexec display.

The ram64 DT gives the existing `pwm-backlight` driver an active-high
GPIO151 enable and its correct mux. Mainline asserts it after programming
PWM. The separately modeled GPIO157 5 V supply is enabled and settled
before PWM. This follows the intended stock callbacks with explicit GPIO
ownership and direction. PMIC and DSI voltage programming are unchanged;
the fresh stock regulator inventory uses the dummy DSI supply too and
identifies a TWL6032, so a speculative TWL6030 VCXIO provider was not added.
