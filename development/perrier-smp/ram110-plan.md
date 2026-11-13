# Ram110 boot-time CPU1 trial

Ram110 inherits validated ram109, including its CPU1-enabled DTB, mainline
watchdog, RAM SSH, Qt application, read-only eMMC policy, fixed CPU clock and
unchanged PMIC policy. Its offline audit permits only three kernel-config
changes: the version label, built-in initramfs path, and removal of
`maxcpus=1` from the forced command line. The rootfs changes only its boot
marker from ram109 to ram110. No driver, DT node, clock, OPP or voltage
setting changes. See `reviewed-image.json` under `smp-boot-two`.

The one-shot U-Boot candidate is SHA256
`34b607194bd68f7bb29f16002276e54dec6f5a962c850e6e8ae04c1f57571889`.
It changes only `bootcmd`, saves the factory path before loading a
hash-verified zImage and DTB into RAM, and then hands off. Its independent
environment and memory-range audit passed. The current factory p8 hash is
`f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.

One bounded trial:

1. Check healthy stock Linux/Phoenix, exact factory p8, direct Ethernet,
   serial capture and sufficient p14 space. Stage only the audited ram110
   zImage and seeded DTB, verify readback, and arm the one-use environment.
2. Software-reboot once. Serial should show two processors activated before
   `/init`. Confirm RAM SSH, `online=0-1`, nowayout WDT2 feeding, eMMC
   read-only and unmounted, and one Qt start. Do not cycle the display.
3. Observe for at least 30 seconds, including a CPU1-pinned read, CPU1
   scheduler/timer activity, temperature and watchdog pings. Do not alter
   clocks or voltages.
4. Request stock reboot. Verify Phoenix, exact factory p8, and the already
   approved ADC postflight. If the kernel panics, `panic=5` should restore
   stock. If it hangs after watchdog startup, stop lease renewal and allow
   WDT2 to reset it. A hang before watchdog probe may require one physical
   power cycle. Do not repeat an unchanged failure.

This trial does not change installed firmware or qualify long-duration SMP,
DVFS or production power management.

## Result on 2026-11-12

The single trial passed. Serial reported CPU1 at 0.274 seconds and two CPUs
activated at 0.285 seconds; the image reached RAM SSH, Qt and the mainline
watchdog. Both CPUs remained online through a 25-second observation. A
CPU1-pinned read succeeded, CPU1 scheduler and timer counts advanced, and
watchdog pings rose from 9 to 14. eMMC stayed read-only and unmounted; no
display cycle or Qt restart was requested. Stock Linux and Phoenix returned
after 36.7 seconds with exact factory p8 and approved ADC postflight. See
the [validation record](../kernel/validation-ram110.json) and
[live observation](../runs/20261112T180058Z-uboot-ram110-b3b712/cpu1-observation.log).

P14 lacked room for another image. Only the hash-verified obsolete ram64
staged zImage was removed before this trial; ram104, ram108 and ram109 test
images remain staged.
