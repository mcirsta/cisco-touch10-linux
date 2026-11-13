# Ram108 U-Boot isolation test

Ram108 is a Linux 6.18.48 SMP build of validated ram107 with `nosmp` forced
on the kernel command line. Its DTB is byte-identical to ram107, including
`cpu@1` disabled. The initramfs differs only in the `ram108` release marker.
The 52 resulting Kconfig changes, including Tree RCU and SMP infrastructure,
are pinned in `../kernel/configs/smp-nosmp-config-delta.json`; CPUfreq,
regulator, remoteproc, CPU idle and suspend policy stay off. The stock
700 MHz clock/rail state is inherited. The source, archive, watchdog helper
and one-shot U-Boot environment pass offline audits.

The exact ram108 initramfs archive (SHA-256
`3a7eb87245b91ce9192afe36a13b7cef569cd3f91cd924b2892317901ef6e0d8`)
also passed a generic two-core Cortex-A9 QEMU boot. The separately built SMP
kernel reached `/bin/sh` with no archive parser error. This checks the archive
format, not the Perrier memory controller or early U-Boot handoff. See
[`qemu_ram108_probe.py`](qemu_ram108_probe.py) and
[`qemu-ram108-archive/result.json`](qemu-ram108-archive/result.json).

The purpose is to test an SMP-built kernel through the cold U-Boot handoff
without starting CPU1. Ram56 with `nosmp` failed during initramfs unpack
through **kexec**. The exact ram56 archive unpacked on generic two-CPU QEMU,
so the old failure may depend on the kexec/OMAP handoff. A ram108 U-Boot
success would narrow that cause; it would not prove CPU1 works.

For one live test:

1. Confirm stock Linux 3.4, Phoenix, exact factory p8, host link and serial
   capture. Keep the known-good ram104/ram100 staged files intact.
2. Stage only the audited ram108 zImage and seeded DTB. Write/read back the
   one-use p8 image; software reboot. U-Boot must save the factory path
   before loading the RAM kernel.
3. Verify the serial log contains `nosmp`, no initramfs parser error, kernel
   release `6.18.48-perrier-ram108`, and one CPU online. Check RAM SSH,
   feeding nowayout WDT2, read-only/unmounted eMMC and one Qt startup. Run
   no display blank/unblank cycle or Qt restart.
4. Request reboot to stock, verify exact factory p8 and approved ADC
   postflight. If the kernel panics, its `panic=5` should reboot. If it
   stalls before watchdog probe, one manual cold power cycle may be needed.
   Do not repeat an unchanged failure.

The owner was near the panel for the contingency. The single ram108 hardware
trial passed on 2026-11-12: U-Boot saved the factory command before handoff,
the SMP-built kernel reached `/init` with one CPU under `nosmp`, RAM SSH and
the mainline watchdog ran, Qt started once, and eMMC stayed read-only.
Requested reboot returned stock in 36.7 seconds with exact factory p8 and
approved ADC postflight. See
[`validation-ram108.json`](../kernel/validation-ram108.json) and the
[run record](../runs/20261112T170131Z-uboot-ram108-580977/result.json).
No physical power cycle was needed.

This pass is the gate for a separately audited CPU1-enabled DT trial. The
CPU1 trial must retain fixed frequency/voltage policy and establish a
pre-probe watchdog plan or an explicit recovery contingency.
