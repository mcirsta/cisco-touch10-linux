# Touch 10 DHCP and DNS live-path check (2026-11-06)

The PC's isolated `enp7s0` link hosted a temporary dnsmasq process bound only
to that interface. The Touch 10 requested a lease as `Cisco:Touchdevice`, MAC
`24:16:9d:b6:77:bb`, hostname `SEP24169DB677BB`. The offer/ack assigned
`10.77.10.10/24`, DNS `10.77.10.1`, no router, and a two-minute lease. The
target's `tail messages` confirmed `dnsmasq[862]: using nameserver
10.77.10.1#53` (see `post-dhcp-dns-2026-11-06.log`).

The first discovery reply advertised
`http://touch10-probe.test:18080/...` before the renewed lease completed. The
target sent no observed DNS query or HTTP request for that first UUID. On a
second, one-shot reply after renewal, the host DNS service observed two A and
two AAAA queries from `10.77.10.10` for `touch10-probe.test`. It returned
`10.77.10.1` for A and NXDOMAIN for AAAA. The target then fetched the benign
XML twice. The SSDP/HTTP event record is
`touch10-direct-ssdp-dns-name-retry-2026-11-06.json`.

The PC dnsmasq process was stopped with Ctrl+C. A postcheck of the target
reported `image2 - ce9.9.0 46f7ea38fda 2019-10-10 [ACTIVE] [SELECTED]`;
see `post-dns-name-2026-11-06.log`. The service log showed normal DHCP
renewal and the existing UPnP network-unreachable messages; no observed crash
or firmware change. This proves a reachable DNS forwarding path on the live
unit. It does not demonstrate a DNS vulnerability or root access.
