# Remaining Perrier board support

Ram104 (`mailbox-audio-dt`) is the qualified default. It packages upstream
ALSA `dmix` for concurrent speaker clients and binds the upstream OMAP
mailbox and hardware-spinlock providers. Ram100 (`native-diagnostics`) is
the immediate fallback. Ram105 adds IPv6 and DHCP observation. Ram106 applies
and renews the isolated lease with rescue SSH. Validated ram107 adds bounded
gateway, DNS and lease-loss state in the RAM rootfs. Real option delivery,
local DNS resolution and cleanup passed in a later ram110 direct-link run.
The network images are not the default because arbitrary production LAN
leases remain pending. Ram110 has now passed three U-Boot RAM boots
with both CPUs online, including one extended peripheral regression; it is
also preserved as a candidate. Ram99 and earlier baselines remain saved.
Continue U-Boot RAM loading, read-only eMMC in the test
kernel, key-only SSH and the unchanged nowayout watchdog/host lease.

| Area | Current state | Mainline route and next evidence |
| --- | --- | --- |
| Display, touch, backlight | Qualified ram93, including repeated blank/unblank | Existing OMAP DRM, TC358765 bridge, panel-lvds, timer PWM, pwm-backlight and restored Gen4; production rail shutdown remains separate |
| Ethernet, UART, eMMC read, timers | Working | Existing OMAP USB/EHCI, network, serial, MMC and timer drivers |
| IPv6, DHCP and time | Ram105: IPv6 link-local and volatile clock. Ram106: isolated DHCP lease and rescue SSH. Ram107: route/DNS event and lease-loss cleanup. The unchanged route/DNS script in ram110 passed real DHCP router/DNS delivery, local name resolution and renewal cleanup on the fixed direct link | Mainline IPv6 and BusyBox udhcpc; arbitrary production leases, external DNS, time source and IPv6 DHCP/SLAAC still need qualification. See [real-option validation](validation-ram110-network.json) |
| Front keys | Working press, hold-repeat and mute toggle | OMAP keypad/input; touch and front volume/mute keys now drive native ALSA with readback |
| Temperature | Working CPU and board readings in Qt. Ram110 reached 60.255 °C under a six-minute run. The DT-only 85 °C passive / 95 °C critical candidate passed one U-Boot RAM boot; the live clock tree read 700 MHz, a 45-second dual-core load peaked at 61.873 °C and both monitored rails stayed fixed. Stock recovery passed. The trip values are now in the canonical board DTS; compiling without the temporary overlay produces the same tested DTB | OMAP4460 thermal and TMP102. With CPUfreq off, the passive trip has no cooling map; the critical trip requests shutdown. Qualify the forced-poweroff fallback before full power policy. See [thermal policy](power/thermal-policy.md) and [validation](validation-thermal-policy.json) |
| Red/green mute indicators | Qualified ram94, both colors confirmed | Mainline gpio-leds, GPIO122/119 active-high, both off at boot; exact stock pads 0x116/0x110 = 0x000b |
| White system indicator | Qualified ram95, native Qt control physically confirmed | Mainline TWL6032 MFD, ordinary TWL PWM channel 1 and pwm-leds; low/off test uses stock startup level 10/255 |
| Power monitors | Qualified ram95, all six channels in Qt | Two mainline INA3221 clients on I2C4 at 0x40/0x41, 10 mΩ shunts, stock 0x7127 config and maximum alerts; summation remains disabled |
| Board EEPROM | Qualified ram95, read-only | Mainline AT24 at I2C4/0x54, 256 bytes; exact stock hash matched in RAM and after recovery, read-only sysfs permissions |
| GPIO expander | Qualified ram96 provider and AS-IS reads, byte 0x11 shown in Qt | Existing PCF857x driver at I2C4/0x24; stock has no requested line at the captured point. Physical pin functions remain unknown; see [mapping investigation](expander-pin-investigation.md) before driving any line |
| RTC | Qualified ram96 counter and one alarm interrupt, exact alarm restoration | Existing rtc-twl, PMIC IRQ 11. Calendar remains unconfigured (2000-01-01); no HCTOSYS/SYSTOHC/NVMEM. Suspend wakeup and retention without external power remain separate |
| PMIC 32 kHz clocks | Qualified ram96 providers and read API | Existing clk-twl supplies clk32kg/clk32kaudio, both 32768 Hz; zero prepare/enable counts, hardware state preserved. Consumer switching and physical frequency measurement pending |
| Audio | Qualified ram104 packaged upstream `dmix`: two concurrent silent 48 kHz clients finished; Qt ALSA volume/mute and native 88.2/96 kHz DMA remain inherited | Mainline TWL6040/McPDM/SDMA plus upstream ALSA plugins; HFR only. ABE DSP effects and production power policy remain separate. EP unused/unqualified |
| OMAP mailbox and hardware spinlock | Qualified ram104 provider binding at 0x4a0f4000 and 0x4a0f6000; both runtime suspended with no remote core started | Upstream `omap-mailbox` and `omap_hwspinlock`; only their L4 target modules are enabled. Message traffic, lock acquisition and DSP/IPU remoteproc are separate work |
| PMIC ADC | Qualified ram100 internal channels 7/8/9/10/18, 25 conversions/IRQs, OTP trim preserved | Unmodified TWL6032 GPADC/IIO; exact sensing-state postflight is approved and automatic for this profile. Other channels and suspend policy remain unqualified |
| CPU performance monitoring | Qualified ram100 cycle counts and 50 overflow samples | General events are disabled by the CPU's debug-authentication state (`DBGAUTHSTATUS=0xaa`); stock also reads zero. Keep mainline perf and do not set `secure-reg-access` in Non-secure Linux. See [PMU investigation](pmu-investigation.md) |
| PMIC power management | Transport, PWM, RTC and clock APIs working. The [31-word stock capture](../../evidence/perrier-omap-prm-power-stock-2026-11-13.md) confirmed Cisco's three VC address/command pairs and active VP requests. Ram114's isolated VC bypass provider and mainline OPP path passed bounded 350/700 MHz dynamic voltage tests. The [three-point curve](validation-cpu-dvfs-voltage-curve.json) measured nominal 1.203/1.152/1.101 V at 350 MHz. The 1.101 V image passed a five-minute two-core hold and measured about 22% less power on the likely MPU rail than ram114 at the same frequency. Its dynamic sampler found no stable low selector at 700 MHz. All RAM boots recovered to stock. See [ram115 validation](validation-cpu-dvfs-low-trial.json) and [ram116 validation](validation-cpu-dvfs-mid-trial.json) | Treat the INA mapping as strong software evidence, not a measured PCB net. The monitored 5 V channel changed at most about 1.3%; whole-device input energy remains unmeasured. CPUfreq and AVS remain off in the canonical board image, PM late init stays blacklisted, and the board DTS deletes inherited CPU OPPs. Ram112's CPU1 hotplug cleanup panicked; ram113 onward disabled hotplug. The [write audit](power/pm-late-init-audit.md) found a generic 1.375 V ON command and VP enable-bit clear. Full PM/AVS integration, overnight stability, error-checked compute under low voltage, thermal cooling, suspend and full power-down remain separate work; see the [DVFS plan](power/dvfs-plan.md) |
| CPU1/SMP | Stock has two cores; earlier kexec SMP images failed at initramfs unpack, including `nosmp`. Ram108 passed from U-Boot with `nosmp`; ram109 brought CPU1 online after watchdog startup. Ram110 passed boot-time CPU1 release three times, including a six-minute load/peripheral run and a real DHCP/DNS run, with watchdog and exact stock recovery. Ram112 also ran both cores at 350 MHz for ten seconds. Ram113 passed two-core fixed-350-MHz load for 20 and 60 seconds, with peak CPU temperature 59.2 °C, and `schedutil` selected 350 MHz at idle and 700 MHz under load. Ram114 kept both cores online for bounded dynamic frequency and voltage tests | The ram112 cleanup hit a NULL pointer in OMAP4 CPU hotplug because this RAM policy skips the PM init that fills CPU1's power-domain pointer. Ram113/ram114 disable runtime hotplug; keep that guard until safe selective PM initialization is implemented. Qualify longer-term dual-core and voltage-scaling policy. See [ram114 validation](validation-cpu-dvfs-trial.json), [ram113 validation](validation-cpu-m2-smp-safe.json) and [extended ram110 validation](validation-ram110-extended.json) |
| SGX 3D | Parked at owner's request | Plans and protocol/API observations remain in the dedicated SGX workspace |
| Factory reset/recovery | Investigation only | Keep GPIO138 and boot/recovery selectors outside normal kernel peripheral tests |

## Ram104 completed

The first bundled ram103 image packaged `dmix`, but its provider drivers
could not bind because the baseline RAM DT disabled their entire L4 parent
segment. Ram104 enables the segment, explicitly disables its unrelated
children, and preserves no-reset-on-init for the mailbox and spinlock
targets. The exact DT delta and four Kconfig additions passed offline audit.
Both upstream drivers bound in one U-Boot RAM boot. Their runtime power state
was suspended; the remoteproc class remained absent. Packaged two-client
silent playback passed, Qt stayed on the same PID, and the nowayout watchdog
kept feeding. No display reset or Qt restart was performed. Stock recovery,
exact factory p8 and the authorized ADC postflight passed. See
[validation-ram104.json](validation-ram104.json) and the frozen
`baselines/ram104` source snapshot. Ram100 is the fallback.

## Ram100 completed

ADC and CPU cycle/sampling checks passed in one RAM boot with unchanged
supply fields, one Qt start and zero display cycles or Qt restarts.
General PMU events remain zero and unqualified; ram101/102 subsequently
identified disabled debug authentication as the cause. Watchdog recovery took
155.0 seconds. The owner approved restoration of the three surviving
ADC sensing controls and the identical future postflight. The helper
restored 00/04/14 with readback; stock ADC/trim/audio/supply checks passed.
Authorization, helper integrity and stock-health guards are preserved.
See [native-diagnostics.md](native-diagnostics.md) and
[validation-ram100.json](validation-ram100.json).

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
[the audio tools](../audio/README.md). Ram99 subsequently connected Qt
volume/mute to native ALSA.

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
