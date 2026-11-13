# Mainline driver coverage and remaining patch boundary

The Touch 10 RAM image is based on Linux 6.18.48. The active source
manifest contains 11 exported patch groups against the pristine release;
they separate generic driver work, Perrier DT wiring and RAM-only safety.
The working hardware path is validated in the `ram110` U-Boot RAM profile,
while `ram104` remains the qualified default and stock is the recovery
target. No display reset test is needed for unrelated work.

| Area | Mainline use now | What we still carry |
| --- | --- | --- |
| CPU, memory, timers, SMP, UART, USB/Ethernet, read-only eMMC | OMAP/ARM core, clock, serial, USB/net and MMC drivers | Board DT wiring and three RAM-only safety edits for clock/reset/eMMC policy. CPU rate stays fixed at 700 MHz. |
| GPIO, pinctrl, front keys, LEDs, thermal, watchdog | Existing GPIO/pinctrl, keypad, LEDs, OMAP bandgap/TMP102 and watchdog drivers | A generic PCF857x retain-state option (30 patch lines) prevents a shutdown port write. |
| RTC, PMIC ADC/PWM/32 kHz, INA3221, EEPROM | Existing TWL, IIO, PWM, INA3221 and AT24 drivers | DT/binding descriptions; no replacement sensor or PMIC driver. |
| Audio | Existing McPDM, TWL6040 and ALSA `dmix` | A 49-line ASoC routing patch. Stock ABE DSP effects and unused EP output are not qualified. |
| Display | Existing OMAP DRM DISPC/DSS, panel-lvds and pwm-backlight | A 15-line generic PLL correction, roughly 230 lines in OMAP DSI, and roughly 490 lines extending the TC358775 bridge driver for TC358765. DISPC and DSS source overrides were removed. |
| Touch | Linux input multitouch interfaces | Restored Cypress Gen4 core/I2C driver, about 2,400 patch lines. Upstream `cyttsp5` is a V5 HID protocol driver, not a direct replacement for this V4 controller. |
| Mailbox and hardware spinlocks | Existing OMAP drivers bind through DT | DSP/IPU firmware execution and ownership remain separate from provider support. |
| CPU voltage/frequency | Upstream thermal and clock infrastructure, with fixed inherited MLO setting | A candidate 350/700 MHz path can likely use `cpufreq-dt` and the existing M2 divider with a DT override; it has not been booted. Dynamic voltage and higher OPPs need a real MPU regulator/OMAP VC policy. Generic PM init currently writes different VC/VP settings from stock. See [clock audit](power/cpufreq-clock-audit.md) and [PM audit](power/pm-late-init-audit.md). |

The patch sizes above include context and deleted lines; they are not counts
of added code. The [patch manifest](patches/manifest.json) is the source of
truth for exact files and hashes.

## Next upstream cleanup

1. Keep Perrier wiring and polarity in DT. Remove test-only board checks
   from reusable drivers. In particular, the bridge's `tc_is_perrier()`
   currently checks the root `cisco,perrier-ram` compatible; a production
   board compatible would not take that path. Refactor the TC358765 behavior
   into chip and, where necessary, panel/board match data before using a
   different root compatible.
2. Isolate the Gen4 protocol core from Perrier reset timing, supply order
   and report layout. Keep the standard Linux input ABI and document any
   per-panel properties in the binding. The V5 driver should remain
   separate because its HID command/report protocol differs.
3. Keep generic DSI, PLL, GPIO and ASoC fixes as separate patches. Maintain
   a small board DTS rather than copying vendor device drivers.
4. Keep the one-shot U-Boot wrapper, eMMC write guard and host watchdog
   policy in development tooling. They are for RAM validation, not a
   production upstream kernel.
5. Implement CPU voltage and clock transitions only after the exact
   TWL6032 VC/VP policy, OMAP4460 clock output and OPP qualification are
   resolved. The current common board `.dtsi` deletes inherited OPPs, and
   the RAM image leaves CPUfreq and AVS off.
