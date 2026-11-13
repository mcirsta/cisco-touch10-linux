# Perrier PMIC ADC and CPU profiling

Ram100 (`native-diagnostics`) adds the existing mainline TWL6032 GPADC IIO
driver and Cortex-A9 PMU/perf framework on top of qualified ram99.
The later [PMU investigation](pmu-investigation.md) explains the zero
general-event counts through the CPU's debug-authentication state.
Its hardware trial and authorized sensing-state restoration passed.
**Ram100 is now the default U-Boot RAM profile; ram99 is the immediate
fallback.** The panel is running healthy stock firmware; stock audio, all
65 supply fields, ADC control/trim values and factory p8 match.

## Mainline implementation

- One `ti,twl6032-gpadc` child under the existing PMIC, logical IRQ 3,
  `#io-channel-cells = <1>`. The upstream driver uses this chip's OTP trim
  and calibration tables. Its standard initialization enables internal
  measurement paths and unmasks ADC end-of-conversion. No regulator or GPIO
  driver was added. Only internal voltage channels 7, 8, 9, 10 and 18 were
  exercised; other exposed channels are unqualified.
- The existing OMAP4460 PMU target at 0x54000000 is enabled, retaining
  upstream Cortex-A9 IRQs 54/55. CPU1 stays disabled. The wrapper follows
  the existing RAM power-domain policy and retains its debug clock branch.
  Perf and IIO configuration are enabled; no driver source changes were
  needed. No secure-register-access property is used.
- Qt, display/audio wiring, rootfs and watchdog are inherited. Only rcS's
  version marker differs in the rootfs. No blank/unblank or Qt restart was
  performed. The final source/DT checks passed all eleven patches and the
  selected schemas, including the new ADC/PMU nodes. Twelve negative DT
  mutations were rejected.

The [TI device page](https://www.ti.com/product/TWL6032), target kernel's
`drivers/iio/adc/twl6030-gpadc.c`, its binding, and
`drivers/perf/arm_pmu_platform.c` are the primary references. PMIC ADC labels
describe chip inputs; they do not establish a battery or accessory on this
PoE-powered board.

## Hardware results

Run: `../runs/20261112T114853Z-uboot-ram100-ec4b18/`.

- Twenty-five conversions delivered exactly 25 ADC interrupts. Channel 7
  read 5,017 mV; VBUS channel 10 read 4,878–4,884 mV. Channels 8/18 were
  about 6–7 mV; channel 9 was -24 to -21 mV. Near-zero calibrated readings
  do not establish a negative rail or populated external connection.
- All sixteen ADC OTP trim bytes matched stock before and after testing.
  All 65 sampled supply-register fields matched ram99 and remained stable.
  GPIO expander port stayed 0x11. Qt PID 113 stayed running, with working
  ALSA status and the inherited read-only/unmounted eMMC safeguards.
- Perf counted 50,634,055 cycles and delivered 50 overflow samples with no
  lost records. Count/running-time ratio was approximately 699.5 MHz.
  Cortex-A9 lacks per-mode event filtering; requesting user-only counting
  is rejected, so the helper counts its task across modes.
- Instruction counting and nine raw general events returned zero despite
  positive running time. Stock instruction counting also returned zero.
  Cycle counting and sampling are qualified; general event counting is
  unresolved. Secure/debug restrictions are a hypothesis, not a proven
  cause. No debug-policy bypass was attempted.
- A legacy clkdev alias exceeds its 24-character device-name limit. This
  diagnostic did not prevent PMU registration or cycle sampling; its alias
  cleanup remains separate.

The first result parser incorrectly matched `BUG:` inside ordinary
`debug:` boot messages. Its word-boundary check was corrected and the
original hardware logs were reanalyzed without rerunning conversions.
The failed parser and executed corrected source are both preserved.

## Warm-return sensing-state cleanup

Hardware-watchdog recovery returned healthy stock and the exact factory
environment. Stock audio and all sampled supply settings passed. Three
measurement enables persist across this warm reset:

| Register | Original stock | After ADC test |
| --- | --- | --- |
| 0x48:e4, VBAT/backup/VAC sensing | 00 | 07 |
| 0x49:04, USB VBUS control | 04 | 05 |
| 0x49:06, USB ID control | 14 | 15 |

The guarded `diagnostics/restore_adc_measurements.c` helper is prepared to
restore exactly these settings. It verifies stock Linux 3.4.113+, the
TWL6032 identity and all three current values before any write. USB changes
use the CLR aliases to clear measurement bit 0 while retaining other bits.
It reads back the original values. It never writes GPIO, regulator,
charger, IRQ, ADC selector or OTP calibration registers. QEMU verified its
wrong-kernel rejection before I2C access.

The first execution was rejected under AGENTS.md's read-only recovery
scope. The owner subsequently authorized **“Authorize cleanup and future
postflight.”** The exact helper ran successfully: three writes, final
`misc=00 vbus=04 id=14`. Independent stock reads confirmed all seven stable
ADC controls and all sixteen trim bytes match their original values.
Stock audio, all 65 supply fields and healthy Phoenix passed again, and
all temporary helpers were removed. No additional boot was needed.

The same cleanup is integrated into the native-diagnostics controller's
postflight after a healthy stock return. Approval and exact helper bytes
are checked before another ADC RAM boot. The standing authorization is
recorded in AGENTS.md and
`out/native-diagnostics/adc-postflight-authorization.json`; no repeat
permission is needed for this unchanged scope. Other recovery work remains
investigation only. If a later profile retains the ADC, carry this
postflight requirement into that profile too. A host that is unavailable
cannot execute postflight: watchdog boot recovery is independent, while
restoration of these sensing controls is performed by the host.

The original source snapshot `baselines/ram100` and initial reviewed
supplement `baselines/ram100-postflight` remain immutable. The final
approved runner, helper, authorization and verified results are frozen in
`baselines/ram100-authorized-postflight`. Late diagnostics and raw-event
characterization are copied/hash-recorded in the run. See
[validation-ram100.json](validation-ram100.json) and
`out/native-diagnostics/postflight-resolution.json`. Hardware-watchdog
recovery took 155.0 seconds; the authorized sensing restoration followed
once permission arrived.
