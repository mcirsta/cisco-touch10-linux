# Remaining Perrier board support

Ram93 is the qualified display/touch/brightness baseline and fallback for
this next phase. Continue U-Boot RAM loading, read-only eMMC in the test
kernel, key-only SSH and the unchanged nowayout watchdog/host lease.

| Area | Current state | Mainline route and next evidence |
| --- | --- | --- |
| Display, touch, backlight | Qualified ram93, including repeated blank/unblank | Existing OMAP DRM, TC358765 bridge, panel-lvds, timer PWM, pwm-backlight and restored Gen4; production rail shutdown remains separate |
| Ethernet, UART, eMMC read, timers | Working | Existing OMAP USB/EHCI, network, serial, MMC and timer drivers |
| Front keys | Working press, hold-repeat and mute toggle | OMAP keypad/input; Qt volume remains a simulation until audio is supported |
| Temperature | Working CPU and board readings in Qt | OMAP4460 thermal and TMP102; retain stock-calibrated sensor policy |
| Red/green mute indicators | Ram94 in preparation | Mainline gpio-leds, GPIO122/119 active-high, both off at boot; exact stock pads 0x116/0x110 = 0x000b |
| System indicator | Not enabled | Stock leds_pwm; identify its PWM provider, period and polarity before adding a node |
| Power monitors | Not enabled | Two INA3221 clients on I2C4 at 0x40/0x41; determine shunts, channels, stock configuration and mainline probe writes |
| Board EEPROM | Not enabled | 24c02 at I2C4/0x54; map purpose and enable read-only AT24 access after confirming addressing |
| GPIO expander | Not enabled | PCF8574 at I2C4/0x24; map every pin before probe because quasi-bidirectional initialization can change outputs |
| Audio | Not enabled | TWL6040 at I2C1/0x4b, OMAP McPDM/DMIC and ASoC; first map stock routes, clocks, supplies, amplifiers and GPIO127 audpwron |
| PMIC, RTC, power management | Stock rails retained | TWL6032; review regulator constraints and register writes before enabling. Suspend, DVFS and full power-down need separate tests |
| CPU1/SMP | Deferred at owner's request | Stock/QEMU boot-path investigation before a live SMP test |
| SGX 3D | Parked at owner's request | Plans and protocol/API observations remain in the dedicated SGX workspace |
| Factory reset/recovery | Investigation only | Keep GPIO138 and boot/recovery selectors outside normal kernel peripheral tests |

## Ram94 acceptance

1. Preserve all ram93 hardware properties; allow only two LED nodes and
   their two-pad pinctrl group. Check DT schema, source patches, GPIO/polarity
   mutation rejection and the packed rootfs. Only LED config and the Qt
   indicator integration are new.
2. Boot through the existing one-shot U-Boot path. Verify factory p8 was
   restored before Linux, eMMC remains read-only/unmounted and watchdog feeds.
3. Read native LED class names and GPIO ownership. Toggle each color through
   LED sysfs, confirming that unrelated GPIO output/direction state stays
   constant. Qt mute drives these class devices and restores prior state
   on exit. No GPIO export or raw MMIO writes are used.
4. Check display/touch/brightness and obtain an owner observation of the
   two physical colors. Stop the host lease and verify hardware-watchdog
   recovery, stock Phoenix and exact factory p8 before promotion.

Evidence: stock inventory/topology under `out/stock-support-*-20261111.txt`,
stock GPIO LED board data in
`../../evidence/perrier-stock-mute-led-static-2026-11-11.json`, and stock
pad/GPIO readback in
`../../evidence/perrier-stock-mute-led-pads-2026-11-11.txt`.
The stock data selects two entries for board ID 9001; additional LEDs for
other board IDs are not part of this port.
