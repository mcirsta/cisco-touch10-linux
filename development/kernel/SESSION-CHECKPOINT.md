# Session checkpoint — 2026-11-12

## Validated ram107: DHCP route, DNS and lease-loss state

Ram107 (`network-route-dns`) changes only the volatile DHCP script and
release marker from ram106; the kernel drivers, DTB, Qt and watchdog are
unchanged. On the direct PC link it bound the fixed lease, applied a
temporary gateway/DNS event, and removed that state on real DHCP renewal.
Deconfig kept the separate 10.77.10.11 rescue SSH address while removing
the managed .10 address; a later real renewal restored .10. No display
reset or Qt restart was run. Requested recovery returned healthy stock in
36.8 seconds with exact factory p8 and the approved ADC postflight.

The source and evidence are frozen in `baselines/ram107`,
[validation-ram107.json](validation-ram107.json), and
[network-route-dns.md](network-route-dns.md). The isolated DHCP server does
not advertise router/DNS options, so the live route/DNS event was injected
inside the RAM image. A real server-supplied option and DNS lookup remain
to test before changing the default from ram104. The stock expander pins
remain read-only; see [the mapping investigation](expander-pin-investigation.md).

## Validated ram106: isolated DHCP address and renewal

Ram106 (`network-dhcp`) retains ram105's kernel drivers and DTB. It keeps
10.77.10.11/24 for rescue SSH while BusyBox udhcpc applies the PC's fixed
10.77.10.10/24 lease. A forced renewal retained both addresses; SSH through
the rescue address reached the same boot. Qt stayed on PID 126, the nowayout
watchdog fed, and eMMC stayed read-only and unmounted. No display reset or Qt
restart occurred. Requested recovery returned to healthy stock in 36.8
seconds, restored exact factory p8, and completed the approved ADC postflight.
The frozen source and logs are in `baselines/ram106` and
[validation-ram106.json](validation-ram106.json). Ram104 remains the default
until production router/DNS and lease-loss behavior are qualified.

The first ram106 hardware attempt had working DHCP but its host controller
timed out because a static RAM identity table omitted ram106. The watchdog
returned to stock, exact factory p8 and manual authorized ADC postflight
passed. The identity check now derives the version from the boot marker and
has regression tests. The second, clean run above passed. The controller's
exception path now performs the approved ADC postflight after stock recovery.

## Validated ram105: IPv6, DHCP observation and volatile time

Ram105 (`network-dualstack`) was built from ram104 with only mainline IPv6
Kconfig additions and a bounded BusyBox DHCP observer. The board DTB,
display path, Qt executable, watchdog feeder and static 10.77.10.10 rescue
address were unchanged. On the direct PC link, the panel kept the stock MAC
24:16:9d:b6:77:bb, acquired stock-matching IPv6 link-local
fe80::2616:9dff:feb6:77bb, pinged the PC over IPv6, and received the
10.77.10.10/24 DHCP reservation. The host set only the RAM system clock;
the unconfigured PMIC RTC was not written.

Qt stayed on its original PID, WDT2 kept feeding, and eMMC was read-only and
unmounted. Requested recovery returned to stock Linux 3.4.113+ and Phoenix
in 36.7 seconds. Factory p8 matched the saved hash; the approved ADC
postflight restored 00/04/14. No display cycle or Qt restart was run.
Source, image and run evidence are frozen in `baselines/ram105` and
[validation-ram105.json](validation-ram105.json). Ram104 remains the default
until the DHCP address, route and DNS script is qualified.

The old SMP trials are being investigated separately. They used kexec and
failed during initramfs unpack even with `nosmp`; there is no proof yet that
CPU1 caused the parser failure. SGX/3D remains parked.

## Qualified ram104: mailbox, spinlock and shared audio

Ram104 (`mailbox-audio-dt`) is now the default U-Boot RAM profile; ram100
(`native-diagnostics`) is the immediate fallback. The upstream OMAP mailbox
and hardware-spinlock drivers bound at 0x4a0f4000 and 0x4a0f6000. Both
were runtime suspended, and no DSP/IPU remote processor was started. The
new DT enables only their L4 target modules and keeps the other children
disabled. It retains the qualified display wiring and Qt binary.

The packaged upstream ALSA `dmix` configuration served two overlapping
silent 48 kHz clients in 9.3 seconds. Qt stayed on PID 114; the hardware
watchdog kept feeding; eMMC remained read-only and unmounted. No display
blank/unblank or Qt restart was performed. One-shot U-Boot restored factory
p8 before kernel handoff, then stock Linux 3.4.113+ and Phoenix returned.
Factory p8 matched
`f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
The authorized ADC postflight restored 00/04/14. Validation is saved in
[validation-ram104.json](validation-ram104.json), the source in
`baselines/ram104`, and the live run in
`development/runs/20261112T141303Z-uboot-ram104-9d19fd`.

The intermediate ram103 image proved the audio package but could not bind
the two drivers because its parent L4 segment was disabled. Its stock
recovery and ADC postflight passed. Its staged files were verified against
the saved host copies and removed to free p14 space. Ram104 staging remains.

## Shared audio and RAM clock follow-up

The already qualified ram100 image was booted once for two independent
RAM-only checks. An isolated upstream ALSA build with `dmix` allowed two
overlapping silent 48 kHz speaker streams to finish; the baseline rejected
the second stream as busy. The new library and configuration are saved as
candidates, not yet installed in an image. Volatile system time was also
set from the host without writing the RTC; Qt PID and watchdog stayed
stable. Details: [shared-playback.md](../audio/shared-playback.md).

That U-Boot session passed, returned to stock Linux 3.4.113+, verified exact
factory p8, and completed the authorized ADC postflight. It ran no display
blank/unblank or Qt restart checks. Ram100 was the qualified default at
that checkpoint; ram104 now packages the audio path.

## PMU investigation update

Ram101/102 identified why the general event counters read zero. The CPU's
debug-authentication status is `0xaa`: non-secure non-invasive debug is
disabled. ARMv7 requires general events to stop in that state and permits
cycle counting when PMCR.DP=0. The direct ram102 counter test read back event
`0x68`, but counted zero hardware events and software increments; standard
perf still counted 50 cycle-overflow samples. Waking the mainline debug
subsystem clock did not change this. Stock also counts cycles but zero
instructions. SDER access traps in our Non-secure Linux boot, so the
`secure-reg-access` DT property is invalid here. See
[pmu-investigation.md](pmu-investigation.md) and the preserved
`validation-ram101.json` / `validation-ram102.json` records.

The panel is back on stock Linux 3.4.113+ with Phoenix running. Ram102
hardware-watchdog recovery took 151.8 seconds, factory p8 matched, and the
owner-approved ADC postflight and independent stock ADC/trim/audio/supply
checks passed. Diagnostic p14 stage files were archived on the host and
removed; ram99/100 staged fallbacks remain. The active kernel sources and
patch manifest were restored exactly to qualified ram100. Ram100 remains the
default; no display cycle or Qt restart was performed.

**Ram100 `native-diagnostics` was the default U-Boot RAM profile at this
checkpoint, with ram99 `speaker-audio` as fallback.** The panel was
back on stock Linux 3.4.113+ with Phoenix running. Hardware-watchdog
recovery took 155.0 seconds. Factory p8 remains exactly
`f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
The controller/capture ended; temporary helpers were removed.

## New mainline support

- Unmodified TWL6032 GPADC/IIO driver: one PMIC child, compatible
  `ti,twl6032-gpadc`, logical IRQ 3, #io-channel-cells = <1>. Twenty-five
  internal voltage conversions across channels 7/8/9/10/18 delivered
  exactly 25 EOC IRQs. Channel 7 read 5,017 mV; VBUS 10 read 4,878–4,884 mV;
  other tested internal inputs were near zero. All 16 OTP trim bytes match
  stock. Other exposed channels and temperature conversion are unqualified.
- Unmodified Cortex-A9 PMU/perf using the upstream OMAP4460 target and
  IRQs 54/55. CPU1 stays disabled. Cycle count 50,634,055, overflow samples 50,
  losses 0, approximate count/running-time ratio 699.5 MHz. Cortex-A9 cannot
  exclude individual CPU modes. General instruction and nine raw events
  read zero, including stock instructions. Ram101/102 subsequently confirmed
  that CPU debug authentication is disabled. Do not enable
  secure-reg-access in this Non-secure boot.
- DT/config changes only; existing display, Qt, touch, audio and watchdog
  code/binary remain inherited. Rootfs changes only version markers.
  Qt PID 113 stayed running: one boot, no display cycles or Qt restarts.
  All 65 sampled supply fields stayed unchanged; GPIO expander0x11.

Source/DT checks passed all 11 patches and selected schemas including the
ADC/PMU nodes. Twelve unsafe DT mutations were rejected. Original snapshot:
`baselines/ram100`. Detailed record: [native-diagnostics.md](native-diagnostics.md).
Validation: [validation-ram100.json](validation-ram100.json).
Run: `development/runs/20261112T114853Z-uboot-ram100-ec4b18`.

## ADC cleanup is authorized and verified

Three measurement enables survive warm reset: 0x48:e4 becomes 07 versus
stock 00; USB controls 0x49:04 and0x49:06 become 05/15 versus stock 04/14.
The owner explicitly replied **“Authorize cleanup and future postflight.”**
This grants the same bounded restoration after future ADC RAM tests.
Standing scope is recorded in AGENTS.md and
`out/native-diagnostics/adc-postflight-authorization.json`; do not ask again
for unchanged cleanup. All other recovery work remains investigation only.

The guarded helper ran successfully: **three writes, readback 00/04/14**.
It checks stock kernel/chip/current values and clears USB measurement bits
through CLR aliases, preserving other bits. It does not touch regulators,
GPIO, charger, IRQ, selector or OTP. Exact helper SHA-256:
`921a877fcbb0b1f9a711d1c22d5b8db6cabf39df70c8cab96e400a3942cbc6e6`.
Independent postchecks verified all stable ADC controls, 16 trim bytes,
stock audio's 83 controls/HFR-on/EP-off, all 65 supply fields, GPIO 0x11 and
healthy Phoenix. Temporary helpers were removed. No additional boot was
needed for restoration.

The U-Boot controller checks approval and the exact helper before another
native-diagnostics boot, then invokes it after healthy stock return. Carry
this requirement into later ADC-containing profiles. Hardware-watchdog
boot recovery is independent; the host performs measurement restoration.
If the host is unavailable, these sensing enables can persist until host
postflight is run. No rail state or persistent firmware write is involved.

The original approval rejection/pending state is preserved historically,
not active. Resolution: `out/native-diagnostics/postflight-resolution.json`.
The original `baselines/ram100-postflight` and final
`baselines/ram100-authorized-postflight` supplements are immutable. They
record the approved helper, runner, authorization and successful checks.

## Retained working support

Display/touch/backlight, Ethernet/UART/storage reads/timers, front keys,
CPU/TMP102 thermal readings, mute LEDs, white LED, six INA3221 channels,
read-only EEPROM, RTC counter/restored alarm, GPIO AS-IS reads and clock
APIs retain their prior qualification. Avoid display cycling/restarts for
unrelated work. Bundle independent additions in a test session.

Ram99's default ALSA PCM handles 48 kHz mono/stereo S16_LE through upstream
plug/rate/route to 96 kHz four-channel S32_LE, only HFR slot 3 active. Qt
volume/mute/front keys control native ALSA with readback, HFR gain 0..24,
zero/mute Off. The owner confirmed sound/volume/mute; the corrected app
completed 1,440,000 frames with 0 recoveries. Qt binary remains
`384466222476f0b631ecc318117cf0716caacde07ebdbb4d9d51346b71929eb8`.
EP is only a generic codec label, not a confirmed earpiece. The owner has
only built-in speakers; use HFR. One PCM client at a time; mixing/ABE DSP
processing remain separate. See [application-audio.md](application-audio.md).

Guard hash remains
`7b98f7d64dbf44e212a22f671d4b33158e70a37d8d9afd6250e1f1cf73625a16`.
RAM eMMC stays read-only/unmounted; U-Boot restores factory p8 before Linux.
No kernel/rootfs was installed as the persistent boot target. Stage p14
has **36000 KiB free** after byte-verified removal of the ram105 and ram106
test staging files. The first ram106 seed-specific DTB was saved on the PC
before cleanup. Ram104 and ram100 remain staged as fallbacks; earlier
qualified images remain saved on the PC.

```sh
python3 tools/touch10_uboot.py prepare --profile native-diagnostics
python3 tools/touch10_uboot.py session --profile native-diagnostics --minutes 60
# Immediate fallback: --profile speaker-audio
```

Key-only SSH uses access/ssh_config. No root password or power cycling is
needed for routine tests. PMIC regulator/voltage policy, GPIO output/pin
mapping, suspend/DVFS, RTC retention/wakeup and physical clock measurements
remain pending. Existing PMIC 0x53/0x59=5 in RAM/1 in stock restores correctly;
do not manually write those values. SMP is under boot-path and early-watchdog
investigation; SGX stays parked.
A legacy PMU clock alias exceeds 24 characters; it does not prevent cycle
sampling, but alias cleanup and general event counters remain open.
Recovery/factory-reset selectors remain investigation only. Maximum
brightness observation remains unconfirmed. See [remaining-support.md](remaining-support.md).
