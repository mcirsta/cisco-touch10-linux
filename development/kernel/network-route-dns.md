# Ram107: DHCP route, DNS and lease-loss handling

Ram107 changes only the volatile initramfs DHCP script and release marker
relative to validated ram106. The Linux 6.18.48 kernel configuration, mainline
drivers, board DTB, Qt application and watchdog guard are unchanged. The
separate `10.77.10.11/24` rescue address remains available on the direct PC
link. The DHCP-managed address, default route (metric 100) and resolver file
are removed on `deconfig`; renewal replaces only state owned by this script.
DHCP IPv4 values are validated before any network change.

The offline test exercises bound, renewal with gateway and two DNS servers,
rejected malformed options, and lease-loss cleanup without touching the host
network. The packed image audit found only the script replacement and release
marker, with no kernel Kconfig or DT change.

In the U-Boot RAM run `../runs/20261112T154108Z-uboot-ram107-80e01b`, the
isolated PC's actual DHCP lease bound `10.77.10.10/24` without a route or DNS.
An explicit test event in the RAM image set default gateway `10.77.10.1` at
metric 100 and wrote nameservers `10.77.10.1` and `192.0.2.53`. A real
`udhcpc` renewal against the unchanged isolated DHCP server removed both
because the renewed lease advertised neither. A controlled `deconfig` left
only the independent `.11` rescue address; `dhcp-loss.log` captures that
state. A subsequent real renewal restored `.10` and left no default route or
resolver file; see `dhcp-post-loss-renew.log`.

Qt started once. The display was not blanked or restarted. eMMC remained
read-only and unmounted, and the nowayout watchdog kept feeding. Requested
recovery returned to stock in 36.8 seconds; exact factory p8, Phoenix, serial
handoff markers and the approved ADC postflight passed.

The router/DNS values were injected as a test event, not obtained from a DHCP
server. The isolated server deliberately advertises none. Actual DHCP option
delivery, DNS resolution, arbitrary production leases, IPv6 DHCP/SLAAC,
and behavior without the direct-link rescue address are still to qualify
before this becomes the default image. Ram104 remains the default and ram106
the qualified isolated-DHCP fallback.

## Follow-up with real DHCP options

The unchanged route/DNS script was later exercised in ram110 with a temporary
isolated dnsmasq fixture on the PC. Its real DHCPACK supplied router and DNS
`10.77.10.1`. The panel installed a metric-100 default route, wrote a
resolver entry, and resolved `probe.touch10-validation.test` to `10.77.10.1`
through that server. After the normal no-router/no-DNS service returned, a
real renewal kept the managed `.10` address and independent `.11` rescue
address while removing the route and resolver. The host unit, original config
and rollback timer were restored. Requested reboot returned stock Linux,
Phoenix, exact factory p8 and the approved ADC state in 36.7 seconds. See
[validation-ram110-network.json](validation-ram110-network.json).

This qualifies option delivery and local DNS on the fixed direct link. An
arbitrary production lease, external DNS, IPv6 DHCP/SLAAC and operation
without the rescue address remain open; ram104 stays the default.
