# Cisco Touch 10 investigation

Initial investigation date: 2026-11-06. The current kernel-development status
is in the [development workflow](DEVELOPMENT-WORKFLOW.md). Ram60's full Linux
6.18.48 RAM environment now boots through the installed U-Boot with Ethernet,
root SSH, and proven hardware watchdog recovery. U-Boot is the default kernel
test route; see the [current record](development/perrier-cold-ethernet/README.md).
The [restored Gen4 port](development/perrier-gen4/README.md) adds DT touch
power/reset and the older controller protocol; ram62 initialized touch and
Qt from U-Boot. Ram64 also adds the missing LCD/backlight supply, PWM pinmux,
and correctly identified GPIO151 enable and is undergoing physical validation. A
minimal image also passed a physical power-on test; details are in the
[cold-boot record](development/perrier-coldboot/README.md).
The earlier root, backup, and boot-chain findings are in
[Root access and backup investigation](ROOT-AND-BACKUP.md).

## Connected device: observations

Evidence is in `evidence/console-*.log`.

| Item | Observed value |
| --- | --- |
| USB path | Host `3-2` hub, FTDI UART on `3-2.1`; transient OMAP ROM USB on `3-2.2` |
| USB hub | `04b4:6570` |
| UART bridge | FT230X, `0403:6015`, serial `D3081QEX` |
| Host serial node | `/dev/ttyUSB0` |
| Stable host path | `/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D3081QEX-if00-port0` |
| Console | 115200 baud, 8 data bits, no parity, 1 stop bit, no flow control |
| Login verified | `support`, no password; restricted `supportsh` |
| Active software | `image2 - ce9.9.0 46f7ea38fda 2019-10-10` |
| Kernel | Linux `3.4.113+`, ARMv7, SMP PREEMPT, built 2019-09-17 |
| Board / SoC | `Perrier board`, TI `OMAP4460 ES1.1`, two Cortex-A9 CPUs |
| Memory | Bootloader confirms 1 GiB DRAM; Linux reports 907 MB across usable banks |
| Storage | eMMC `004GA0`, 3.68 GiB user area, two 2 MiB boot areas |
| Bootloader | Kernel command line reports `u-boot=2013.04-32` |
| Active base filesystem | `/dev/mmcblk0p14`, ext4 |
| Touch driver | `cyttsp4-i2c`, I2C bus 2 address `0x67` |
| Display | OMAP DRM, LVDS bridge reset in boot log, PWM backlight on timer 10 |
| Ethernet | SMSC95xx USB Ethernet, `eth0`, MAC `24:16:9d:b6:77:bb`, now `192.168.1.161/24` |
| EEPROM | Kernel detects 256-byte EEPROM on I2C bus 4, address `0x54` |

The kernel log says the alternate GPT is invalid and the primary is being used.
This was already present; no repair was attempted.

The host user initially lacked serial access. A KDE/polkit authentication prompt
successfully ran `setfacl -m u:marius:rw /dev/ttyUSB0`. This avoids further sudo
use for this connection. Reconnecting USB may recreate the node and drop the ACL.

## Communicating with it

`tools/serial_probe.py` uses only the Python standard library. It captures output
and sends only explicitly supplied commands. Do not run two console clients at
once. It does not deliberately toggle modem lines, send BREAK, or reboot.

```sh
python3 tools/serial_probe.py --command '' --log evidence/session.log
```

At a login prompt, send `support`. Available diagnostic commands include:

```text
help
uname
selectsw
ip addr
netstat -lnt
show
show dmesg
show console
show kern
show messages
show main
show touchmenu
```

Bare `selectsw` lists images; do not supply selection arguments during inventory.
`bootlogo --help` was checked, without sending an on/off argument.
Only loopback TCP listeners were observed. Ethernet is now connected; targeted
connections to the Touch's tested TCP ports were refused. The service USB
connection exposes a UART and a transient OMAP ROM peripheral-boot interface.
No USB network, ADB, or mass-storage interface was observed.

After leaving supportsh, username `root` was submitted and a password prompt
appeared. Automatic approval review initially blocked the blank-password check.
After the user explicitly authorized one attempt and read-only inspection, one
blank password was submitted at a confirmed root password prompt. It produced
only a newline, with no shell prompt or explicit rejection. Ctrl-C returned to
the login prompt. No further root password was tried. Root shell access is
therefore unverified; this does not establish that the password was accepted.
See `evidence/console-root-authorized.log`.

In the subsequent root/backup investigation, the user authorized an additional
blank-password test using LF instead of CR. This returned **Login incorrect**.
Thus the previous silence was not proof of a successful login, and blank root
access does not work on the connected CE9.9.0 unit. See
`evidence/root-investigation-lf.log` and `ROOT-AND-BACKUP.md` for the updated
findings. No firmware backup of this unit has yet been acquired.

The owner later connected the Touch 10 to the PC's second Ethernet port.
An isolated 10.77.10.0/24 link is active; the Touch obtained 10.77.10.10.
IPv6 SSDP discovery and two HTTP fetches of a benign local device description
were captured. No pairing, root access, firmware transfer or backup followed.
See `ROOT-AND-BACKUP.md` and `evidence/direct-link-initial.pcap`. The temporary
DHCP server and packet capture were stopped after the test.

An identification-only query to the transient OMAP ROM USB interface returned
an 81-byte ASIC ID. The ROM's MPKH equals SHA-256 of the root public-key record
in the older reference Touch 10 MLO. This confirms a shared trust-anchor key
record, but no loader has been uploaded and no alternate boot or root access
has been demonstrated. Raw identity and reproducible comparison results are in
`evidence/omap-rom-asic-id.bin` and
`evidence/reference-mlo-rom-mpkh-match.json`; details are in
`ROOT-AND-BACKUP.md`.

## Firmware obtained for offline study

A public dump from another owner's older Touch 10 was downloaded from:

<https://trimen.org/Cisco_HW_Hack/TelepresenceTouch_10/emmc_dump.bin.tar.gz>

First-hand writeup:
<https://wiki.taktpraha.cz/profile/trimen/ciscohax>

Local archive: `firmware/reference/emmc_dump.bin.tar.gz` (283,216,742 bytes).
SHA-256:
`b2f9d9fdf18cbd3539db17e16664bc26db94893cbfc8a65dc679a38ffcd07593`.
This hash identifies our download; no independently published authenticity hash
was found.

The decompressed `emmc_dump.bin` is 3,909,091,328 bytes. Its GPT has 16 named
partitions; the parsed layout is in `firmware/reference/partitions.json`.
Partition 14, `system-b`, was copied into `system-b.ext4` and read with `debugfs`
without writable mounting. It contains `image1` (TI7.2.1 cb31c3d) and `image2`
(TI7.3.3 c84180a). These differ from the connected device's CE9.9.0.

Extracted files in `firmware/reference/image2/`:

| File | Finding |
| --- | --- |
| `kernel` | uImage, `Cisco kernel 27`, load/entry `0x80008000` |
| `rootfs` | uImage, `CISCO rootfs 27`, gzip data begins at file offset 912 |
| `rootfs.cpio` | Decompressed newc archive, 1,614 entries listed in `rootfs-files.txt` |
| `u-boot.bin` | uImage, `Cisco U-Boot dev`, load/entry `0x80e80000` |

The three extracted uImages pass their header and payload CRC32 checks. These
checks establish internal consistency, not cryptographic authenticity or boot
acceptance. Metadata is in `uimage-manifest.json`. Kernel and rootfs payloads
begin with a Cisco `CertISW` wrapper, so stripping just the 64-byte uImage header
does not directly yield the kernel or gzip archive. No payload was executed.

The reference rootfs has modules for Linux `3.4.104-27` and starts a getty on
`ttyO2`. The reference firmware's partition configuration specifies encrypted
`config.img` and `user.img`, with a key read from EEPROM address `0x54`, offset
101, length 16. This is evidence from the other unit's firmware, not a key read
or encryption verification on this unit. No private configuration was extracted
for publication. Keep raw dumps local.

## Vendor firmware and source route

Cisco's normal update process distributes Touch 10 software from its paired
codec. A codec update package is a useful source to inspect for the matching
Touch payload; it is not automatically an independently flashable Touch image.
No authenticated Cisco CE9.9.0 package has been obtained for this unit.

Cisco documents pairing-related ports on the codec: TCP 4043 for legacy software
download, 4045 for version information, 4047 for the session, and 4060 for secure
software download. These are codec-side services, not observed listeners on
this Touch 10:
<https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/roomos-1019/desk-room-board-administration-guide-roomos-1019.pdf>

Cisco's employee-authored service-console guide documents 115200 8N1, no flow
control, and passwordless support login:
<https://community.cisco.com/t5/tkb-%E3%82%B3%E3%83%A9%E3%83%9C%E3%83%AC%E3%83%BC%E3%82%B7%E3%83%A7%E3%83%B3-%E3%83%89%E3%82%AD%E3%83%A5%E3%83%A1%E3%83%B3%E3%83%88/touch-10-%E3%81%AE%E3%83%AD%E3%82%B0%E5%8F%96%E5%BE%97%E6%96%B9%E6%B3%95/ta-p/3156702>

Cisco's CE8.0 Touch 10 open-source notice gives
`external-opensource-requests@cisco.com` as the source request contact and
reference `78EE117C99-94437712`. For a request, identify the actual CE9.9.0 build
and ask for its corresponding GPL-covered kernel and bootloader source, board
support and build configuration. The CE8 notice is a lead, not proof that its
source matches CE9.9.0. No request was sent:
<https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/software/ce8/licensing-guide/touch10-open-source-documentation-ce80.pdf>

## Path toward replacement firmware

1. Establish authorized read-only root access, if available. Capture the running
   partition map, mounts, boot configuration, kernel configuration and board
   data. The support shell alone does not provide a general backup command.
2. Back up this unit's entire eMMC user area, both eMMC boot areas and board
   EEPROM. A public dump cannot replace its manufacturing data or keys.
3. Determine the actual boot verification policy and a practical recovery route.
   The public investigator reports that U-Boot CLI is disabled and image load
   failures reboot the device. That behavior has not been tested here. Signed
   and unsigned filenames in an old dump do not establish an unlocked boot chain.
4. Obtain corresponding vendor source or reconstruct the Perrier board data.
   The live evidence provides OMAP4460, PMIC, display, touch, Ethernet and storage
   starting points; exact panel timings and pin assignments still need evidence.
5. Once recovery is verified, attempt a minimal RAM-booted Linux/initramfs with
   serial output, preserving stock storage. Add display and touch after the
   console and boot path work.

A replacement Linux system is a plausible engineering target. We have not yet
demonstrated arbitrary code execution, alternate boot, recovery or the ability
to install an unsigned image on this unit.
