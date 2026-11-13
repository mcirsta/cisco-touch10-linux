# CPU1 handoff comparison before a U-Boot RAM trial

The stock CE9.9.0 kernel's `smp_init_cpus` is at `0xc071d8e4`. Its
`platform_smp_prepare_cpus` at `0xc071d9bc` enables the Cortex-A9 SCU,
selects `omap_secondary_startup_4460` at `0xc04b7938` for the OMAP4460,
publishes that secondary address and issues barriers and `SEV`. The stock
`boot_secondary` at `0xc04b7794` also handles the `mpu1_clkdm` and CPU1
power state on a secondary wake. The selected secondary startup calls `SMC`
before entering the generic secondary kernel entry. These observations come
from the saved stock kernel image and matching kallsyms, not a live CPU1
experiment.

Linux 6.18.48 already contains an OMAP4460 configuration in
`arch/arm/mach-omap2/omap-smp.c`. It selects
`omap4460_secondary_startup`, prepares the SCU, publishes the secondary
address through the secure API when available, and handles CPU1 clock and
power domains in `omap4_boot_secondary`. The upstream code checks whether
CPU1 is parked before overwriting its startup address. Earlier kexec trials
logged `smp: CPU1 not parked?`, so the old handoff state may differ from a
fresh U-Boot boot. That message alone does not explain the initramfs parser
failure: the `nosmp` kexec trial skipped OMAP CPU1 preparation and still
failed during archive unpack.

The first U-Boot isolation candidate is therefore an SMP-built kernel with
`nosmp` and the validated ram107 DTB, where CPU1 remains disabled. This
tests the SMP build's archive and cold handoff without releasing CPU1 or
changing frequency/voltage policy. A successful result would support a
separate CPU1-enabled DT trial; it would not itself qualify dual-core
operation. The current watchdog starts at kernel driver probe, so a failure
before that point can still require a physical power cycle. Keep the exact
factory p8 restore and known-good ram104/ram100 staged fallbacks.
