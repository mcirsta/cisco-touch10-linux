# Perrier dynamic CPU frequency and voltage plan

The owner's target is load-based CPU frequency scaling with a matching MPU
voltage change for lower power use. The CPU and its TWL6032 SMPS1 supply must
share one policy: raising performance requires voltage first, and lowering
performance requires the clock first. The current validated ram110 kernel
stays fixed at 700 MHz and inherits about 1.208 V on the likely MPU INA3221
channel. Stock Linux instead uses SmartReflex/VP and has requested about
0.988 V at 700 MHz, closely matching a 0.992 V INA sample. These are two
different boot policies, not an OPP voltage table to copy without testing.

## First experiment: clock only

The isolated [ram112 source](omap4-cisco-perrier-cpu-m2-ram.dts) and
[reviewed image](../../perrier-ramenv/cpu-m2-trial/reviewed-image.json)
enable only 350 and 700 MHz with mainline `cpufreq-dt`, OPP v2, and the
existing OMAP `ti,divider-clock`. CPU0's clock reference changes from the
MPU DPLL to the M2 divider already used by MPUSS. Both CPU nodes share the
OPP table. The table has no `opp-microvolt` and the CPUs have no
`cpu-supply`, so this image requests **no voltage transition**. The
performance governor starts at 700 MHz, and `maxcpus=1` keeps CPU1 offline
for the first bounded test. Legacy `omap-cpufreq` and `ti-cpufreq` were
explicitly disabled after Kconfig's defaults enabled them in the first
offline build. OMAP PM late init and AVS remain disabled. The 85/95 °C trips
and nowayout watchdog are inherited from the validated thermal profile.

The [image audit](audit_cpu_m2_candidate.py) checks the exact config delta,
initramfs and watchdog helper, all FDT changes including phandle resolution,
thermal trips, and the compressed image span. The separate
[one-shot U-Boot audit](../../perrier-ramenv/cpu-m2-trial/uboot/oneshot-audit.json)
checks the factory environment, exact load files/ranges and watchdog proof.
Stock firmware lists its 350 MHz OPP but disables it. The ram112 clock-only
candidate was subsequently tested in RAM on 2026-11-13; see the
[validation record](../validation-cpu-m2-trial.json).

The [live test script](test_cpu_m2_live.py) verifies the policy, watchdog,
CPU1 state and temperature before any change. It requests 350 MHz for about
seven seconds, records CPU and parent clock readback, thermal and all INA
voltage channels, then restores 700 MHz and the performance governor even
if an ordinary command fails. The host U-Boot runner maintains the watchdog
lease and returns to stock. The first test did not activate an automatic
governor, change voltage, or reset the display.

The single-core idle and load tests passed: `dpll_mpu_m2_ck` and MPUSS
followed 700 → 350 → 700 MHz, while the parent DPLL stayed at 700 MHz.
At one CPU-bound worker, the likely MPU INA channel read 600 mA at 700 MHz
and 316 mA at 350 MHz; its voltage remained about 1.20 V. Temperature stayed
below 62 °C. The 350 MHz two-core, ten-second load also passed with CPU1
online. These are short samples, not sustained stability or whole-device
power measurements.

The two-core test's cleanup then took CPU1 offline and hit a NULL pointer in
`omap4_hotplug_cpu()` because this RAM policy skips the late OMAP4 PM init
that fills CPU1's power-domain pointer. The kernel rebooted into stock;
the factory p8 hash and ADC postflight matched. This is a **CPU hotplug
failure**, not evidence of a failed 350 MHz transition. Until selective PM
initialization is reviewed, future CPUfreq images should boot both cores and
disable runtime CPU hotplug. They should leave CPU1 online throughout the
test. The ram112 runner's overall status remains failed, reflecting this
panic, even though its bounded frequency checks passed.

The [ram113 image](../../perrier-ramenv/cpu-m2-smp-safe/reviewed-image.json)
was built and independently audited. It keeps the identical CPU OPP
and DTB, boots both CPUs, disables `CONFIG_HOTPLUG_CPU`, and makes mainline
`schedutil` available while retaining performance as the startup governor.
Its [bounded test](test_cpu_m2_smp_safe.py) never writes CPU online state;
it measures a two-core fixed 350 MHz load followed by idle/load `schedutil`
behavior, then restores 700 MHz. The owner-approved [live run](../validation-cpu-m2-smp-safe.json)
passed: 20 seconds of two-core fixed 350 MHz load, a 60-second idle window
with `schedutil` spending 96.9% of measured time at 350 MHz, and another
60 seconds of two-core fixed 350 MHz load with peak CPU temperature 59.2 °C.
`schedutil` selected 700 MHz under two-core load. No voltage was commanded
and the likely MPU INA channel stayed about 1.20 V. The exact factory p8
hash, stock app and ADC postflight were verified after normal recovery.
Ram113 is a validated **clock-only RAM test**, not yet the canonical image.

## Voltage control path

1. The [read-only stock/RAM VC/VP comparison](../../../evidence/perrier-omap-prm-ram113-2026-11-13.md)
   is complete. Ram113 retains Cisco's address map and MPU/CORE ON commands,
   but all VPs are disabled and hold MLO-era selectors; stock enables VP and
   requests lower voltage. At 350 MHz, the RAM MPU VP selector stayed
   `0x29` and the likely rail stayed near 1.20 V. The [late-init write
   audit](pm-late-init-audit.md) shows that pristine mainline would program
   incorrect CORE/IVA addresses, a 1.375 V ON command, and different VP
   limits. Its PM late init stays blacklisted until that entire sequence is
   board correct.
2. Expose a real CPU voltage provider through the OMAP VC/VP to TWL6032
   SMPS1 (`0x12`, voltage register `0x55`, command register `0x56`). The
   ordinary TWL6032 control-I2C client at `0x48` returned zero for these
   offsets; the retired ram111 observer is not suitable. Preserve or
   explicitly replace stock VP/SmartReflex ownership so two controllers
   cannot command the rail independently. Keep CORE and IVA out of the CPU
   regulator interface. Mainline's OMAP `voltdm_scale()` is internal to
   `arch/arm/mach-omap2/voltage.c`, and `omap_voltage_late_init()` programs
   all three domains; neither currently supplies a CPU regulator to
   `cpufreq-dt`. A small integration layer and a safe, selective PM init
   will likely be needed. The OMAP4460 TRM and Cisco MLO say VC bypass
   `VALID=1` means pending and `0` means completion; mainline's current
   `omap_vc_bypass_scale()` poll checks the opposite condition. Resolve that
   before using it for a Perrier regulator.
3. At **fixed 700 MHz**, the owner-approved [one-step VC bypass
   test](omap4-mpu-bypass-step.md) passed in two separate RAM boots, once
   idle and once with both CPUs loaded. Selector `0x28` gave a measured
   8–16 mV drop from the same-selector `0x29` reading and a return to the
   original reading after restoration. Each command completed with bypass
   ACK and no VC error bits. Temperature stayed below 63 °C and both
   factory recoveries passed. The low-voltage dwell was 0.5 seconds, so
   this establishes transport and immediate behavior, not sustained
   undervolt stability. Do not infer a safe fixed value solely from
   stock's adaptive ~0.99 V reading.
4. The isolated [ram114 image](../../perrier-ramenv/cpu-dvfs-trial/reviewed-image.json)
   now connects mainline `cpufreq-dt` and OPP ordering to a small Perrier VC
   bypass regulator. Its [DT overlay](omap4-cisco-perrier-cpu-dvfs-ram.dts)
   provides only 350 MHz at nominal 1,202,740 µV and 700 MHz at nominal
   1,215,400 µV. The provider validates inherited Cisco VC/VP state, changes
   only SMPS1 selector `0x28`/`0x29`, polls for VALID to clear, and checks
   bypass ACK/error bits. No generic OMAP PM late init or SmartReflex is
   enabled. The [bounded fixed-rate test](../validation-cpu-dvfs-trial.json)
   passed 700 → 350 → 700 MHz, including 20 seconds of two-core load at
   350 MHz. INA channel 1 moved about 1.208 → 1.200 → 1.216 V, consistent
   with the selector changes; peak CPU temperature was 58.638 °C.
   A separate guarded 300-second two-core 350 MHz load subsequently passed:
   31 ten-second checks stayed at the lower setting, the likely MPU rail
   read 1.200–1.208 V, peak CPU temperature was 59.716 °C, and the nowayout
   watchdog recorded 68 pings. The test restored 700 MHz before recovery.

   A separate `schedutil` run sampled the policy clock, the hardware clock
   getter, regulator state and VC register at 100 ms intervals. In two
   20-second idle windows, the hardware clock and low selector agreed in
   187/200 and 185/200 samples. Under 20 seconds of two-core load, all
   200 samples showed 700 MHz with the high selector. No sample showed
   hardware 700 MHz bracketed by a stable low VC selector. Some policy,
   regulator and VC fields disagree for one sample near transitions because
   those reads are sequential. Mainline `scaling_cur_freq` reports the
   policy's cached value for this driver; `cpuinfo_cur_freq` calls the
   clock getter. Mainline OPP raises voltage before clock and lowers clock
   before voltage. The first script's strict sequential-read assertion was
   therefore a measurement error, not a failed hardware test. All four
   ram114 sessions returned to stock with exact p8 and ADC postflight.

   The voltage step was deliberately small. It qualified bounded dynamic
   350/700 MHz operation, before the separate lower-voltage experiment.
5. The [ram115 lower-voltage image](../../perrier-ramenv/cpu-dvfs-low-trial/reviewed-image.json)
   changes only the 350 MHz OPP and MPU VC selector to nominal 1,101,460 µV
   (`0x20`); 700 MHz retains 1,215,400 µV (`0x29`). Short, fixed-350 MHz
   probes of `0x24` and `0x20` both returned ACK without VC error and
   restored the high setting. The subsequent [ram115 validation](../validation-cpu-dvfs-low-trial.json)
   passed a 20-second two-core transition and a five-minute two-core hold.
   During the hold, the likely MPU INA channel read 1.096–1.104 V, the CPU
   peaked at 59.716 °C, and the nowayout watchdog kept feeding. The paired
   dynamic sampler saw 181/200 and 184/200 stable low-selector samples in
   its idle windows and 200/200 stable high-selector samples under load. It
   saw no hardware 700 MHz sample bracketed by a stable low VC selector.

   A 96-sample idle/load comparison at each frequency showed that changing
   the 350 MHz point from nominal 1.20274 V to 1.10146 V reduced the likely
   MPU rail's average power from 240.27 to 187.86 mW at idle (21.8%) and
   from 405.75 to 313.81 mW under two-core load (22.7%). The monitored
   5 V channel changed from 5.568 to 5.503 W at idle and 5.701 to 5.627 W
   under load, about 1.2–1.3%. These are separate RAM boots, so the
   comparison includes ambient and workload variation; the 5 V channel is
   not proven to be whole-device input. Do not sum nested rail readings.
   For an identical 300-second interval, the measured mean-power difference
   corresponds to roughly 15.7 J idle or 27.6 J loaded on the likely MPU
   rail. This is calculated from mean power, not directly integrated energy
   or energy for a fixed amount of work.

   The [ram116 intermediate image](../../perrier-ramenv/cpu-dvfs-mid-trial/reviewed-image.json)
   repeated the mainline OPP/regulator route with 350 MHz at nominal
   1,152,100 µV (`0x24`) and the same 700 MHz high point. Its 20-second
   loaded transition passed and stock recovery matched the factory p8.
   The same 96-sample power protocol put the likely MPU rail between the
   other points: 213.12 mW idle and 357.70 mW loaded. The monitored 5 V
   channel read 5.536 W idle and 5.662 W loaded. The full [three-point
   curve](../validation-cpu-dvfs-voltage-curve.json) and [ram116 record](../validation-cpu-dvfs-mid-trial.json)
   retain the individual runs, reductions and limits. Ram116 had no
   five-minute hold or dynamic sampler; only ram115 completed those checks.

   Both ram115 boots returned to healthy stock with exact factory p8 and
   ADC postflight. Five minutes does not qualify overnight stability or
   worst-case temperature. The likely MPU INA assignment remains software
   evidence without PCB net confirmation. Keep this voltage in RAM tests
   while reviewing failure rollback, selective PM/AVS and full power policy.
   Keep the canonical boot image at its existing fixed policy.
6. Treat 920 MHz and 1.2 GHz as separate work. They need higher validated
   voltage, OMAP4460 MPU clock-child behavior, ABB handling and DPLL erratum
   review. They are absent from ram112 and should remain absent until those
   pieces are qualified.

This plan keeps voltage and frequency experiments recoverable in RAM. The
owner has authorized CPU hardware tests, including the bounded live VC test
above. No persistent voltage policy has been installed.
