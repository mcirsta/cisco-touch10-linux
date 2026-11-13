# Perrier CPU frequency clock-path audit

The clock-path selection began as an offline audit and was tested in a
one-shot U-Boot RAM image on 2026-11-13. No PMIC voltage was commanded. The
fixed 700 MHz ram110 image remains the validated baseline; ram112 is an
experimental clock-only image with a CPU1 hotplug failure described below.

## What the two kernels expose

| Item | Stock CE9.9.0 Linux 3.4 | Local Linux 6.18.48 |
| --- | --- | --- |
| CPU clock/policy | `omap2plus`, `userspace`, `virt_dpll_mpu_ck` in the stock OPP table | `cpufreq-dt` would be created for `ti,omap4` if configured |
| Available OPPs | 700, 920, 1200 MHz; the 350 MHz stock table entry is disabled | SoC table supplies 350, 700, 920 MHz before Perrier override |
| CPU clock DT reference | Legacy platform clock and OMAP device scaling | CPU0 uses `dpll_mpu_ck`; MPUSS clock-control parent is `dpll_mpu_m2_ck` |
| Voltage control | OMAP VC/VP and SmartReflex Class3 active | No `cpu-supply`; PM late init blacklisted, AVS and CPUfreq off |

The live stock read on 2026-11-13 again reported `omap2plus`, governor
`userspace`, current frequency 700000 kHz and available frequencies
700000/920000/1200000 kHz. The exact saved stock kernel's OPP table records
350 MHz at 1.025 V with its default-enable bit clear; see
[`perrier-stock-opp-2026-11-12.md`](../../../evidence/perrier-stock-opp-2026-11-12.md).
The stock kallsyms identify `omap4460_mpu_dpll_set_rate` at `0xc0030cdc`
and `omap4460_mpu_dpll_update_children` at `0xc003021c`. IDA inspection of
the saved kernel confirms a special MPU DPLL path and child-clock update;
this is evidence of clock handling, not proof that stock ever selected the
disabled 350 MHz point. The saved child-update routine clears the same two
MPUSS clock-control bits for both 350 and 700 MHz; higher rates take other
branches. This narrows the expected 350/700 difference to the output
divider, but does not establish stability of a live transition.

In Linux 6.18.48, `drivers/cpufreq/cpufreq-dt-platdev.c` allowlists
`ti,omap4`. `drivers/cpufreq/cpufreq-dt.c` calls
`dev_pm_opp_set_rate()`. Without a CPU supply, the OPP layer calls the CPU
clock's `clk_set_rate()` without a regulator transition. The CPU0 phandle
in `omap4.dtsi` is `dpll_mpu_ck`, whose provider has the generic noncore
DPLL `set_rate` operation. The downstream `dpll_mpu_m2_ck` is a separate
divider, and the OMAP4 MPUSS clock-control parent is that divider. The M2
divider's driver can set its divisor directly; it is not selected by the
current CPU0 phandle. The isolated ram112 test changed that phandle and
confirmed a real divider-only transition on this board.

TI's OMAP4460 TRM, Table 3-88, gives the preferred 38.4 MHz SYS_CLK
settings for OPP100 (700.8 MHz) and OPP50 (350.4 MHz): the same 1401.6
MHz DPLL lock with M=73 and N=3, changing M2 from 1 to 2. The measured
RAM clock tree likewise showed `dpll_mpu_ck`, `dpll_mpu_m2_ck` and the
MPUSS consumer at 700 MHz, consistent with M2=1. This suggests a divider-based
transition is the appropriate path. The bounded ram112 result confirms the
clock path but is not a sustained board qualification for 350 MHz. TI
erratum i700 separately makes high-rate DPLL changes a
special case.

## Mainline reuse boundary

At fixed 700 MHz, the current upstream OMAP clock, ARM SMP, thermal and
watchdog drivers work with the rate and rails inherited from MLO. No
Touch 10 CPU clock driver is required. The RAM-only OMAP PM and clock
guards are separate boot-policy measures, not the long-term CPU design.

A bounded 350/700 MHz experiment now uses the existing `cpufreq-dt`,
OPP core and `ti,divider-clock` driver in the isolated
[ram112 image](dvfs-plan.md). It gives CPU0 a **candidate-only** clock phandle
to `dpll_mpu_m2_ck` and an OPP v2 table containing only 350 and 700 MHz.
No CPU supply or voltage values are present, so the MPU rail remains at its
inherited setting. The M2 divider has no
`ti,set-rate-parent` property, so its `set_rate` path changes the divisor
without requesting a new parent PLL rate. This behavior was measured during
the bounded live test; it does not justify enabling 350 MHz in the
production board DTS. Stock disables that OPP, and longer timer, SMP,
audio, display and watchdog testing remains necessary.

Dynamic voltage scaling or rates above 700 MHz can still reuse mainline
OPP, regulator and thermal-cooling frameworks, but require a real TWL6032
SMPS1/OMAP VC control path and the board's exact command, VP and ABB policy.
The generic OMAP PM late init currently writes different addresses and
voltages from stock; the [write audit](pm-late-init-audit.md) documents
that gap. Higher OPPs also need the OMAP4460 clock-child and DPLL erratum
behavior reviewed. A DTS-only 920 MHz entry would be unsafe.

## Fixed-rate board policy

The Perrier board `.dtsi` deletes the inherited OMAP4460
`operating-points`; the RAM wrapper no longer carries this rule alone.
`CONFIG_CPU_FREQ` and `CONFIG_POWER_AVS_OMAP` stay off, and
`omap2_common_pm_late_init` remains blacklisted. The 350/920 MHz SoC
entries, generic 1.375 V PM init command and unqualified PMIC address map
therefore cannot become an accidental CPU voltage/frequency policy.
Moving the OPP deletion changed no DTB bytes when old and new source
placements were compiled with the same OMAP4460 tree and RAM policy: both
SHA-256 digests were `626c00363df742326d6fcc59df1bd74ef3450e0fc4e479cc03e5578c7170a3df`.

The ram112 offline audit confirmed the M2 phandle, 350/700 OPP table,
unchanged thermal trips and watchdog recovery image. In the live idle and
single-core load tests, M2 and the MPUSS consumer followed 700 → 350 → 700
MHz, while the parent DPLL held 700 MHz. The likely MPU rail stayed near
1.20 V. One CPU-bound worker drew 600 mA at 700 MHz and 316 mA at 350 MHz
on the likely MPU INA channel; this snapshot does not establish whole-device
power saving. A ten-second two-core 350 MHz load also completed.

Immediately after that two-core load, the test cleanup tried to offline
CPU1 and panicked in `pwrdm_get_valid_lp_state()` through
`omap4_hotplug_cpu()`. The RAM boot intentionally skips
`omap2_common_pm_late_init()`, and therefore never calls `omap4_mpuss_init()`
to populate CPU1's power-domain pointer. Stock boot recovered with the exact
factory p8 hash and ADC postflight. The [validation record](../validation-cpu-m2-trial.json)
separates the clock result from the hotplug failure. Avoid
`cpu1/online=0` in this RAM policy until selective PM init is audited.

Ram113 then passed a [one-shot RAM run](../validation-cpu-m2-smp-safe.json)
with both CPUs online and runtime hotplug disabled. Two-core fixed 350 MHz
load ran for 20 seconds and then 60 seconds; the longer window peaked at
59.2 °C. With mainline `schedutil`, a 60-second idle window spent 96.9% of
measured time at 350 MHz, and a two-core load selected 700 MHz. The rail
remained near 1.20 V because no voltage provider is connected. Stock
recovery, factory p8 readback and ADC postflight all passed. This validates
dynamic **clock** scaling in a bounded RAM test, not dynamic voltage scaling.

Keep higher OPPs disabled until a qualified voltage provider,
rate/voltage ordering and stock-specific clock handling are available.

Primary hardware references: [TI OMAP4460 TRM](https://www.ti.com/pdfs/wtbu/OMAP4460_ES1.x_DM_Public_Book_V_A.pdf)
and [TI OMAP4460 silicon errata](https://www.ti.com/pdfs/wtbu/OMAP4460_ES1.x_Silicon_Errata_Rev_H.pdf).
