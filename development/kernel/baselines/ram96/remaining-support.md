# Remaining Perrier board support

Ram95 is the qualified default, adding the white indicator, six power
monitor channels and read-only board EEPROM to ram94. Ram94 is its fallback;
ram93 remains the preserved display baseline.
Continue U-Boot RAM loading, read-only eMMC in the test
kernel, key-only SSH and the unchanged nowayout watchdog/host lease.

| Area | Current state | Mainline route and next evidence |
| --- | --- | --- |
| Display, touch, backlight | Qualified ram93, including repeated blank/unblank | Existing OMAP DRM, TC358765 bridge, panel-lvds, timer PWM, pwm-backlight and restored Gen4; production rail shutdown remains separate |
| Ethernet, UART, eMMC read, timers | Working | Existing OMAP USB/EHCI, network, serial, MMC and timer drivers |
| Front keys | Working press, hold-repeat and mute toggle | OMAP keypad/input; Qt volume remains a simulation until audio is supported |
| Temperature | Working CPU and board readings in Qt | OMAP4460 thermal and TMP102; retain stock-calibrated sensor policy |
| Red/green mute indicators | Qualified ram94, both colors confirmed | Mainline gpio-leds, GPIO122/119 active-high, both off at boot; exact stock pads 0x116/0x110 = 0x000b |
| White system indicator | Qualified ram95, native Qt control physically confirmed | Mainline TWL6032 MFD, ordinary TWL PWM channel 1 and pwm-leds; low/off test uses stock startup level 10/255 |
| Power monitors | Qualified ram95, all six channels in Qt | Two mainline INA3221 clients on I2C4 at 0x40/0x41, 10 mΩ shunts, stock 0x7127 config and maximum alerts; summation remains disabled |
| Board EEPROM | Qualified ram95, read-only | Mainline AT24 at I2C4/0x54, 256 bytes; exact stock hash matched in RAM and after recovery, read-only sysfs permissions |
| GPIO expander | Not enabled | PCF8574 at I2C4/0x24; map every pin before probe because quasi-bidirectional initialization can change outputs |
| Audio | Not enabled | TWL6040 at I2C1/0x4b, OMAP McPDM/DMIC and ASoC; first map stock routes, clocks, supplies, amplifiers and GPIO127 audpwron |
| PMIC, RTC, power management | PMIC transport/PWM working; RTC and rail policy pending | No PMIC regulator or power-controller driver enabled. RTC, suspend, DVFS and full power-down remain separate board work |
| CPU1/SMP | Deferred at owner's request | Stock/QEMU boot-path investigation before a live SMP test |
| SGX 3D | Parked at owner's request | Plans and protocol/API observations remain in the dedicated SGX workspace |
| Factory reset/recovery | Investigation only | Keep GPIO138 and boot/recovery selectors outside normal kernel peripheral tests |

## Test workflow

Bundle independent, safe peripheral changes in one U-Boot RAM image rather
than spending a boot cycle on each small feature. Keep the qualified display
running: no blank/unblank cycles or Qt restarts for unrelated peripherals.
Reuse its frozen validation when display source and wiring are unchanged.
Retain the host lease, SSH and hardware-watchdog return to stock.

Ram95 combines the PMIC PWM white LED, both three-channel INA3221 monitors
and read-only EEPROM. It adds no regulator or analog PMIC child, leaves PMIC
clock initialization to the bootloader and keeps summation disabled on the
monitors. Stock register 0x7127 and maximum alert limits match mainline's
reset defaults. The I2C1/I2C4 pad settings are copied from live stock readback.
The TWL binding gains the zero address-cell declaration for its interrupt
provider; the device drivers are unmodified.

All three groups passed in one RAM boot, with zero display cycles and zero
Qt restarts. Ten Qt white-LED changes were verified and physically confirmed.
Hardware-watchdog recovery took 153.7 seconds, restored exact factory p8,
and returned all sampled PMIC registers and indicator states to stock.
See [validation-ram95.json](validation-ram95.json).

PMIC offsets 0x53/0x59 read 5 in RAM and 1 under stock. The new drivers have
no write path to those fields, and they remain stable through all PWM use.
They returned to 1 after stock recovery; all other sampled settings matched.
Exact attribution within startup/stock power policy remains a production
power-management follow-up. Do not write the stock values back manually.

## Ram94 acceptance (completed)

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

The system indicator data is saved in
`../../evidence/perrier-stock-system-led-static-2026-11-11.json`.
Stock adds two fields to the v3.4 PWM LED structure: a probe initialization
flag and initial brightness 10. The running stock UI currently leaves this
LED at zero. Its PMIC PWM is distinct from timer10 LCD backlight PWM.
The owner identified it as the white light seen during boot. A temporary
stock LED-class test at 10/255 physically confirmed the mapping and restored
the prior zero brightness. See
`../../evidence/perrier-white-system-led-2026-11-11.json`.

For INA3221, the current mainline driver's runtime resume resets the chip,
restores its cached config and programs summation control. Review the stock
alert limits and the board's alert wiring as well as channel shunts before
probing either client. Reading voltages is the goal; a measurement-device
probe must not silently change a board protection output.
