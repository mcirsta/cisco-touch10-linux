# Perrier functionality roadmap

Qualified default RAM baseline: ram104. Ram105 adds IPv6 and DHCP observation;
ram106 applies and renews the isolated PC lease. Validated ram107 handles
gateway, DNS and lease-loss state with independent rescue SSH. Ram110 has
passed three U-Boot RAM boots with both CPUs active, including a six-minute
peripheral regression and real DHCP router/DNS option delivery on the fixed
direct link. The default stays ram104 until arbitrary production lease
behavior and remaining board support are qualified.
All live trials use the one-shot U-Boot RAM
loader, restore factory p8 before handoff, keep eMMC read-only/unmounted,
renew the host lease, and return through the nowayout watchdog or a requested
reboot. Keep ram104 and ram100 as fallbacks. Do not blank/unblank the display
or restart Qt for unrelated tests. SGX/3D work is parked by the owner.

## 1. Network and time

Stock has IPv4, IPv6 link-local, DHCP and local DNS behavior. The direct PC
link already gives this panel's MAC `24:16:9d:b6:77:bb` the fixed lease
`10.77.10.10`. Ram105 first enables upstream IPv6 and observes the DHCP
exchange without replacing the established static SSH address. Ram105 passed:
IPv6 loopback/link-local, one exact DHCP lease, Qt and watchdog healthy,
factory recovery. Ram106 applied and renewed the fixed lease with a separate
rescue address. Ram107 added route/DNS state and verified renewal and
lease-loss cleanup. A later ram110 run received actual router/DNS options
from a temporary isolated server, resolved a local `.test` name, and removed
both settings on renewal from the normal server. See the
[real-option validation](validation-ram110-network.json). Time can be
synced from the host without writing the unconfigured TWL RTC; make it a
normal session aid before choosing a production time source.

## 2. CPU1/SMP

Stock runs both Cortex-A9 cores at 700 MHz. Mainline `omap4_smp_ops` now
starts both cores in ram110 through the one-shot U-Boot RAM route. A second,
roughly six-minute run exercised CPU1 under bounded load alongside ALSA,
Ethernet, sensors, Qt and the watchdog, then returned to exact stock state.
See the [extended validation](validation-ram110-extended.json). The older
kexec parser failures remain a separate handoff issue; the exact ram56
archive passed on a generic two-core Cortex-A9 QEMU boot. Keep CPU frequency
and rail voltage fixed until Perrier's MPU supply is mapped. Longer SMP and
production power-management qualification remain open.

## 3. Power and suspend

Map the stock MPU voltage processor, PMIC regulator consumers, OPP values,
clock domains and physical rail enables before enabling CPUfreq or changing
any voltage. The current mainline cpufreq driver may change rate even without
an MPU `vcc` regulator, so it stays disabled. Qualify WFI/idle separately,
then suspend/resume, then ordered display/audio power-down and wake sources.
Each step needs register snapshots and a watchdog recovery path.

## 4. Audio, board controls and boot image

Mainline TWL6040/McPDM playback, HFR routing, Qt controls and upstream
`dmix` are qualified. Stock ABE DSP effects and any microphone route require
their own firmware and physical-path inventory. Map the GPIO expander's
outputs before driving them. Factory-reset and recovery selector work remains
read-only investigation until a concrete, separately reviewed change is
authorized. Once the kernel and rootfs are complete, test the full image
through U-Boot RAM and watchdog recovery before considering an eMMC boot
target.
