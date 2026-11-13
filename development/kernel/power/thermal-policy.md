# Perrier thermal and CPU operating envelope

## Current, validated state

The ram110 kernel runs both Cortex-A9 cores with CPUfreq and OMAP power AVS
disabled. Its OMAP PM late init is blacklisted. Cisco MLO sets the MPU and
CORE rails before Linux, and this kernel does not request a voltage change.
The saved ram110 INA3221 samples are 1.208 V on likely MPU channel 1 and
1.128 V on likely CORE channel 3. These agree with MLO's nominal 1.203 V
and 1.127 V commands. The channel identification is strong software
evidence, not a physical board-net measurement.

Stock Linux reports a 700 MHz CPU setting. The thermal-policy RAM run later
read 700 MHz directly from mainline's clock tree. The longer ram110 load run
reached at most 60.255 °C and returned to 55.672 °C. This is a six-minute
observation, not a continuous-load qualification.

The inherited OMAP4460 OPP table lists 350 MHz at 1.025 V, 700 MHz at
1.200 V and 920 MHz at 1.313 V. The fixed MLO MPU rail agrees with the
700 MHz nominal OPP. An increase to 920 MHz on that rail is prohibited by
the current board policy. The stock kernel marks its 350 MHz point
unavailable, and the [clock-path audit](cpufreq-clock-audit.md) found that
mainline `cpufreq-dt` would target the PLL instead of the MPUSS output
divider. TI's OMAP4460 erratum i700 also makes the 1.2 GHz
and 1.5 GHz DPLL transitions a separate problem. Neither 920 MHz nor
1.2 GHz is enabled in the current RAM image.

TI specifies 110 °C as the OMAP4460 maximum *functional* junction
temperature and cautions against continuous operation there. The common
OMAP4 device tree's 125 °C critical trip exceeds that limit. The
board-specific candidate moves the passive trip to 85 °C and the critical
trip to 95 °C. With CPUfreq disabled, the passive trip has no cooling map:
it indicates low headroom, while the critical trip requests shutdown. The
SoC's hardware TSHUT threshold remains unchanged as a last-resort backstop.
The kernel's emergency poweroff delay is currently zero, so a blocked
orderly shutdown can rely on the already qualified nowayout watchdog for
eventual reset. A later kernel change should add a short forced-poweroff
delay and test it separately.

## Audited RAM candidate

The [thermal DTS](omap4-cisco-perrier-thermal-ram.dts) reuses the exact
ram110 zImage and initramfs. Its [offline audit](out/review.json) compares
the compiled FDT with frozen ram110 and permits **only** the two thermal
temperature property changes. The dedicated `thermal-policy` U-Boot profile
also verifies the source, baseline, config guards, FDT diff, seeded DTB,
load ranges, factory boot command and watchdog proof before any device
connection. The one-shot environment and candidate files are prepared
locally in `development/perrier-ramenv/thermal-policy/uboot/`.

The owner authorized one U-Boot RAM boot under the existing recovery scope.
The [run record](../validation-thermal-policy.json) shows that it staged a
hash-named zImage and DTB on p14, armed the standard one-use p8 environment,
restored the factory `bootcmd` in U-Boot before Linux, and returned to stock
by watchdog-controlled reboot. Mainline's debug clock tree read 700 MHz.
The CPU trip sysfs read 85/95 °C. Both CPUs stayed online, a bounded
45-second load peaked at 61.873 °C, and INA channels 1 and 3 stayed at
1.208/1.128 V in every sample. The load would have stopped at 80 °C or on
an unexpected rail value. The Linux nowayout watchdog kept feeding. Qt
started once with no display cycle. Stock Linux and Phoenix returned in
36.7 seconds; exact factory p8 and the approved ADC postflight passed.

This test made no intentional CPU frequency or PMIC voltage change. It did
not exercise the trips, a voltage transition, or a long thermal soak. The
offline profile's `live_tested=false` flag records the status at artifact
creation; the separate run record is the live validation. Both trip values
are now in the canonical Perrier board DTS. Rebuilding the comparison DTB
after that source change produced the same SHA-256
`9119d90b8595cddd74ff1e741103c5eb49aab22f2765c7ad223d20f27ee73e01`
as the DTB used for the successful RAM boot. The source patch series applies
cleanly to pristine Linux 6.18.48; no new device boot was needed for this
source consolidation. A separate compile of the canonical board source with
CPU1 enabled and **without** the temporary thermal overlay was byte-identical
to that validated DTB.

## Route to adaptive voltage and frequency

1. Use the [31-word stock VC/VP snapshot](../../../evidence/perrier-omap-prm-power-stock-2026-11-13.md)
   as the reference for any future RAM image. It confirmed Cisco's PMIC
   addresses and found the active stock MPU/CORE requests close to the INA
   readings. Ram113 has now captured the same words at 700 and 350 MHz;
   its VPs remained disabled with MLO-era fixed selectors. See the
   [comparison](../../../evidence/perrier-omap-prm-ram113-2026-11-13.md).
2. Make the Perrier/TWL6032 voltage-register mapping explicit in the OMAP
   PM code: MPU `0x55/0x56`, CORE `0x5b/0x5c`, IVA `0x49/0x4a` on VC slave
   `0x12`. Pristine mainline has the latter two wrong for this unit. Its
   generic ON/RET commands and VP initialization also differ from stock,
   so review all of those writes before removing the PM late-init blacklist.
3. Provide a real MPU voltage control path and a CPU OPP policy that rejects
   unsupported rate/voltage pairs. Validate a single fixed rate first. Any
   undervolt must be a measured, reversible experiment at that fixed rate,
   with load, thermal and watchdog checks. Lower idle power is useful only
   after stability is established across cold boot and sustained load.
4. The isolated [ram112 clock-only trial](dvfs-plan.md) demonstrated short
   350/700 MHz M2-divider transitions at fixed voltage, then exposed a
   separate CPU1 hotplug failure in its cleanup. The audited ram113 image
   boots both cores with hotplug disabled and passed bounded two-core
   350 MHz load and `schedutil` tests; see the
   [validation record](../validation-cpu-m2-smp-safe.json). Enable
   dynamic CPUfreq in the canonical image
   only after the voltage controller, OPP/ABB behavior and transition
   ordering are demonstrated. Keep 1.2 GHz disabled until the DPLL erratum
   workaround is independently checked.

Primary references: [TI OMAP4460 data manual](https://www.ti.com/pdfs/wtbu/OMAP4460_ES1.x_DM_Public_Book_V_A.pdf),
[TI OMAP4460 silicon errata](https://www.ti.com/pdfs/wtbu/OMAP4460_ES1.x_Silicon_Errata_Rev_H.pdf),
and the local Linux 6.18.48 `omap4460.dtsi`, `omap_twl.c`, `vc.c`, and `vp.c`.
