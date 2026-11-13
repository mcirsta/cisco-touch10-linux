# CPU frequency and voltage boundary

The stock Linux 3.4 kernel runs the MPU at 700 MHz with the `userspace`
governor and exposes 700, 920 and 1200 MHz. Its driver is `omap2plus`.
The regulator class lists LDOUSB, VANA, 32 kHz clocks, SYSEN and REGEN1,
but no MPU `vcc` regulator. The saved stock image's `omap4_opp_init` enables
the 1.2 GHz MPU OPP for this SoC variant. These are reference observations;
the owner separately authorized bounded CPU hardware tests.

Mainline 6.18.48's `omap4460.dtsi` supplies 350/700/920 MHz OPP entries
at 1.025/1.2/1.313 V. With `CONFIG_CPUFREQ_DT=y`, OMAP4 is on the
`cpufreq-dt` platform allowlist and that driver is created. The older
`omap-cpufreq` driver is still in the source but lacks its platform device
and `cpufreq_ck` alias on this OMAP4 DT path. With no `cpu-supply` in the Perrier
DT, the OPP layer has no regulator to change and still calls `clk_set_rate()`.
Mainline's TWL6032 driver does not expose the SMPS1/VCORE1 rail. The stock
kernel advertises 700/920/1200 MHz and marks its 350 MHz OPP unavailable.
Enabling CPUfreq as-is could therefore raise the clock without matching
voltage, or attempt an unqualified 350 MHz clock transition. Mainline also
points the CPU at `dpll_mpu_ck` while the actual MPUSS clock parent is
`dpll_mpu_m2_ck`; the [clock-path audit](power/cpufreq-clock-audit.md)
records how `cpufreq-dt` can be reused with a candidate-only M2 clock
phandle and 350/700 OPP list. Keep `CONFIG_CPU_FREQ` off in the canonical
board image until SMPS1/VC coordination, the clock path and exact stock
OPP/ABB behavior are implemented and reviewed. An isolated
[ram112 clock-only image](power/dvfs-plan.md) enabled CPUfreq with no
CPU voltage provider and no rates above 700 MHz for a bounded RAM test.
Its 700 → 350 → 700 MHz divider transitions passed, including a short
two-core 350 MHz load; the test's CPU1 offline cleanup then panicked because
OMAP4 PM init was skipped. Stock recovered. The separately audited ram113
candidate boots both cores with runtime CPU hotplug disabled. It passed
bounded two-core 350 MHz load and `schedutil` idle/load tests, then recovered
stock with the factory p8 hash intact. Neither image changes voltage.
The newer [ram114 validation](validation-cpu-dvfs-trial.json) covers a bounded
350/700 MHz dynamic clock and two-selector voltage trial with `schedutil`.
Its idle/load hardware samples and recovery passed; the small voltage step,
runtime PM integration and long-term power policy remain separate work. The
canonical board DTS still deletes inherited OPPs.

Evidence: stock `scaling_available_frequencies`, `scaling_cur_freq` and
`scaling_driver` were read over key-only SSH on 2026-11-12; stock regulators
were compared with `evidence/perrier-stock-display-supplies-2026-11-10.txt`.
The stock image decompilation was checked at `0xc071e994` (`omap4_opp_init`).
The mainline code and OPP table are in the local Linux 6.18.48 source tree.
That early stock audit made no change; subsequent ram112–ram114 CPU tests
used one-shot U-Boot RAM boots with exact factory recovery.

## Perrier supply identification

The [exact CE9.9.0 MLO and stock-kernel trace](../../evidence/perrier-mpu-rail-trace-2026-11-12.md)
identifies **TWL6032 SMPS1/VCORE1** as the intended software-controlled
`mpu` supply. Cisco MLO's OMAP4460 ES1.1 branch writes PMIC slave `0x12`,
register `0x55`, selector `0x28`. Its nominal voltage is 1.203 V only if
the SMPS1 EPROM offset bit is set; otherwise it is 1.101 V. The stock kernel's
`omap_twl4030_init` registers `mpu` with the same slave and voltage/command
registers `0x55`/`0x56`. Its `core` and `iva` entries likewise match the
MLO's TWL6032 SMPS2 and SMPS5 writes. Stock boot logging shows VCORE1 and
VCORE2 setup. The live unit identifies TWL6032 at I2C1 address `0x48`.

The saved kernel also builds `CONFIG_OMAP_TPS6236X=y`, but static inspection
found no direct call or data reference to `omap_tps6236x_board_setup`.
Bundled U-Boot contains TI's generic OMAP4460 TPS62361 table, whose PMIC
address field is `0x12` even though the TPS62361B datasheet specifies
`0x60`. Neither a compiled helper nor this generic table establishes a
Perrier TPS device. The stock I2C client list and regulator class cannot
exclude an unregistered or voltage-controller-managed device. The matching
MLO/kernel TWL mapping is the stronger board-specific evidence. Physical
copper routing remains unmeasured; do not mistake the 1.216 V reading on an
unlabeled INA3221 channel for a confirmed VDD_MPU probe.

## Mainline gap and safe policy

The unmodified Linux 6.18.48 TWL6032 regulator driver and binding expose
SMPS3/SMPS4/VIO, but no SMPS1/SMPS2/SMPS5 provider. Its older
`ti,twl6030-vdd1` voltage callbacks return `-ENODEV`. The earlier ram111
candidate attempted a read-only SMPS1 regulator observer, but the
[stock PMIC read](../../evidence/perrier-smps-selector-stock-2026-11-13.md)
showed that its control-I2C path does not expose a valid programmed
SmartReflex selector. Ram111 was retired before any device boot; its source
and DT changes are absent from the active patch series. See the
[ram111 record](smps1-observe.md). Ram110 remains the validated fallback.
No CPU `vcc-supply` phandle or CPUfreq is enabled.

The earlier [fixed-frequency arithmetic test](../../evidence/perrier-ina-arithmetic-2026-11-12.md)
showed that INA channel 1 rose +120 mA with one CPU worker and +190 mA
with two. Nominal [stock OPP voltages](../../evidence/perrier-stock-opp-2026-11-12.md)
initially made channel 2 look like MPU, but those OPP entries are nominal
targets, not the running voltage. The one-time fixed-register stock read
returned `0x5b` for the offset EPROM and zero at all three control-I2C
voltage offsets. The exact Cisco MLO and kernel use PMIC slave `0x12` for
the OMAP voltage controller, while that read used general I2C `0x48`;
the zero bytes cannot establish programmed voltages. TI documents two I2C
interfaces for TWL6032, one dedicated to SmartReflex.

The subsequent [stock OMAP VP snapshot](../../evidence/perrier-omap-vp-stock-2026-11-13.md)
read the voltage processor's current requested selectors: MPU `0x18`
(1.00018 V) and CORE `0x16` (0.97486 V), closely matching INA channels 1
and 3 at 1.000 and 0.976 V. `VPENABLE=1`, with a distinct MPU initial/ON
selector `0x29` (1.2154 V). Stock SmartReflex Class3 is built and logged.
The already saved ram110 peripheral log supplies an independent boot-path
comparison: with power AVS off and `omap2_common_pm_late_init` blacklisted,
INA channels 1–3 read 1.208, 1.216 and 1.128 V. Channels 1 and 3 match
MLO's SMPS1/SMPS2 settings of 1.20274 and 1.12678 V, while channel 2
stays at 1.216 V. Together with stock VP values and CPU-load response,
this gives high confidence that channel 1 monitors MPU and channel 3
monitors CORE; channel 2's identity remains unresolved. VP values are
software requests, and no PCB net was electrically measured. The validated
ram110 kernel uses higher fixed MPU/CORE settings and does not implement
stock adaptive voltage behavior. Ram114 tests only two close SMPS1 selectors
with generic OMAP PM late init disabled. Broader DVFS still needs stock
OPP/ABB and mainline OMAP VC/SmartReflex coordination. Keep CPUfreq and VSEL
writes disabled in the canonical image; the bounded RAM candidates are the
documented exceptions.

## Upstream voltage address mismatch

The pristine Linux 6.18.48 `arch/arm/mach-omap2/omap_twl.c` hardcodes the
following OMAP4 voltage-controller PMIC addresses. Cisco's exact MLO and
stock Linux image use the second column. Both use slave `0x12`.

| Voltage domain | Linux 6.18.48 voltage/command | Cisco stock voltage/command |
| --- | --- | --- |
| MPU | `0x55` / `0x56` | `0x55` / `0x56` |
| CORE | `0x61` / `0x62` | `0x5b` / `0x5c` |
| IVA | `0x5b` / `0x5c` | `0x49` / `0x4a` |

This is a board-specific mismatch, separate from the failed control-I2C
observer. `omap2_common_pm_late_init()` calls `omap4_twl_init()` and then
`omap_voltage_late_init()`. The latter calls `omap_vc_init_channel()`,
which programs the OMAP voltage controller's PMIC register addresses and
command values; it also calls `omap_vp_init()`, which writes voltage
processor configuration. Removing the RAM image's initcall blacklist would
therefore configure CORE and IVA for the wrong PMIC registers on this
board, even with CPUfreq disabled. The validated ram110 config retains
`initcall_blacklist=omap2_common_pm_late_init`, has
`CONFIG_POWER_AVS_OMAP` and `CONFIG_CPU_FREQ` off, and performs no kernel
voltage transition. Preserve those guards until the mapping is corrected
and the entire initialization sequence is reviewed.

TI's OMAP4 U-Boot source independently labels TWL6032's SMPS1, SMPS2 and
SMPS5 voltage registers as `0x55`, `0x5b` and `0x49` respectively, matching
Cisco's exact MLO and stock-kernel assignments. The source is in TI's
[register definitions](https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/include/asm/arch-omap4/clock.h?id=e79de74103d9d411aa6b4e63582c5d7075c6a7a8)
and [OMAP4 rail table](https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/mach-omap2/omap4/hw_data.c?id=e79de74103d9d411aa6b4e63582c5d7075c6a7a8).
An [isolated Linux patch](power/patches/0001-omap4-twl6032-vc-addresses.patch)
now selects that map for an available `ti,twl6032` DT node. Its
[offline review](power/patches/review.json) passed exact patch application.
It remains outside the active patch series and has not enabled PM init.
The deeper [late-init audit](power/pm-late-init-audit.md) found a second
blocker: pristine OMAP4 command defaults use a 1.375 V ON target for all
three domains, unlike stock's captured 1.215 V MPU ON setting, and
`omap_vp_init()` would clear the stock VP enable bit. Correcting only the
register addresses is insufficient. The PM late-init blacklist remains a
required safety boundary.

The later [31-register stock snapshot](../../evidence/perrier-omap-prm-power-stock-2026-11-13.md)
confirmed all three exact VC mappings and command words, plus the enabled
VP state and limits. Its live MPU and CORE voltage requests were about
0.988 and 0.962 V; subsequent INA channels 1 and 3 measured 0.992 and
0.960 V at the stock 700 MHz CPU clock. These close readings strengthen
the software rail identification, while remaining separate from a physical
board-net measurement. The one-time helper was removed; stock Linux and
Phoenix kept running with the same boot ID.

## Staged power work

The concrete [thermal and CPU operating envelope](power/thermal-policy.md)
records the audited 85/95 °C DT-only RAM candidate, the six-minute ram110
load baseline, its successful single U-Boot RAM boot and bounded 45-second
dual-core test, and the gates for voltage and frequency scaling. The live
clock tree confirmed 700 MHz; INA channels 1 and 3 remained at 1.208/1.128 V
through that load. See the [validation record](validation-thermal-policy.json).

1. Use the captured stock VC/VP snapshot as the reference when separating
   passive OMAP PM registration from hardware programming. Do not infer rail
   voltage from PMIC control-I2C `0x48` selector offsets.
2. Correct the TWL6032 CORE and IVA VC addresses, command values and VP
   policy before enabling any upstream OMAP PM late init. Its generic CORE
   and IVA ON targets exceed its own VP maxima; the address patch alone
   remains outside the booted kernel.
3. The isolated ram112/ram113 350/700 MHz clock trials and the ram114
   two-selector voltage trial passed bounded RAM tests. The latter used
   mainline `cpufreq-dt`/OPP ordering and a board-specific VC bypass
   regulator; [the detailed plan and evidence](power/dvfs-plan.md) record
   idle/load sampling and the limits of this result. Review Cisco's exact
   OPP/ABB and stock SmartReflex Class3 behavior before extending the
   voltage range, adding a thermal cooling map, or installing a persistent
   policy. Keep watchdog recovery and INA/VC observation in later tests.

The owner authorized CPU hardware tests. Recovery selectors, other rails,
and persistent firmware changes remain outside that scope.
