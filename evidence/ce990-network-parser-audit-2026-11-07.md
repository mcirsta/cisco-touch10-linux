# CE9.9.0 network parser audit (2026-11-07)

Scope: offline inspection of the Touch 10 factory package obtained from the
codec, `firmware/codec-ce9.9.0/idefix.pkg`. Its `vcinfo.txt` identifies
`ce-9.9.0-20190926-45-g46f7ea38fda`, matching the panel's installed
`selectsw` revision. The package is not a byte-for-byte dump of this unit's
eMMC. No new malformed network input was sent to the panel in this audit.

## DHCP

The package's rootfs `/sbin/dhclient` prints `Internet Systems Consortium DHCP
Client 4.3.6-P1` when run under `qemu-arm -L` with `-V`. This is the version ISC
lists as fixed for CVE-2018-5732. The older TI7.3.3 reference image has
4.1-ESV-R8, but that older-client overflow is not a CE9.9.0 lead by version.

The exact `apps.img` `/etc/dhclient-script` writes DHCP-supplied SIP, TMS,
TFTP, WPAD and Cisco TFTP values to `/run/netman/dhcpinfo` as single-quoted
shell-style assignments (lines 105-119). It passes vendor option 43 to the
`provisioninginfo` command and appends the command's output to the same file.
The command itself is absent from all four extracted image trees, and a
recursive literal search found no other `dhcpinfo` reference. The quoting
does not execute the option value in `dhclient-script`; execution would depend
on a consumer sourcing or otherwise interpreting the file, which has not been
found. The script also writes DHCP domain and DNS values to resolver config.

## DNS

The package's `extra.img` `/sbin/dnsmasq -v` prints version **2.80** with
`no-DHCP`, `no-TFTP`, and `no-DNSSEC`. The `apps.img` `/etc/dnsmasq.conf`
sets `interface=lo`, `bind-interfaces`, and `user/group=nobody` and reads
upstream servers from `/run/resolv/conf`. The active config can be generated
at runtime, so the static file alone does not establish every live setting;
the live startup log independently reported `no-DNSSEC`. Prior live evidence
showed that a DHCP-provided upstream DNS server received A/AAAA queries when
an SSDP response contained a hostname in `LOCATION`.

The 2021 dnsmasq DNSSEC overflows require DNSSEC code that this binary lacks.
The network reaches DNS parsing, but neither the version nor the benign live
test demonstrates code execution or a firmware readout.

## UPnP

The exact `apps.img` uses `/bin/upnptool`, not the older TI7.3.3
`upnpdiscoverer`. `/bin/upnpdiscover` launches `upnptool -i $ETHDEVICES -d`.
IDA analysis of this exact `upnptool` identified `upnp::discover` at
`0x25c3c`: it receives at most 1024 bytes per SSDP datagram, extracts
`LOCATION`, fetches the XML description with libcurl, and calls `XML_Parse`
on the response. `XML_ParserCreate("utf-8")` uses the library from
`extra.img`; its `xmlwf -v` prints `expat_2.2.7`. There is no import or call
to `XML_SetExternalEntityRefHandler` in this program. The fetched XML path
was confirmed live by earlier benign probes.

The callback at `0x2511c` constructs a C++ string from the HTTP chunk's
start and `start + size * nmemb`. The character-data callback at `0x24b88`
likewise uses Expat's explicit length. The initial decompiler view obscured
these bounds; ARM disassembly confirmed them. No fixed-size copy bug from the
older `upnpdiscoverer` is established in this CE9.9.0 binary.

Expat 2.2.7 predates upstream security fixes in 2.4.5, including malformed
UTF-8 input passed to application callbacks (CVE-2022-25235) and doctype
stack exhaustion (CVE-2022-25313). The latter needs a much larger XML body
than normal device descriptions. Whether either gives control in this C++
application is unproven. Its callback stores strings in a C++ map; no
unsafe fixed buffer was found in the inspected path.

An off-device check confirms the malformed UTF-8 behavior in this exact
library, beyond version matching. Running the package's `xmlwf -e utf-8` under
QEMU returned exit 0 for `<a\xdb\x25/>` and `<a\xe0\x24\x85/>`; the host's
Expat 2.10.0 rejected both as invalid tokens. These byte patterns are drawn
from upstream's CVE-2022-25235 regression tests. With `xmlwf -d`, the exact
parser's application output retained invalid name bytes (`<a\xdb%>` in one
case), confirming that the malformed name reached callbacks. `xmlwf` uses the same shared
Expat library as `upnptool`, but this test does not exercise `upnptool`'s
application callbacks. Controlled callback testing is the next useful step
before any malformed live XML test. Raw case bytes and exit results are in
`evidence/ce990-expat-utf8-probe-2026-11-07.json`.

## Reproduction and source links

* `qemu-arm -L /tmp/touch10-ce990-sysroot /tmp/touch10-ce990-sysroot/sbin/dhclient -V`
* `LD_LIBRARY_PATH=/tmp/touch10-ce990-extra/lib qemu-arm -L /tmp/touch10-ce990-sysroot /tmp/touch10-ce990-extra/sbin/dnsmasq -v`
* `LD_LIBRARY_PATH=/tmp/touch10-ce990-extra/lib qemu-arm -L /tmp/touch10-ce990-sysroot /tmp/touch10-ce990-extra/bin/xmlwf -v`
* [Expat CVE-2022-25235 upstream regression test](https://github.com/libexpat/libexpat/pull/562/commits/6a5510bc6b7efe743356296724e0b38300f05379)
* [ISC CVE-2018-5732 advisory](https://kb.isc.org/docs/aa-01565)
* [dnsmasq 2.83 maintainer security announcement](https://lists.thekelleys.org.uk/pipermail/dnsmasq-discuss/2021q1/014600.html)
* [Expat 2.4.5 upstream change log](https://github.com/libexpat/libexpat/blob/R_2_4_5/expat/Changes)
* Live reachability: `evidence/dhcp-dns-live-path-2026-11-06.md` and `evidence/touch10-ssdp-*.json`.
