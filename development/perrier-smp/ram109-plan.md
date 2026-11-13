# Ram109 CPU1 hotplug trial

Ram109 carries validated ram108's application, drivers, watchdog and network
setup. It adds `CONFIG_HOTPLUG_CPU`, changes the forced command line from
`nosmp` to `maxcpus=1`, and changes only `/cpus/cpu@1/status` from
`disabled` to `okay` in the test DTB. CPU frequency, OPP and voltage policy
remain disabled; the stock-inherited 700 MHz MPU rail/clock setup is left
unchanged.
The exact Kconfig and DTB differences must pass offline audit.

`maxcpus=1` lets the ARM/OMAP SMP preparation run, but leaves CPU1 offline
during boot. After `/init`, RAM SSH and the nowayout WDT2 feeder are ready,
one write of `1` to `/sys/devices/system/cpu/cpu1/online` will request CPU1
startup. This separates early SMP preparation from the CPU1 release and
keeps the release inside the already proven watchdog recovery window.
Mainline `smp_prepare_cpus(1)` still enables the SCU, programs the CPU1
startup address and may reset a stale parked CPU1 before watchdog probe.
The later `omap4_boot_secondary()` sets the CPU1 release state and requests
its clock/power domain; ARM waits up to one second for the core to report
online. These paths do not program an MPU voltage or change its OPP, but an
early preparation hang remains possible.

For one hardware trial:

1. Recheck healthy stock Linux/Phoenix, exact factory p8, direct Ethernet
   and the prepared one-shot image. Stage only audited ram109 files, capture
   serial, and use one software reboot.
2. Before hotplug, confirm `maxcpus=1`, CPU1 present but offline, one CPU
   online, RAM SSH, a feeding 120-second nowayout watchdog, eMMC read-only
   and unmounted, and one Qt startup. Do not cycle the display or restart Qt.
3. Request CPU1 online once. Observe the command result, serial log,
   `/sys/devices/system/cpu/online`, CPU1 activity, watchdog feeding,
   temperature and Qt process state. Do not change clocks or voltages.
4. Request stock reboot. Verify the exact factory p8, Phoenix and approved
   ADC postflight. A failed hotplug may freeze the temporary kernel; stop
   host lease renewal and allow WDT2 to reset it. A hang before watchdog
   driver probe may still need one physical power cycle. Never repeat an
   unchanged failure.

The prior ram108 pass does not prove CPU1 startup. This plan does not
authorize an eMMC firmware update or persistent CPU/power-policy change.

## Result on 2026-11-12

The single live trial passed. CPU1 was offline at boot and came online after
one watchdog-backed hotplug request. A CPU1-pinned command and CPU1 timer and
scheduler activity confirmed execution. The watchdog advanced to 22 pings,
Qt stayed on its original PID, and eMMC remained read-only. Requested reboot
returned stock in 36.7 seconds with the exact factory p8 and approved ADC
postflight. The [validation record](../kernel/validation-ram109.json) and
[observation log](ram109-hotplug-observation.json) preserve the evidence.

The first staging preflight failed before p8 was written because p14 had too
little free space. One hash-verified obsolete ram59 test zImage was removed,
and the unchanged ram109 candidate then staged and ran successfully.
