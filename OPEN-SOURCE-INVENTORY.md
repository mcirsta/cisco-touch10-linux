# Touch 10 open-source inventory

## What is available

The only Touch 10-specific Cisco open-source inventory located so far is
[**Open Source Used In Cisco TelePresence Touch 10 (CE8.0)**](https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/software/ce8/licensing-guide/touch10-open-source-documentation-ce80.pdf).
A local copy is `firmware/reference/touch10-open-source-ce80.pdf` (SHA-256
`7bf0eb8fe2a48f19004100b999b7888ff76379972e303a47fdbe57bd4ea762a8`).
It is a license/notice inventory, **not source code or a firmware image**.
Cisco directs requests for the corresponding license-covered source to
`external-opensource-requests@cisco.com` with reference
`78EE117C99-94437712`. `SOURCE-REQUEST.md` is a draft for this unit; it has
not been sent.

Cisco's later [RoomOS 11.5.2.x open-source inventory](https://www.cisco.com/c/dam/en_us/about/doing_business/open_source/docs/RoomOS-RoomOS1152x-1687973598.pdf)
lists `linux-omap 3.4.113-cisco` and `u-boot v2013.04`. Those are useful clues
to the continued OMAP kernel and bootloader branches, but this is not a
CE9.9.0 Touch 10 inventory or source archive.
The public upstream [Linux 3.4.113 source](https://www.kernel.org/pub/linux/kernel/v3.x/linux-3.4.113.tar.xz)
also lacks any unverified Cisco board patches/configuration.

## Independent board research

- [A first-hand Touch 10 teardown](https://wiki.taktpraha.cz/profile/trimen/ciscohax)
  identifies the OMAP4460, display, touch controller, UART, and eMMC on an
  **older micro-USB board revision**. Its linked raw eMMC dump is already
  preserved at `firmware/reference/emmc_dump.bin`. The writeup and dump are
  hardware/firmware evidence, not a kernel source tree or a working port.
- [CTS-CTRL-DV10 research notes](https://github.com/thejameswoods/cts-ctrl-dv10)
  include [hardware](https://github.com/thejameswoods/cts-ctrl-dv10/blob/main/docs/hardware.md)
  and [firmware](https://github.com/thejameswoods/cts-ctrl-dv10/blob/main/docs/firmware-observations.md)
  observations based on the older board/dump. The repository contains notes,
  not a device tree, bootloader source, kernel patches, or working software.
  Its boot-layout claims need checking against this unit's direct evidence.
- The [2013 TTC5-09 FCC filing](https://fccid.io/MCLTTC509) includes internal
  photos. It can help identify hardware but contains no board support code.
- [Nexus Q Reloaded](https://github.com/petronijus/nexusQ-reloaded) is a
  Linux 6.18 OMAP4460 port for a **different board**. Its DTS and patches may
  help with SoC-level bring-up, but its pin mapping is not Touch 10 data.

Searches for the exact Perrier/IDEFIX board identifiers did not locate a
publicly indexed Touch 10 board source, device tree, U-Boot source, kernel
patch set, or completed Linux port as of 2026-11-08. This is a search result,
not proof that no such code exists.

## Components Cisco lists for Touch 10 CE8.0

The following 37 entries are transcribed from the contents on pages 2–4 of
Cisco's CE8.0 notice. The dates/qualifiers in the original have been omitted
except where they are part of a version. These are **not verified versions on
the connected CE9.9.0 unit**.

| Component | CE8.0 version |
| --- | --- |
| alsa-lib | 1.0.18 |
| alsa-lib_aserver | 1.0.18 |
| alsa-utils | 1.0.18 |
| bash | 3.2 |
| busybox | 1.23.1 |
| curl | 7.40.0 |
| dhcp | 4.1-ESV-R8 |
| e2fsprogs | 1.42.12 |
| ethtool | 2.6.36 |
| fbset | 2.1 (Cisco notice also prints `3.0.0.0501961`) |
| glib | 2.43.4 |
| glibc | 2.20 |
| inotify-tools | 3.13 |
| ipcalc | 1.3 |
| iproute2 | 3.19.0 |
| libssh2 | 1.4.3 |
| libupnp | 1.6.19 |
| linux | 3.4.107 |
| Linux-PAM | 1.1.8 |
| nc6 | 1.0 |
| ncurses | 5.9 |
| ndisc6 | 1.0.2 |
| net-tools | 1.60 |
| openssh | 6.7p1 |
| openssl | 1.0.1m |
| OpenSSL patch to 0.9.8 branch for RFC5649 | 1.0 |
| openssl/crypto | 1.0.1m |
| Portmap | 4 |
| procps-ng | 3.3.9 |
| qt-everywhere-opensource | 4.8.2 |
| rsync | 2.6.9 |
| sudo | 1.8.8 |
| sysvinit | 2.88dsf |
| tslib | 1.1 |
| udev | 150 |
| util-linux | 2.22.2 |
| xinetd | 2.3.14 |

## Versions confirmed on this CE9.9.0 unit

| Item | Observed version | Evidence |
| --- | --- | --- |
| Installed Touch software | `ce9.9.0 46f7ea38fda`, dated 2019-10-10 | `evidence/live-version-inventory.log` (`selectsw`, no argument) |
| Linux kernel | `3.4.113+`, built 2019-09-17 | `evidence/live-version-inventory.log` (`uname -a`) |
| iproute2 executable | `iproute2-ss190708` | `evidence/live-version-inventory.log` (`ip -V`) |
| U-Boot | `2013.04-32`, built 2018-01-22 | `evidence/control-bootcapture-readable.txt` |

The support shell does not expose a package manager or full filesystem
inventory. The CE8.0 `libupnp`, OpenSSL, BusyBox, Qt and OpenSSH versions
therefore cannot be assigned to this CE9.9.0 build. No CE9.9.0-specific
Touch 10 source archive or license inventory has been acquired.
