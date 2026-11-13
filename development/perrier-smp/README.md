# Perrier OMAP4460 SMP investigation

Stock CE9.9.0 reports CPU0 and CPU1 online. The proven ram110 Linux 6.18.48
RAM image starts both CPUs during boot. Ram109 first proved CPU1 hotplug after
watchdog startup. CPU frequency and voltage policy remain unchanged. Early
trials used stock `kexec`; ram108 through ram110 used one-shot U-Boot RAM
loading and restored the
factory boot environment before kernel handoff. Every trial checks stock
recovery afterward.

## Bounded trials on 2026-11-09

| Image | Difference | Observed result |
| --- | --- | --- |
| [ram53](../runs/20261109T192744Z-interactive-ca2483/result.json) | Enable `CONFIG_SMP`, two CPUs, and `cpu@1` in DT | No new-kernel serial output or RAM SSH. WDT2 restored stock. |
| [ram54](../runs/20261109T193406Z-interactive-db4e7a/result.json) | Same SMP image with `maxcpus=1` | CPU0 reached kernel init; built-in initramfs unpack panicked with `broken padding`. `panic=5` restored stock. |
| [ram55](../runs/20261109T194227Z-interactive-f66f5c/result.json) | Ram54 plus `initramfs_async=0` | CPU0 reached kernel init; unpack panicked with `junk within compressed archive`. Stock restored. |
| [ram56](../runs/20261109T194738Z-interactive-c09d35/result.json) | Same SMP build with `nosmp`, which skips OMAP SCU/CPU1 preparation | CPU0 reached kernel init; unpack panicked with `junk within compressed archive`. Stock restored. |
| [ram57](../runs/20261109T195241Z-interactive-69e938/result.json) | Proven non-SMP kernel configuration and DT with the current Qt executable and archive | Booted to RAM SSH. Ethernet, connected LVDS, native touch, keypad, and backlight devices were present. Requested reboot restored stock. |

Every run returned to stock Linux 3.4.113+ with `phoenix` running and the
same U-Boot environment hash,
`f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
The ram53 no-console result does not establish where its startup stalled.
The ram54-56 kernel panics are visible in their `serial.log` files; the
controller's `RAM SSH startup deadline exceeded` is a consequence of those
panics, not a separate network failure.

The [offline verifier](verify_archive.py) checked all 484 cpio entries,
header/name/data padding, and trailer for the comparison images. It also
confirmed that each compressed archive expands to its source cpio, appears
byte-for-byte in the linked `Image`, and that the final `zImage` expands to
that `Image`. Ram57 proves the larger current Qt binary
and archive are usable with the non-SMP kernel. The ram54 and ram56 rootfs
manifests differ from ram57 only in the boot marker inside `rcS`.
`initramfs_async=0` and
`nosmp` did not fix the SMP build. In particular, ram56's `nosmp` skips
`omap4_smp_prepare_cpus()`, so merely enabling the SCU or releasing CPU1 is
not sufficient to explain its unpack failure.

## Earlier isolation work

Keep [ram52](../perrier-keypad/README.md) and the successful ram57 comparison
as single-core references. On 2026-11-12 the exact ram56 archive (SHA-256
`502d072867663a3a455358a71d412286ab3963ced665c4288ba428fcc791bf64`)
was linked into a separate Linux 6.18.48 Cortex-A9 SMP kernel and booted on
QEMU `vexpress-a9` with two CPUs. It reached `/bin/sh` without any initramfs
parser error. See [the reproducible probe](qemu_archive_probe.py),
[result](qemu-ram56-archive/result.json) and
[serial log](qemu-ram56-archive/serial.log). The first no-DTB QEMU run had
no console output; the recorded passing run supplies the vexpress DTB.

That test rules out an intrinsically invalid ram56 archive and a generic
ARM SMP parser defect. It does not emulate the OMAP4460 memory controller,
U-Boot, kexec handoff or CPU1 release. Before another hardware SMP trial,
instrument the SMP image to report the built-in compressed archive's
checksum and the exact cpio offset and bytes at the parser error. Compare
those with the host artifact and review ARM zImage relocation, kexec cache
maintenance and stock CPU1 shutdown. The existing one-shot U-Boot path
restores the factory environment before handoff, but its hardware watchdog
starts only when the new driver probes. An early hang may require power
removal. The current evidence does not establish whether the prior corruption
was in kexec, OMAP early memory setup or another configuration-dependent path.

Ram108 is an audited U-Boot isolation candidate based on validated ram107.
It enables `CONFIG_SMP` while forcing `nosmp` and keeping `cpu@1` disabled,
so it tests the SMP kernel configuration without releasing CPU1. Its exact
archive reached `/bin/sh` in a separate generic two-core Cortex-A9 QEMU boot.
The [test plan](ram108-plan.md), [archive result](qemu-ram108-archive/result.json)
and [stock/mainline handoff review](stock-mainline-handoff.md) are saved.
Ram108 passed one Touch 10 U-Boot RAM trial with one CPU active and returned
to stock with exact factory p8 and ADC postflight. See the
[validation record](../kernel/validation-ram108.json). A CPU1-enabled U-Boot
test still needs an early watchdog plan or a physical recovery contingency.

Ram109 passed one U-Boot RAM trial. It booted with CPU1 present but offline
(`maxcpus=1`); after RAM SSH and the watchdog feeder were ready, one hotplug
write brought CPU1 online. A CPU1-pinned command ran, CPU1 timer and scheduler
counts advanced, Qt remained running, and eMMC stayed read-only. Requested
reboot restored stock Linux, Phoenix, exact factory p8 and the approved ADC
state. See the [validation record](../kernel/validation-ram109.json),
[live observations](ram109-hotplug-observation.json) and
[test plan](ram109-plan.md). Boot-time CPU1 release and long-duration SMP
stability remain unqualified.

Ram110 then removed only `maxcpus=1` from the forced kernel command line;
its CPU1-enabled DTB and hardware policy match ram109. Three U-Boot RAM boots
activated both CPUs before `/init` and restored exact stock state. The
second, roughly six-minute run included a 20-second CPU1-pinned load,
concurrent packaged 48 kHz playback, and Ethernet, sensor, EEPROM, Qt and
watchdog checks. CPU temperature peaked at 60.255 °C during that load and
fell to 55.672 °C. No display cycle was requested. See the
[initial validation](../kernel/validation-ram110.json),
[extended validation](../kernel/validation-ram110-extended.json),
[network validation](../kernel/validation-ram110-network.json) and
[plan](ram110-plan.md). Ram104 remains the qualified default while production
power policy and longer-term SMP behavior remain open.

Build and audit commands for the saved variants are in
[`build_image.py`](../perrier-ramenv/build_image.py) and the
`audit_*.py` scripts in this directory. The audited images and unmodified
serial captures remain under `development/perrier-ramenv/` and
`development/runs/` respectively.
