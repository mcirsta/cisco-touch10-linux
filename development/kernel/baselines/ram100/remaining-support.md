# Remaining Perrier board support

Ram99 (`speaker-audio`) is the qualified default for 48 kHz application
playback and real Qt volume/mute. Its hardware setup is unchanged from
ram97 (`native-audio`), the immediate fallback. Ram96 and ram93 remain
preserved peripheral/display baselines.
Continue U-Boot RAM loading, read-only eMMC in the test
kernel, key-only SSH and the unchanged nowayout watchdog/host lease.

| Area | Current state | Mainline route and next evidence |
| --- | --- | --- |
| Display, touch, backlight | Qualified ram93, including repeated blank/unblank | Existing OMAP DRM, TC358765 bridge, panel-lvds, timer PWM, pwm-backlight and restored Gen4; production rail shutdown remains separate |
| Ethernet, UART, eMMC read, timers | Working | Existing OMAP USB/EHCI, network, serial, MMC and timer drivers |
| Front keys | Working press, hold-repeat and mute toggle | OMAP keypad/input; touch and front volume/mute keys now drive native ALSA with readback |
| Temperature | Working CPU and board readings in Qt | OMAP4460 thermal and TMP102; retain stock-calibrated sensor policy |
| Red/green mute indicators | Qualified ram94, both colors confirmed | Mainline gpio-leds, GPIO122/119 active-high, both off at boot; exact stock pads 0x116/0x110 = 0x000b |
| White system indicator | Qualified ram95, native Qt control physically confirmed | Mainline TWL6032 MFD, ordinary TWL PWM channel 1 and pwm-leds; low/off test uses stock startup level 10/255 |
| Power monitors | Qualified ram95, all six channels in Qt | Two mainline INA3221 clients on I2C4 at 0x40/0x41, 10 mΩ shunts, stock 0x7127 config and maximum alerts; summation remains disabled |
| Board EEPROM | Qualified ram95, read-only | Mainline AT24 at I2C4/0x54, 256 bytes; exact stock hash matched in RAM and after recovery, read-only sysfs permissions |
| GPIO expander | Qualified ram96 provider and AS-IS reads, byte 0x11 shown in Qt | Existing PCF857x driver at I2C4/0x24; read-only probe and flags=0 requests preserve pins. Optional shutdown-retention guard prevents all-high write. Map pin functions and output latches before driving any line |
| RTC | Qualified ram96 counter and one alarm interrupt, exact alarm restoration | Existing rtc-twl, PMIC IRQ 11. Calendar remains unconfigured (2000-01-01); no HCTOSYS/SYSTOHC/NVMEM. Suspend wakeup and retention without external power remain separate |
| PMIC 32 kHz clocks | Qualified ram96 providers and read API | Existing clk-twl supplies clk32kg/clk32kaudio, both 32768 Hz; zero prepare/enable counts, hardware state preserved. Consumer switching and physical frequency measurement pending |
| Audio | Qualified ram99 48 kHz mono/stereo application playback and Qt ALSA volume/mute; native ram97 88.2/96 kHz DMA retained | Mainline TWL6040/McPDM/SDMA plus upstream ALSA plugins; HFR only, mixer readback and bounded nonblocking Qt sound test. Concurrent mixing, ABE DSP effects and production power policy remain separate. EP unused/unqualified |
| PMIC power management | Transport, PWM, RTC and clock APIs working; rail policy pending | No PMIC regulator or power-controller driver enabled. Suspend, DVFS and full power-down remain separate board work |
| CPU1/SMP | Deferred at owner's request | Stock/QEMU boot-path investigation before a live SMP test |
| SGX 3D | Parked at owner's request | Plans and protocol/API observations remain in the dedicated SGX workspace |
| Factory reset/recovery | Investigation only | Keep GPIO138 and boot/recovery selectors outside normal kernel peripheral tests |

## Test workflow

Bundle independent, safe peripheral changes in one U-Boot RAM image rather
than spending a boot cycle on each small feature. Keep the qualified display
running: no blank/unblank cycles or Qt restarts for unrelated peripherals.
Reuse its frozen validation when display source and wiring are unchanged.
Retain the host lease, SSH and hardware-watchdog return to stock.

Ram99 adds userspace audio only. The six-case ARM/QEMU conversion test
and mono/stereo 48 kHz panel playback passed. Qt's original period-time
setup error was fixed over RAM SSH with one clean app restart; the owner
confirmed the corrected app. Its 30-second stream completed 1,440,000
frames with zero recoveries, and 124 stable independent mixer samples
matched Qt. The final packaged binary is identical, starts once on ram99,
and passed the shared silent PCM-setup diagnostic. No display reset cycles
were used. Final hardware recovery took 150.8 seconds; stock audio and all
65 sampled PMIC fields matched. See [application-audio.md](application-audio.md)
and [validation-ram99.json](validation-ram99.json). Ram98's original package
is preserved as not promoted.

Ram97 completed one RAM boot with no display cycles or Qt restarts. Perrier
stock data and live APIs mapped GPIO127 AUDPWRON, GIC SPI119, codec revision
0x02 and the CLK32KAUDIO reference. Stock's vio/v2v1 consumers are dummy
regulators; physical rails remain inherited, with no PMIC voltage programming.
The 65 sampled rail fields match ram95 before probe and stayed stable
through HFR/EP/rate tests. The GPIO expander stayed 0x11. The owner heard
HFR tones. DMA timestamp rates measured about 88,124 and 96,024 frames/s
for requested 88,200/96,000. Hardware-watchdog recovery took 150.6 seconds,
restored factory p8 and healthy stock HFR routing with EP disabled; all 65
stock rail fields matched the original baseline.

Cisco's alsafifo opens a mono 48 kHz S16_LE stream. Its active ABE route is
HFR, matching the right-channel-only stock board flag. EP is another codec
output name, not proof of another speaker or an accessory socket. The owner
has nothing external connected. EP DAC/amp activation and PCM passed, but
no sound was heard at minimum or modest gains. Keep it unqualified rather
than driving unknown pins or rails. The software path cannot establish
the physical number of speaker transducers.

See [validation-ram97.json](validation-ram97.json) and
[the audio tools/next userspace plan](../audio/README.md). Qt's audio
volume/mute remain a simulation; mute LED control is already native.

Ram96 uses one RAM boot for all three new API groups, with zero display
cycles and zero Qt restarts. The five-second alarm delivered one parent
and one nested interrupt, then its cached state and hardware alarm/enable
bytes were restored. GPIO debugfs state remained identical, and native
AS-IS reads matched direct I2C reads. The clock providers' control registers
matched stock throughout. Hardware-watchdog recovery took 151.8 seconds,
restored exact factory p8 and returned to healthy stock firmware. Read-only
post-recovery checks confirmed the RTC, expander and PMIC clock state.
See [validation-ram96.json](validation-ram96.json) and the
[RTC, GPIO and audio record](rtc-gpio-audio.md).

The mainline GPIO probe does not write the port. The optional new generic
shutdown-retention property prevents the normal shutdown all-high write;
its actual implementation was tested offline with all 256 eight-bit latch
states. Pin mappings and output control remain unqualified. The RTC and
clock drivers are unmodified. No audio or regulator driver was enabled.

The earlier read-only stock audio work captured 83 ALSA controls, McPDM
pads, sys_nirq2 and GPIO127 audpwron. Ram97 then used that evidence for
the mainline bring-up above. Stock ABE DSP effects and production power
management remain separate; unconnected microphones/DMIC stay disabled.

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
