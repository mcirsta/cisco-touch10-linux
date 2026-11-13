# Root access and backup investigation

Date: 2026-11-06. Target: connected Touch 10, serial FOC2403P431,
MAC 24:16:9d:b6:77:bb, CE9.9.0 46f7ea38fda.

**Status (2026-11-07): root SSH persists, a verified raw backup of the eMMC
user area, both eMMC boot partitions, and board EEPROM is complete, and a
RAM-only unsigned `bootz` test succeeded.** The exact CE9.9.0 factory
firmware package was recovered from the seller-tested codec. The older public
TI7.3.3 dump is reference material only. Root settings were changed to
establish SSH, and the owner authorized one partition-8 environment test;
U-Boot saved a valid normal-boot environment. No firmware image, GPT, or
recovery selector was written, and no factory reset was performed. An
initial pairing attempt later caused the panel to **generate a private key in
`/config/pairing/privkey.pem` automatically**, before credentials were entered;
see the owner-approved initial-connection section below. The key was left as
generated and its prior state is unknown.

## Live root access and panel backup, 2026-11-07

On the direct PC-to-panel Ethernet link, the owner-approved updater test used
the exact CE9.9.0 `swsync` path to first fetch a dangling `/upgrade/pkg`
symlink with rsync and then write a small script through that symlink with
curl. The script lived in the initramfs `/etc/profile.d` directory. A later
root-run profile source opened a temporary reverse shell. The live `id`
response was `uid=0(root) gid=0(root)`. The codec test server served no
firmware package, and no package installation or flash write was requested.
The temporary script and symlink were removed and confirmed absent before the
shell and test codec services were stopped. The owner power-cycled the panel;
it returned to its normal screen.

The raw backup is in [`backups/touch10-2026-11-07`](backups/touch10-2026-11-07).
It contains the 3,959,422,976-byte `/dev/mmcblk0` user area, both 2,097,152-byte
eMMC boot areas, the 256-byte board EEPROM, and identity/version metadata.
[`manifest.json`](backups/touch10-2026-11-07/manifest.json) records source paths,
sizes, and SHA-256 values; [`SHA256SUMS`](backups/touch10-2026-11-07/SHA256SUMS)
supports local rechecking. Each file's hash matched on the panel before and
after transfer and on the PC after receipt and in a second read. The active
image was `image2`, running `ce9.9.0 46f7ea38fda 2019-10-10`. These were live
reads, so the backup is not an atomic filesystem snapshot. The authenticated
eMMC RPMB region was not backed up.

The updater path and live evidence are described in
[`evidence/ce990-updater-symlink-chain-2026-11-07.md`](evidence/ce990-updater-symlink-chain-2026-11-07.md).
Older sections below preserve the investigation sequence and may describe
then-pending tests.

## Root SSH and recovery follow-up, 2026-11-07

The owner requested a simple persistent root connection. The stock SSH
service now accepts a dedicated key over the direct PC link; a separate
connection returned `uid=0(root)`. Persistent `/config` and `/user` files
enable SSH and restore the volatile root permission and key during startup.
The boot hook passed syntax, live restore, and `sshd -t` checks. One
owner-authorized normal software reboot then produced a new boot ID and a
fresh `uid=0(root)` SSH session; the normal `phoenix` process was running.
The temporary updater symlink and RAM script were removed. Connection instructions are in
[`access/README.md`](access/README.md).

The [recovery audit](evidence/ce990-root-ssh-and-recovery-2026-11-07.md)
confirms matching signed bootloader copies and a valid diagnostic image in
partition 10. The alternate OS slot is not established as bootable, the live
U-Boot environment is invalid and uses defaults, and the backup GPT header is
absent. The exact U-Boot read and save paths locate the 256 KiB environment in
partition 8 (`sb2-data`); live SSH readback matches the backup and confirms
the invalid CRC. Offline analysis also found a `SHELL` client in the
diagnostic image's console switcher. Diagnostic boot and shell access remain
untested. No U-Boot environment, GPT, or diagnostic-boot selector was written.

Root SSH was also used for an early bounded [memory access check](evidence/rom-linux-read-2026-11-07.md).
**Correction:** that check targeted an OMAP4460 reserved region because the
address was wrong. Its first 16 mapped bytes were zero, and a 48 KiB mapped
read caused a kernel external abort at physical `0x4002f000`. It supplies no
evidence about ROM readability. The panel remained reachable and its normal
application was running. A later corrected-address mapped read succeeded;
see the Boot ROM capture below.

A subsequent [offline ROM-service audit](evidence/rom-offline-service-audit-2026-11-07.md)
traced the exact signed PPA and MLO ISW. The PPA uses external handoff-table
services during memory cleanup, and the MLO invokes verification services,
but neither trace established a host-controlled ROM-to-USB/serial readback
path. The checked public ROM archive contains an AM335x dump, not an OMAP4
dump. No panel access was used for this audit.

An [exact U-Boot command audit](evidence/ce990-uboot-unsigned-boot-rom-audit-2026-11-07.md)
found that `go` is a disabled stub and legacy `bootm`/`booti` invokes Cisco
signature verification, while `bootz` has a raw zImage path without that
verifier. The `source` command accepts a CRC-valid U-Boot script without the
Cisco certificate check; that route remains untested.

With the owner's explicit one-time authorization, the
[console environment image](evidence/uboot-console-candidate-2026-11-07/README.md)
was written to partition 8 and verified. U-Boot saved its original boot
command under `normalboot`, reached `TOUCH10>`, and booted a RAM-only modified
zImage through `bootz`. Linux, `phoenix`, and root SSH returned. The
[live proof](evidence/uboot-bootz-live-proof-2026-11-07.md) records the serial
transcript, hashes, commands, and persistent environment. No Boot ROM read
was attempted from U-Boot; a corrected-address Linux `/dev/mem` `read()`
returned `Bad address` with no bytes. A subsequent user-mode mapped read
captured the complete ROM; see below.
The [recovery safety review](evidence/recovery-safety-review-2026-11-07.md)
corrects the ROM address and records the remaining U-Boot parser and fallback
risks before any environment write.
The [Cisco recovery procedure review](evidence/cisco-touch10-recovery-2026-11-07.md)
records the CE9.9 panel reset sequences and codec-provided upgrade behavior.
The installed reset script matches the recovered package and would likely
remove the persistent SSH setup; no reset was performed.

## Exact CE9.9.0 package recovered from offline codec

The owner connected the original seller-tested codec directly to the PC's
isolated `enp7s0` port in place of the Touch 10. Passive capture identified
codec MAC `4c:e1:76:e4:49:03` and its link-local address `169.254.1.1`; the
PC used `169.254.1.2/24`. IP forwarding was disabled, and no gateway or DNS
was offered to the codec. No Internet connection or panel pairing was used.
The codec's TCP 4045 announcement, saved at
`evidence/codec-package-announcement-ce9.9.0-2026-11-07.json`, reported:

```text
version: ce9.9.0 46f7ea38fda 2019-10-10
method: rsync
url: rsync://[::ffff:169.254.1.1]:4043/idefix/idefix.pkg
targets: 102300-3,102310-0,102310-1,101282-0
```

The last target is the panel's Perrier hardware revision. The only exported
rsync module was `idefix`, containing only this package. We copied the
113,785,221-byte package to `firmware/codec-ce9.9.0/idefix.pkg`.
SHA-256:
`e3fdd8225c44926b7f879ed4d36c37b97e1bc9e4e6477e04fa3cb93a0f16ad48`.
An `rsync --checksum --dry-run` comparison against the codec reported no
difference. The source file on the codec was read only.

`tools/extract_touch_pkg.py` parsed the `pkg\0` member table, validated
contiguous offsets and total length, and extracted 18 entries to
`firmware/codec-ce9.9.0/extracted/`. Its `manifest.json` contains member
offsets, sizes, and SHA-256 hashes. The package contains `MLO`,
`u-boot_signed.bin`, `kernel`, `rootfs`, and three readable SquashFS images:
`gui.img`, `extra.img`, and `apps.img`. The three U-Boot image headers and
payloads passed their CRC32 checks. The rootfs's gzip stream decompressed
successfully into a 47,033,856-byte `rootfs.cpio`; `apps.img` was unpacked
to `firmware/codec-ce9.9.0/apps-unpacked/`. The package is readable rather
than payload-encrypted. Its signing certificate and signature are present,
but independent cryptographic signature verification has not yet been done.

This is the exact **factory package** matching the Touch's installed version.
It is not a raw backup of the panel's eMMC, persistent settings, unique keys,
or calibration data. It provides the exact 2019 binaries for offline analysis.

### Exact CE9.9.0 MLO comparison

The package's `MLO` is 41,024 bytes (SHA-256
`2b80cf8b398c3cb109d4da028831ff4881c8b0ea0fa8c33167a6d6b00e62e427`).
Its TOC contains `MLO` at offset `0x4000`, size `0x6040`, followed by
`PRIMAPP` at `0x0c00`, size `0x339c`, and `KEYS` at `0x0200`, size `0x0960`.
The embedded banner says `Cisco Systems, Inc. MLO 1.41.0
(Jan 22 2018 - 12:37:07)`, matching the version and build date captured from
the panel's serial boot. This is strong version evidence, though we cannot
prove byte-for-byte identity without reading the panel's eMMC.

Compared with the older 41,628-byte TI7.3.3 reference MLO, the entire
`KEYS` and `PRIMAPP` sections and padding through offset `0x4000` are
byte-for-byte identical. Only the two TOC size bytes at `0x4`–`0x5` differ
before the signed ISW; the ISW itself is different and 604 bytes shorter.
The root public-key record in the exact MLO hashes to
`8b846a5a4bd78d86fdbeee1c4ce0ed074e91b9f501f80652d1b6084b1c0fa742`,
identical to this unit's ROM MPKH. The reproducible check is
`tools/check_rom_mlo_key.py`; result:
`evidence/exact-ce9.9.0-mlo-rom-mpkh-match.json`.

This exact MLO provides the relevant first-stage code for auditing boot and
recovery behavior. It does not by itself grant root or expose a flash-read
command. It remains above the observed 31–32 KiB ROM USB receive transition,
and its storage TOC begins with `MLO`, while the tested USB route used `2ND`.
The earlier USB tests used the older MLO; the exact-MLO result follows below.
Any attempt to shrink or rename it would need a fresh authentication analysis,
since an intact certificate chain cannot be assumed after header edits.

On 2026-11-07, the owner cold power-cycled the panel for a one-shot USB ROM
test of the **unmodified exact MLO**. The probe pinned its 41,024-byte size,
SHA-256, certificate markers, and Touch 10 FTDI sibling USB port. ROM accepted
the BOOT command, image length, and the first 512-byte sector, then the second
sector failed with USB `EPROTO` (errno 71). Passive serial showed the usual
PPA, 2018 Cisco MLO, U-Boot, kernel and Linux login. Since the full image did
not transfer, that boot is the installed eMMC path, not proof that the USB
copy executed. The result matches the earlier intact 41,628-byte reference
MLO failure, so the exact build does not resolve this USB transport hurdle.
Evidence: `evidence/rom-exact-mlo-20261107T011234Z-usb.log`, matching
`-serial.log`, and `-usbmon.pcap`. No storage write was requested.

The next RAM-only test submitted the exact MLO's signed primary application
and root-key material as a 16,284-byte OMAP `2ND` image. Only the outer TOC
name, size, and truncation changed; signed bytes from offset `0x200` through
`0x3f9c` were unchanged. On the corrected capture, BOOT, length, and every
image packet completed successfully. Serial then printed the PPA 1.8.5
banner, `Detected device: 04460e11 HS`, `SEC_STATUS = 00030181`, followed
by `FATAL ERROR` and `LITE_TRACE_ON`; no Cisco MLO or U-Boot followed. The
TI ROM USB interface remained enumerated but did not answer a subsequent
GET_ID request. This establishes that the shorter signed candidate crossed
the USB receive boundary and reached a PPA error path; it does not establish
an interactive PPA command interface, a signature bypass, or eMMC readback.
The owner then cold power-cycled the panel and the ROM USB interface
disappeared. Capture: `evidence/rom-exact-ppa-2nd-20261107T013700Z-usb.log`,
matching `-serial.log`, `-usbmon.pcap`, and filtered target pcap. The first
attempt at `20261107T013402Z` failed during host USB configuration before
sending BOOT and is not a device-side result.

Offline IDA analysis of the exact PPA locates its startup at `0x403031b4`,
the memory-cleanup message routine at `0x40301e58`, and the generic fatal
printer at `0x403017f4`. The fatal printer emits no reason code in this
`LITE_TRACE_ON` build. A normal boot and the successful USB transfer print
the same PPA banner and `The PPA is about to free 2252 bytes`; only the next
line differs. The compact `2ND` test contains no signed Cisco MLO ISW, so a
missing next stage is the leading explanation, but the trace does not prove
where the error originated. The exact signed PPA payload and its IDA database
are in `firmware/codec-ce9.9.0/analysis/touch10-ce990-ppa.bin` and `.i64`.
The PPA initialization path registers that fatal printer as a callback
through a table pointer loaded from `0x402104` (`0x40301880` performs the
write). The PPA image does not show who initializes that pointer. This
explains why no direct PPA call site carries an error code: a caller through
the table can invoke the callback after PPA returns. The PPA exposes service
dispatch entry points to its signed next stage; this USB test did not give
the host a general PPA function-call interface. An input-driven memory bug
would need to be reached through the unsigned outer TOC, declared transfer
length, or arguments supplied to PPA. The observed fatal is a useful oracle
for such bounded tests, not yet proof of a memory overwrite.

A targeted RAM-only control increased the `2ND` first-item span and declared
image length by four bytes, from `0x3f9c` to `0x3fa0`, while leaving the
`PRIMAPP` TOC and all signed bytes unchanged. The extra four bytes were zero
padding already present in the exact MLO. All 16,288 bytes transferred; the
PPA again printed `Free space for PPA: 2172 bytes` and `The PPA is about to
free 2252 bytes`, then the same generic fatal. This specific outer-span
change did **not** move the PPA cleanup boundary. The owner cold power-cycled
to leave the halted state and the ROM USB interface disappeared. Evidence:
`evidence/rom-exact-ppa-2nd-plus4-20261107T015717Z-usb.log` and matching
`-serial.log`/`-usbmon.pcap`.

A first IDA pass over the exact signed ISW resolves the apparently promising
`warning: skipping signature verification` text. The relevant function at
loaded address `0x40307864` calls a CPU-type reader at `0x40304658`, which
extracts bits 8–10 from the control register at `0x4a0022c4`. It skips
verification only if that hardware value is 3 (the GP CPU branch). Otherwise
it invokes the certificate-signature check and compares a computed SHA-1
hash with the stored hash; failure returns an error. The panel's captured
boot reports an HS device, so this string does not expose a software switch
to disable verification on this unit. This is a targeted code-path result,
not a full audit of the MLO.

### Exact MLO and U-Boot recovery-path trace

IDA disassembly of the exact MLO's ISW shows its main boot path accepts MMC
boot-source codes 5 (`MMC/SD1`) and 6 (`EMMC`). It tries bootloader images at
eMMC sectors `0x5b00`, `0x25b00`, then `0x200`. In the older reference dump,
the first two are exactly the starts of GPT partitions 6 and 7 (`sb2-a`,
`sb2-b`); `0x200` lies inside partition 1 (`isw`). The CE9.9.0
`bin/upgradebootsw` script writes its `u-boot_signed.bin` to partitions 6
and 7 and the MLO to partition 1. The loader checks the U-Boot image header
and payload CRC, then calls its certificate-signature/SHA-1 verification
function before handing control to the image. A valid primary image jumps
away, so the secondary and legacy sectors are failure fallbacks. The
disassembled path does not select USB or network as a bootloader source or
provide a serial command loop. This is code-path evidence, not a claim that
all ROM or U-Boot recovery mechanisms have been exhausted.

The exact packaged U-Boot's compiled default environment has
`autoupgrade=0`, `diag_booting=0`, and **no `bootdelay` variable**. Its main
loop at `0x80e8cd0a` sets delay to `-2` when that variable is absent, which
skips the key-polling countdown and runs `bootcmd`. The live serial log
reports `bad CRC, using default environment`, then no countdown, matching
this code path and explaining why the timed Ctrl-C probe did not stop boot.
Later disassembly established that a positive `bootdelay` would show a
countdown but a keypress only prints `Unit is in secure mode, no operations
are allowed` and resumes boot. A valid environment with `bootdelay=-1`, or a
boot command that returns, appears to reach the `TOUCH10> ` command loop;
neither has been tried on the unit. See the
[recovery audit](evidence/ce990-root-ssh-and-recovery-2026-11-07.md).
The default `bootcmd` can boot the diagnostic image from GPT partition 10 if
`diag_booting=BOOTING_DIAG_IMAGE`, or fetch `/touch10.bootscr` with DHCP if
`autoupgrade=1`. Neither condition holds in the captured default environment.
The later root SSH audit read partition 10 and verified its diagnostic uImage
CRC. Changing these flags requires a valid persistent U-Boot environment;
the support console has no demonstrated setter. Root SSH could write the
environment partition, but no such write has been attempted.
The exact rootfs contains no `fw_setenv` utility. Its `upgradebootsw` script
only invalidates the environment partition after rewriting boot software,
which would keep this unit on defaults and risk a boot change. The exact
`supportsh` command strings contain `selectsw` and `bootlogo`, but no
diagnostic-boot or U-Boot-environment setter. A read-only rootfs archive
inventory found no setuid or setgid files in that layer; this does not cover
other mounted image layers or Linux kernel privilege-escalation paths.

The exact CE9.9.0 `S01release` creates `/tmp/releasesw` when the installed
version reports a release build; `S05setup_ssh` disables SSH in that case
unless `/user/start_ssh` exists. IDA decompilation of this build's
`libnss_root.so.2:is_login_allowed` confirms that a release marker denies
root account lookup unless `/etc/root-is-allowed` exists. Neither the rootfs
archive nor unpacked apps contains that override file. The NSS code also
requires `ROOTSETTING=on` in `/config/sysconfig/rootsettings` when it can read
the file. This confirms the older reference policy in the exact build and
explains why a blank serial root login is not a viable route; it does not
identify a way for the restricted support account to change the policy.

A focused second IDA pass over the exact `supportsh` shows that its `ip`,
`netstat`, and `selectsw` handlers call `handle_os_command`, which filters
each argument byte before running a fixed command through `bash -l -c`.
It allows alphanumeric/whitespace plus `@:/.-_'\"`; shell separators and
substitution characters are rejected. Although quotes are allowed, the
input reader uses one `fgets` line and strips its trailing newline, so this
pass did not find a command separator that would turn the quotes into an
executable second command. `bootlogo` accepts exactly `on` or `off` for
EEPROM writes and otherwise uses a read-only getter. This is not a proof of
the shell's security, but it rules out a simple punctuation injection through
these handlers.

### Exact package update gate

The CE9.9.0 `installimage` script calls `pkgverify -f` on a package before
installation, and its early boot hook calls `pkgverify -C /mnt/base/active
pkgheader` on the installed image. We ran this exact ARM `pkgverify` offline
under QEMU: it accepted the unmodified codec package (exit 0) and rejected a
separate copy with one bit changed inside `apps.img` (exit 1, `Signature
invalid!`). The original package was not altered, and the changed copy was
deleted after the test. Evidence:
`evidence/ce990-pkgverify-offline-2026-11-07.txt`.

This makes direct editing of the recovered package an unproven access route:
the verifier rejects a simple payload modification. A controlled write to
the panel would need a valid signed package, a verified bug in the package
handling path, or an independent privileged access path. No update was sent
to the panel. A later review found a separate downloader symlink chain that
could write a volatile root-sourced profile file before package verification;
its exact-binary off-device proof and pending live check are documented in
`evidence/ce990-updater-symlink-chain-2026-11-07.md`.
An IDA review found a suspicious optional-field length subtraction in
`pkg2ReadHeader`; a small malformed-file probe under QEMU returned `EFAULT`
and a clean verifier error, with no crash or signature bypass. The exact
`pkg2SignatureVerify` path iterates built-in public keys and calls
`EVP_VerifyFinal`; no unconditional acceptance path was identified in this
focused pass. This is not a complete parser audit.

The installed `swsync` script follows the older format and would fetch this
package from the codec; the exact `pairing` script is substantially changed
from TI7.3.3 and now verifies its config before sourcing it. An initial IDA
review of the exact `verify-config-file` binary found that it rejects `$`,
backticks and backslashes in quoted values, plus shell metacharacters in
unquoted values. Thus the older `$(...)` config-sourcing payload is blocked
by this build's validation path; no such payload was sent to the panel. No panel
software was installed, changed, or switched during the codec readout.
An initial IDA pass over the exact `supportsh` binary found the same fixed
file and command maps seen in the older reference. Its OS command handler
filters arguments before constructing a shell command. This pass did not
identify an arbitrary file-read or command path; it is not an exhaustive
vulnerability audit.

## Captured boot chain

The owner's requested normal power cycle was captured successfully. Raw bytes
are in `evidence/control-bootcapture.log`; text after the initial binary/noisy
prefix is in `evidence/control-bootcapture-readable.txt`.

- PPA reports `Detected device: 04460e11 HS`, `DEBUG OFF`, and `OBFUSCATOR ON`.
- Cisco MLO 1.41.0, built 2018-01-22, tries the primary bootloader.
- U-Boot 2013.04-32, built 2018-01-22, identifies IDEFIX/PERRIER, OMAP4460 ES1.1
  and **1 GiB DRAM**.
- U-Boot reports `bad CRC, using default environment`. No environment repair,
  save, erase or modification was attempted.
- U-Boot's network initialization reports `No ethernet found`. This concerns
  the bootloader, not Linux Ethernet, which has already been verified working.
- It reads a 3,725,200-byte kernel and a 20,582,926-byte initramfs, verifies
  their checksums and boots Linux. Checksum messages alone are not proof of
  the exact cryptographic verification policy.
- No visible autoboot countdown or interactive prompt appeared in this
  passive capture. This does not alone prove that all abort keys are disabled.

The owner offered another cycle. `tools/boot_interrupt_probe.py` was prepared
for one bounded Ctrl-C test: it waits for a U-Boot banner, sends only Ctrl-C at
20 ms intervals, and stops on a possible prompt, kernel handoff or a five-second
input limit. It sends no BREAK, newline, command, environment save or firmware
write. PTY fixtures verified no idle transmission, Ctrl-C-only input, and stop
conditions at both a prompt and kernel handoff. The live result will be saved
in `evidence/control-boot-interrupt.json`.

That live test completed with `kernel_started_no_prompt`: **104 Ctrl-C bytes**
were transmitted and U-Boot continued to the kernel without a prompt. This
rules out this ordinary timed Ctrl-C attempt, not every possible recovery path.
The probe stopped transmitting at kernel handoff. Text is also saved in
`evidence/control-boot-interrupt-readable.txt`.

## Newly observed ROM USB interface

Host kernel logs show a second device behind the service USB hub during both
captured power cycles, independently of the FTDI UART:

- Physical path: **3-2.2**, versus the UART at 3-2.1.
- USB ID **0451:d010**, manufacturer Texas Instruments, product **OMAP4440**.
- High-speed enumeration lasts about three seconds, then disconnects before
  stock boot continues. The USB product string does not override the live
  OMAP4460 ES1.1 CPU identification.
- Evidence: `evidence/rom-usb-enumeration.log`.

This is a promising OMAP4 ROM peripheral-boot transport, not established root
access or a flash readback interface. The chip's HS report also means generic
unsigned RAM-loader acceptance must not be assumed.

### OMAP4460 Boot ROM captured

TI's [OMAP4460 memory map](https://www.ti.com/jp/lit/pdf/swpu316) identifies a 48 KiB on-chip boot ROM at
physical `0x40030000`–`0x4003bfff`. This immutable code is separate from the Touch 10's
eMMC, which holds the 2019 Cisco software. On 2026-11-07, root SSH and a
user-mode, read-only `/dev/mem` mapping captured all 49,152 bytes at that
address. The image is
[`evidence/omap4460-bootrom-2026-11-07.bin`](evidence/omap4460-bootrom-2026-11-07.bin),
SHA-256 `7fd0176dbdf06cfa42f147a5c0a923abb1f2fa269b82d0352fa02a5bd3b8efff`.
The [live MLO and ROM read record](evidence/rom-read-live-mlo-check-2026-11-07.md)
describes the bounded probes and health checks. The ROM image can now be
audited offline for USB parsing and signature verification; it is separate
from the backup of the unit's writable firmware. The ROM USB GET_ID response
still has no demonstrated memory-read command.

TI source: [OMAP4460 public TRM](https://www.ti.com/lit/pdf/swpu235).
TI's public OMAP4460 ES1.x errata describe boot-related silicon issues but do
not establish a USB readback or security-bypass route:
<https://www.ti.com/lit/er/swpz017l/swpz017l.pdf>.

### ROM exploit investigation, 2026-11-06

Public OMAP4 USB boot tools expose GET_ID, BOOT and boot-source selection
messages. They do not identify an arbitrary-memory-read request. Search of
published OMAP4460/OMAP4 boot ROM research and TI's public ES1.x errata did not
produce a verified USB signature-bypass or code-execution exploit applicable
to this high-security device. This is a research result, not proof that the ROM
has no bug. The `ti` directory of Zenofex's public [BootROM archive]
(https://github.com/Zenofex/SoC-BootROMs/tree/main/ti) contains an AM335x
image but no OMAP4 image as inspected on this date.

### Historical USB/ROM plan before the live dump

At the time of this plan, the target's exact 48 KiB ROM image was not yet
available. It has since been captured as documented above. The original
investigation used the following related material:

- the target ROM's 81-byte ASIC identity, ROM-family/revision fields, and MPKH;
- a complete older Touch 10 eMMC image;
- its authentic 41,628-byte Cisco/TI M-Shield MLO, including PPA and ISW;
- a byte-for-byte match between the MLO root-key record hash and the target
  ROM's MPKH; and
- public OMAP4 USB-loader source plus TI's full peripheral-boot and memory-map
  documentation.

The next experiments are ordered to maximize information while leaving flash
untouched:

1. **Corrected unsigned execution check — completed.** The ROM accepted the
   GET_ID, BOOT, four-byte length, and four raw ARM bytes `fe ff ff ea`
   (`b .`) at the USB transport level. It then continued immediately through
   the stock 2018 PPA, MLO, U-Boot, and kernel instead of stopping in the loop.
   This is consistent with HS authentication rejecting the unsigned image.
   Evidence: `evidence/rom-corrected-raw-usb-2026-11-06.log` and
   `evidence/rom-corrected-raw-serial-2026-11-06.log`.
2. **Authentic signed-MLO execution proof.** Since unsigned code was rejected,
   upload the unmodified older Cisco MLO. Its trust-anchor record matches this
   ROM. The 2014 MLO banner is distinguishable from the unit's 2018 MLO and
   provides an unambiguous serial execution marker. Static analysis of its ISW
   boot path shows MMC initialization followed by sector reads at the primary,
   secondary, and legacy offsets; the low-level transfer routine identifies
   itself as `mmc read`. Complete the PPA-side audit before performing this
   test; the ROM transfer itself does not write storage.
3. **Boundary-only ROM parser tests.** TI documents a host-provided 32-bit
   image size and a 48 KiB download area at `0x40300000`–`0x4030bfff`, followed
   by the public stack at `0x4030c000` and RAM exception vectors at
   `0x4030d000`. Test acceptance/rejection around `0xbffc`, `0xc000`, and
   `0xc004` before sending anything that reaches control data. A clean reject
   establishes a bound; a changed USB/serial outcome indicates a length-check
   defect worth narrowing.
4. **Controlled exception-vector test, only if step 3 exposes an overwrite.**
   The data-abort handler pointer is documented at `0x4030d030`, 0xd030 bytes
   after the download base. A reproducible overwrite reaching this area could
   redirect a deliberately triggered abort into an in-buffer readout stub.
   This is a vulnerability hypothesis, not a demonstrated exploit.
5. **Dump the exact ROM after the first execution primitive.** Read
   `0x40030000`–`0x4003bfff` and stream 48 KiB over USB or UART. Then compare it
   with a same-revision OMAP4460 ROM from a rootable reference device and audit the
   target's actual USB receive and authentication paths rather than relying on
   documentation alone.

The signed certificate fields in the reference MLO are not a simple
malleability route. Local RSA verification shows that the PPA/ISW image
offsets, sizes, SHA-1 image hashes, entry points, and register tables are
covered by valid PKCS#1 v1.5 SHA-256 signatures. Modifying those fields would
invalidate the certificate. The best current ROM-bug candidate is therefore
the host-controlled download length at the 48 KiB SRAM boundary, followed by
the authentic signed-loader path if the bound is enforced.

There is a second concrete parser surface inside an otherwise authentic MLO.
The first 0x60 bytes are an outer TOC with `MLO`, `PRIMAPP`, and `KEYS`
offset/size pairs; the signed certificates begin later at 0x200, 0xc00, and
0x4000. The valid certificate signatures cover their certificate prefixes and
images, not the preceding TOC. After the untouched signed MLO establishes a
baseline, copies with one TOC offset or size changed at a time can test the
ROM/PPA container parser while leaving all signed certificate and image bytes
intact. Integer overflow or a missing downloaded-buffer bounds check in this
TOC path would be a more structured exploit lead than random mutation.

`tools/omap_rom_signed_mlo_probe.c` implements the untouched baseline. It
requires the exact 41,628-byte MLO and SHA-256
`6f84cd9eecb3c2b2145398fb50e1f0de0526ec4ee772ce957a5394884ed434ed`,
checks all three certificate markers, the observed ASIC identity and MPKH,
and the observed USB physical path before uploading. It performs no target
storage operation.

The first untouched-MLO attempt completed GET_ID, BOOT, and the 41,628-byte
length, then the ROM stalled endpoint 0x01 after exactly one 512-byte USB
max-packet. Stock 2018 PPA/MLO boot followed. This did not execute the 2014
MLO and did not reach enough input to test its certificates or anti-rollback
state: byte 0x200 is the start of `CertPK_`, immediately after the 512 bytes
reported transferred. The next transport test sends the identical pinned MLO
as independently completed 512-byte transfers with a short delay. Failure on
the second packet would identify early container/first-sector rejection;
completion would identify host transfer pacing as the issue. Evidence:
`evidence/rom-signed-mlo-usb-first-2026-11-06.log` and
`evidence/rom-signed-mlo-serial-2026-11-06.log`.

The paced retry confirmed that interpretation: the first independent 512-byte
transfer completed, while the transfer beginning at 0x200 failed with zero
bytes accepted. This is a deterministic first-sector rejection, not a large
host-URB problem. The OMAP4 TRM defines the first peripheral-boot sector as an
optional Configuration Header and documents a disabled/void CHSETTINGS item.
The next baseline prepends that exact 512-byte structure (TOC item at 0x40,
size 0x0c, `CHSETTINGS`, closing 0xffffffff item, key 0xc0c0c0c1, Valid=0,
Version=1) and leaves every byte of the signed MLO unchanged at offset 0x200.
The total 42,140-byte image remains below the documented 48 KiB download area.
Evidence: `evidence/rom-signed-mlo-usb-chunked-2026-11-06.log` and
`evidence/rom-signed-mlo-chunked-serial-2026-11-06.log`.

The combined CH-plus-MLO transfer produced the same phase boundary: the valid
CH sector completed and the immediately following 0x200 packet was not
accepted. This is consistent with the TRM boot flow treating a Configuration
Header as a complete transfer to execute before returning to peripheral
synchronization, rather than as the leading bytes of the same flash-loader
transfer. The next host sequence therefore sends a 512-byte CH as its own
BOOT/length/image transaction, requests ASIC ID again on the still-open USB
endpoints, and only after that sends the untouched 41,628-byte MLO as a second
BOOT transaction. Evidence: `evidence/rom-signed-mlo-usb-chprefix-2026-11-06.log`
and `evidence/rom-signed-mlo-chprefix-serial-2026-11-06.log`.

The separate CH transaction also completed its first 512-byte transfer, but
the post-CH GET_ID failed with `LIBUSB_ERROR_IO`, and the stock 2018 boot
continued. Host kernel timestamps for this and the other recent cycles show
the ROM USB device disconnecting approximately 0.25–0.27 seconds after it
enumerates. Thus the repeated 512-byte boundary is **not sufficient to infer
container rejection or a two-stage CH handshake**: the ROM may simply be
moving on to eMMC before a larger host transfer can complete. The earlier
claims of deterministic first-sector rejection and a required CH phase above
are hypotheses superseded by the USB timing evidence. A fast, timestamped
transfer is needed to distinguish a protocol rejection from this boot-window
race. Evidence: `evidence/rom-signed-mlo-usb-two-stage-2026-11-06.log` and
`evidence/rom-signed-mlo-two-stage-serial-2026-11-06.log`.

A further test omitted optional GET_ID and CH traffic and submitted BOOT,
length, and the unchanged signed MLO immediately on detection. It still
reported 512 bytes followed by `LIBUSB_ERROR_IO`, but only 0.001 seconds
elapsed between the program's discovery and the device loss. The kernel logged
the ROM's USB disconnection 0.259 seconds after enumeration. This makes a late
discovery or host-controller transfer issue plausible; the experiment does not
prove that the ROM parsed or rejected the MLO's first sector. The next version
opens the known `/dev/bus/usb/003/NNN` node as soon as the exact `3-2.2`
sysfs device and `0451:d010` identity appear. It uses libusb's documented
`libusb_wrap_sys_device` API and prints a wall-clock timestamp to compare with
kernel enumeration/disconnect times. Evidence:
`evidence/rom-signed-mlo-usb-fast-2026-11-06.log` and
`evidence/rom-signed-mlo-fast-serial-2026-11-06.log`.

Direct sysfs detection and `libusb_wrap_sys_device` again completed BOOT and
size and reported 512 MLO bytes before disconnect. The kernel logged the USB
device at 23:06:35.470009 and its removal at 23:06:35.475539, only 5.5 ms
apart. The program printed 23:06:35.974478 **after** wrapping the open device
node, so the wrapper may have spent considerable time waiting through the
disconnect; that timestamp cannot identify when BOOT was sent. A final host
timing check uses the Linux `USBDEVFS_BULK` ioctl directly on the already-open
node, timestamps opening, interface claim, and each transfer, and sends the
same unmodified hash-pinned signed MLO in 512-byte chunks. This will test
whether the ROM closes the USB connection promptly after the first sector or
whether the previous wrapper delayed I/O until the boot window ended.
Evidence: `evidence/rom-signed-mlo-usb-direct-2026-11-06.log` and
`evidence/rom-signed-mlo-direct-serial-2026-11-06.log`.

The first direct USBFS attempt opened the right node at 23:09:13.941956,
roughly 0.51 seconds after enumeration, but `USBDEVFS_CLAIMINTERFACE` failed
with `ENOENT` before any BOOT bytes were sent. In this no-transfer control run,
the kernel recorded disconnection at 23:09:16.498553, about 3.07 seconds after
enumeration, matching the public OMAP4 USB boot-message timeout. The interface
was unconfigured; the corrected USBFS probe explicitly applies USB
configuration 1 before claiming interface 0. This control shows that the
earlier ~0.25-second disconnects were triggered by host interaction or its
timing, not a fixed background eMMC race. The byte-512 failure still needs
packet-level diagnosis. Evidence:
`evidence/rom-signed-mlo-usb-usbfs-first-2026-11-06.log` and
`evidence/rom-signed-mlo-usbfs-serial-2026-11-06.log`.

With USB configuration 1 explicitly set, the direct USBFS probe claimed
interface 0, sent BOOT and length, and received confirmation of the first 512
MLO bytes. A second 512-byte transfer 1.1 ms later failed with `EPROTO`. The
kernel recorded the ROM's USB removal about 0.248 seconds after enumeration;
the stock 2018 boot followed. The first-hand [OMAP3 USB sniffer investigation]
(https://www.downtowndougbrown.com/2025/11/debugging-beagleboard-usb-boot-with-a-sniffer-fixing-omap_loader-on-modern-pcs/)
documented a similar first/second-packet stall on a modern xHCI host, resolved
by waiting 1 ms **before every bulk transfer**. Our USBFS run sent BOOT,
length, and the first data packet without that pacing; it waited only between
data packets. One paced retry can test this transport explanation. The OMAP3
finding is an analogy, not evidence that OMAP4460 has the same bug. Evidence:
`evidence/rom-signed-mlo-usb-usbfs-configured-2026-11-06.log` and
`evidence/rom-signed-mlo-usbfs-configured-serial-2026-11-06.log`.

The 1 ms-before-every-write retry accepted BOOT and the size but rejected the
**first** MLO data packet with `EPROTO`. This did not reproduce the OMAP3
workaround; pacing also changed the rejection point, so a packet trace is
needed before making claims about the ROM parser. Linux `usbmon3` is available
and can capture a short, truncated bus-3 trace of a repeated unpaced baseline.
Evidence: `evidence/rom-signed-mlo-usb-usbfs-paced-2026-11-06.log` and
`evidence/rom-signed-mlo-usbfs-paced-serial-2026-11-06.log`.

A truncated `usbmon3` capture of another unpaced run showed the precise
transaction: BOOT and 41,628-byte size succeeded, the first MLO sector
completed with status 0, and the following 512-byte transfer beginning at
`CertPK_` completed with status **−32 (`EPIPE`, USB endpoint STALL)** and zero
bytes. The host submitted those four transfers within 0.22 ms. The endpoint
STALL is concrete; the trace alone cannot distinguish ROM first-sector
rejection from the documented OMAP-family xHCI timing failure. This PC has
EHCI controllers on buses 1 and 2 and xHCI on bus 3. Moving the service USB
connection to a genuine EHCI port provides the cleanest transport comparison
before altering signed image bytes or testing ROM bounds. Evidence:
`evidence/rom-signed-mlo-usbmon-summary-2026-11-06.txt` and
`evidence/rom-signed-mlo-usb-usbfs-usbmon-2026-11-06.log`.

The original OMAP4 USBBOOT host source sends `0xF0030002`, then a 32-bit
image length, then the entire first-stage image as one USB write; it uses a
1-microsecond delay only between the command, length and image. Its USB boot
description says a high-security device needs a properly signed first-stage
image. This confirms our command and length ordering, but does not establish
that Cisco's eMMC-format signed MLO is acceptable as a USB first-stage image.
The reference MLO's first 512 bytes are an outer TOC (`MLO`, `PRIMAPP`,
`KEYS`); its first certificate starts exactly at offset 0x200, which the
failed second transfer never delivered. The next transport test is the same
untouched image on the PC's EHCI controller. `tools/omap_rom_signed_mlo_probe.c`
now accepts `--usbfs-port BUS-PORT.2` and checks the adjacent Touch 10 FTDI
UART's VID, PID and serial before opening the ROM node, so the same pinned
probe can follow a cable move without addressing unrelated USB devices.
Source: <https://github.com/simu/usbboot-omap4/blob/master/tools/usbboot.c>
and <https://omappedia.com/wiki/Omapboot>.

On 2026-11-07, the owner moved the service USB cable to another rear port.
The Touch 10 FTDI UART moved from `3-2.1` to `3-1.1` (same serial
`D3081QEX`); the parent hub remains under **bus 3 xHCI**, while buses 1 and 2
remain EHCI with no Touch device. Thus the requested controller comparison has
not yet occurred and another identical signed-MLO attempt on this port would
not isolate the host-controller variable. The ASUS Z10PA-U8 manual documents
an `xHCI Mode` BIOS setting with Auto, Disabled, and Enabled choices, but
changing it would require a PC reboot and affect other USB devices. The image
format question should be resolved first. Board source:
<https://dlcdnets.asus.com/pub/ASUS/mb/Socket2011-R3/Z10PA-U8/QVL/E14884_Z10PA-U8_Series_UM_V5_WEB.pdf?model=Z10PA-U8>.

A format distinction raises the likelihood of image rejection: TI's secure
boot build documentation names **MLO** as the image for SD/MMC/eMMC and **ULO**
as the image for USB/UART peripheral boot. TI's OMAPBOOT notes likewise use
`generate_MLO` for storage and `generate_ULO` for a signed USB first stage
(the detailed example is for OMAP5, so its exact bytes must not be assumed for
OMAP4460). The Cisco reference contains an MLO, not a ULO. Its matching root
key is therefore insufficient to establish USB-image validity. We should
compare a genuine OMAP4 HS ULO header with this Cisco MLO before changing any
header bytes or interpreting the stall as a ROM exploit. Sources:
<https://android.googlesource.com/platform/external/u-boot/+/f7aa2094d4b1f8121384a030e95177327d873339/doc/README.ti-secure>
and <https://omappedia.com/wiki/Omapboot>.

A bounded volatile format comparison was then run on the new `3-1.2` ROM
path. The loader verified the exact reference MLO first, changed only byte
`0x14` of its outer TOC from `MLO` to `ULO` in host memory, then sent the
same BOOT command, 41,628-byte length, and 512-byte USB chunks. BOOT, size,
and the altered first sector succeeded; the second sector again failed
(`EPROTO`, errno 71). This one-byte name change did **not** advance the
transfer. It does not rule out a different ULO layout or host timing issue.
The serial capture terminated with the USB probe and contains only 17 bytes,
so this run provides no serial execution marker. USB evidence:
`evidence/rom-ulo-name-usb-2026-11-07.log`. The capture wrapper now retains
the passive serial recording for 45 seconds after future USB results.

The PC's USB host drivers are already built into its 7.3.1 kernel
(`CONFIG_USB_XHCI_HCD=y`, `CONFIG_USB_XHCI_PCI=y`, and
`CONFIG_USB_EHCI_HCD=y`). The FTDI and ROM appear below xHCI bus 3; EHCI
buses 1 and 2 are present. Loading an EHCI module would not move a port. Intel
documents a per-port xHCI/EHCI selector at PCI configuration offset `0xd0`
and a BIOS permission mask at `0xd4` for this C610/X99 chipset. Linux's PCI
USB quirk code sets those routing registers during controller startup. The
current command environment exposes only the first 64 PCI configuration bytes
even for an escalated read; `setpci -s 00:14.0 d0.l d4.l` returned
`ffffffff ffffffff`, so the mask and safe target bit cannot be established
here. A host-side, verified register change or the board's BIOS `xHCI Mode`
setting could provide an EHCI comparison. Changing the BIOS setting would
reboot the PC and affect its other USB connections. Sources:
<https://www.intel.com/content/dam/www/public/us/en/documents/datasheets/x99-chipset-pch-datasheet.pdf>,
<https://kernel.googlesource.com/pub/scm/linux/kernel/git/stable/linux-stable/+/master/drivers/usb/host/pci-quirks.c>,
and the ASUS board manual linked above.

#### OMAP4 peripheral image layout: `2ND` candidate

Two OMAP4 peripheral boot files are already in the local `omapboot` reference
tree: `images/lelus/p940-aboot.2nd` and
`images/wkpark/su760-aboot.2nd`. Both have the same three-entry outer TOC
structure as Cisco's 41,628-byte MLO: a first image item, `PRIMAPP`, and
`KEYS`; `CertPK_` is at `0x200` and `CertPPA` at `0xc00`. The first item is
named **`2ND`**, where Cisco's storage image says `MLO`. Across the first
512 bytes, only eight byte positions differ between the Cisco MLO and each
example: three for the item name, and five for the different item offsets and
sizes. Their signing keys do not match the target ROM's MPKH, so the example
images themselves are not candidates for execution on this Touch 10.

TI's secure U-Boot build rules explicitly offer `u-boot-spl_HS_2ND` for
peripheral boot, alongside separate `MLO` and `ULO` outputs. This makes `2ND`
a concrete OMAP4 format hypothesis; the earlier `MLO`→`ULO` rename did not
test it. An OMAP4460 HS OMAPFlash trace from an actual repair also shows a
`signed.2nd` file transmitted after the same ROM BOOT command and 32-bit
length. Its first 16 logged bytes fit the TOC offset/size pattern, though
the trace does not show the item name at `0x14`. Sources:
<https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/mach-omap2/config_secure.mk?id=bb7121f6aa644b72115a24f63d3ee6e52629cc99>,
<https://forum.gsmhosting.com/vbb/f777/guide-samsung-gt-i9100g-usb-boot-repair-1488048-print/?pp=50>.

A candidate derived from Cisco's MLO changes **only** bytes `0x14`–`0x16`
from `MLO` to `2ND` in RAM. The file on disk is untouched; everything from
the first certificate at `0x200` onward is byte-for-byte identical, and the
root-key record still hashes to the target ROM's MPKH. This does not prove
the ROM will accept the image or that its signature excludes the outer TOC.
Static comparison and SHA-256 are saved in
`evidence/omap4-2nd-layout-comparison-2026-11-07.json`.

`tools/omap_rom_signed_mlo_probe.c` now supports
`--usbfs-port-2nd-name BUS-PORT.2`, with the same original-MLO SHA-256,
certificate marker, and target FTDI serial checks as the prior mode. It was
compiled with `-Wall -Wextra -Werror`. `tools/rom_mlo_format_capture.sh`
locates the Touch 10's current USB bus/path after a host BIOS change and
records serial for 45 seconds after a one-shot `mlo` or `2nd` test. Neither
mode writes device storage. First confirm `lsusb -t` places the FTDI under
`ehci-pci` after the BIOS change, then run the untouched MLO as the transport
control; if it still stalls after the first sector, test the `2ND` variant on
a separate Touch 10 cold boot.

The owner changed the PC BIOS `xHCI Mode` to Disabled. `lsusb -t` then placed
the Touch 10 FTDI under EHCI bus 2, path `2-1.1.1`; the ROM appeared as
`2-1.1.2`. Three one-shot, RAM-only tests on EHCI followed. The untouched
Cisco MLO failed on the second 512-byte host write, and the `2ND` TOC rename
failed at that same transfer. A third test submitted the `2ND` candidate as
one continuous 41,628-byte USB bulk request, as the original OMAP4 host tool
does; usbmon recorded exactly **512 bytes delivered** and completion status
**−71 (`EPROTO`)**, while BOOT and size both completed. All three serial logs
show the unit proceeding to its installed 2018 MLO/U-Boot/Linux, with no
execution of the older reference loader. This substantially weakens the
xHCI-specific and host-write-chunking explanations.

The timing differs materially: the ROM USB device disconnected about 10 ms
after the original MLO first sector, but stayed enumerated for about 240–251
ms after either `2ND` attempt. This suggests the name changed first-sector
handling, but does not show that the ROM read a certificate (the first one
starts at byte `0x200`, which did not transfer). Possible remaining causes
include a `2ND`-specific TOC size/offset constraint, secure image metadata
outside the first sector, or an OMAP HS USB receive quirk. The host kernel and
usbmon evidence cannot distinguish these yet. Exact timestamps, outcomes,
and the filtered target-only packet capture are documented in
`evidence/rom-ehci-format-timing-2026-11-07.txt` and its linked evidence
files. A search of this workspace and public repositories found no verified
OMAP4460 boot-ROM binary; the available OMAP4 `.2nd` files are signed
second-stage images, **not** ROM dumps.

#### Bounded `2ND` header controls on EHCI

The hash-pinned 21,552-byte `p940-aboot.2nd` example provided a useful
receive-path control. The host declared its real length and sent only the
first 1,024 bytes, stopping well before a complete loader. Both 512-byte
sectors completed, and the ROM remained on USB waiting for the rest of the
image; the serial log contained no loader banner. The next cold power cycle
restored the installed firmware. The example's keys do not match this unit,
so this is evidence of **transfer progress**, not signature acceptance.

One-at-a-time RAM-only controls changed the declared length and the first
`2ND` TOC item's size so that its end matched that length. `PRIMAPP`, `KEYS`,
and certificate bytes in the transmitted 1,024-byte prefix stayed unchanged.
Only two sectors were ever offered:

| Declared length and first-item end | Second 512-byte sector | Result |
| --- | --- | --- |
| 21,552 bytes, original example | accepted | ROM kept waiting for payload |
| 24,576 bytes | accepted | ROM kept waiting |
| 28,672 bytes | accepted | ROM kept waiting |
| 31,744 bytes | accepted | ROM kept waiting |
| 32,768 bytes | rejected after first sector | installed firmware booted |
| 34,816 bytes | rejected after first sector | installed firmware booted |
| 41,628 bytes, Cisco first-item offset/span but small example `PRIMAPP` | rejected after first sector | installed firmware booted |

A separate 41,628-byte declared-length test with the example's original TOC
also stopped after its first sector. Thus the failure is not a universal
512-byte USB limit and cannot be attributed solely to Cisco's larger
`PRIMAPP`. The 34-KiB repeat rules out a failure unique to exactly 32 KiB.
The sharp observed transition between 31 and 32 KiB suggests a
peripheral receive-size or TOC-span boundary near `0x8000`; the controls
change both fields together, so they do not prove which ROM check rejects the
header. The 41,628-byte storage MLO cannot be transferred unchanged by this
observed `2ND` receive path. No complete loader ran and no firmware readback
was obtained. Captures are in `evidence/rom-foreign-header-*-usb.log`,
`*-serial.log`, and `*-target-only.pcap`; the filtered packet captures contain
only the Touch 10 ROM device. The transfer procedure is in
`tools/omap_rom_signed_mlo_probe.c` and `tools/rom_mlo_format_capture.sh`.

The later [Boot ROM disassembly](evidence/bootrom-static-audit-stage1-2026-11-07.md)
resolved this earlier uncertainty: at low-alias `0x33258`–`0x3325e`, the
non-type-3 receive path checks the declared length against
`0x4030bfff - 0x40304000 = 32767` bytes. This matches the 31,744-byte
acceptance and 32,768-byte rejection. The exact 41,024-byte CE9.9.0 MLO
also exceeds this single-image USB limit.

The Cisco MLO is tightly packed: `KEYS` ends at `0xb60`, `PRIMAPP` ends at
`0x3f9c`, and the signed first image begins at `0x4000`. Removing padding
cannot shrink it below the observed 32-KiB transition while preserving
these complete blocks. A read-only scan of the older 3.7-GB eMMC dump found
no `2ND\0` TOC name and therefore no embedded compact peripheral loader.
A smaller Cisco-signed loader from the same key family remains a possible
external lead, but none is in this workspace.

### Reboot and ROM-entry check against the older reference image

The earlier LAN reconnection was reported as a reboot by the owner; the saved
record does not show a host-issued reboot command. A captured boot log reports
`Last reset was cold reset (PRM_RSTST=0x1)`, consistent with a power cycle.

The older image's `support` sudoers rule permits passwordless
`/sbin/reboot`, `/bin/selectsw`, and `/bin/remotesupportuser`, but its
`supportsh` executable dispatches a fixed command map. IDA shows no `sudo`,
`reboot`, `shutdown`, or ROM-mode entry in that map. The live CE9.9.0 shell
explicitly answered `reboot: Unknown command`. The older `supportsh.wrapper`
selects `/bin/tsh` only for `/dev/ttyS*` consoles; this unit uses `ttyO2`.
The older `selectsw` script merely lists images with no argument; an image
argument can upgrade boot software and change the active symlink, and it has
no reboot-only option. Its handler calls `selectsw` without `sudo`.

The older MLO's extracted text includes normal primary/secondary/legacy
loader attempts and no visible ROM-mode request. The older U-Boot payload has
normal `bootcmd`/diagnostic/network-upgrade paths, but no visible command
that can be reached through the running support shell to request ROM USB
boot. These older binaries do not establish what the 2018 bootloader in the
unit can do internally.

As a read-only live check, `ip -batch /proc/sys/kernel/sysrq` returned
`No such file or directory` (`evidence/serial-sysrq-check.log`); there is no
evidence that a serial Magic SysRq reboot is available. An ordinary software
reboot would be a warm reset; the [OMAP44xx hardware manual]
(https://www.phytec.eu/fileadmin/legacy/downloads/Manuals/L760e_0_web_01.pdf)
says peripheral boot is normally not considered after warm reset. Thus a
reboot command would not reliably provide the observed cold-start USB ROM
window even if we could invoke it. The subsequent owner-assisted cold-cycle
probe is recorded below.

To test the actual security boundary without writing storage,
`tools/omap_rom_unsigned_probe.c` sends one unsigned raw ARM instruction over
USB after GET_ID: `b .` (`eafffffe`). This was an experimental input format,
not a proven valid OMAP4460 HS image. The guest instruction contains no storage
access and would only stop the CPU until the next power cycle if accepted. The
probe is fixed to the observed USB VID:PID and bus path, checks the 81-byte ASIC
response, and uploads no signed or older Cisco loader. It compiles with
`-Wall -Wextra -Werror`, and the fixed payload is four bytes. The test requires a
physical power cycle; the support shell rejected `reboot` as an unknown
command, and USB/Ethernet data connections cannot switch PoE power.

On the owner's first 2026-11-06 power cycle, the then-current probe found the ROM as
`0451:d010` at bus 3 address 16. `GET_ID` returned the expected 81-byte ASIC
identity. The `BOOT` command, 4-byte length, and 12-byte buffer each completed
as USB bulk transfers. That buffer incorrectly contained an 8-byte GP header
before `b .`; its first executable word was therefore `0x0000000c`. The serial
capture then showed the ordinary PPA, Cisco MLO, U-Boot, kernel load, and
`SEP24169DB677BB login:` prompt. This establishes that the transfer completed,
but it does not distinguish signature rejection from execution followed by an
exception or the normal eMMC boot path winning a race. The corrected four-byte
raw-code probe had not yet been run. No storage-writing payload was sent.
Evidence: `evidence/rom-unsigned-usb-second-2026-11-06.log` and
`evidence/rom-unsigned-serial-second-2026-11-06.log`.

The corrected raw-code probe was subsequently run. The ROM accepted GET_ID,
BOOT, a length of four, and the exact bytes `fe ff ff ea`; every bulk transfer
completed successfully. Serial output immediately showed the unit's stock PPA
1.8.5, Cisco MLO 1.41.0 built 2018-01-22, U-Boot, and Linux boot. Because an
executed `b .` cannot fall through to those stages, the HS boot path rejected
the unsigned image rather than executing it. This is a clean result for
unsigned execution, while leaving the signed-loader and receive-length paths
open for investigation.

The OMAP4 protocol implementation at
<https://github.com/kousu/omapboot> was downloaded for review at commit
`6057fa6100ffb3c1d1b26cfbf9c861526ff413d0` into
`firmware/reference/omapboot`. `OMAP.py` distinguishes `GET_ID=0xF0030003` from
`BOOT=0xF0030002`. Its included phone payloads have not been run and are not
board-specific loaders for this device.

`tools/omap_rom_identify.c` implements an identification-only probe scoped to
0451:d010 on bus 3, ports 2.2. Its sole outbound protocol payload is the four
little-endian GET_ID bytes; it sends no upload/boot request or payload and
contains no flash-writing code. Standard USB interface configuration/claiming
is transient. It saves the raw ASIC response locally and prints bounded block
metadata. The build passes `-Wall -Wextra -Werror`. Parser fixtures for a valid
block and truncated, oversized and zero-length blocks pass AddressSanitizer
and UndefinedBehaviorSanitizer with leak detection disabled (LeakSanitizer
cannot run under this environment's ptrace).

### Successful live identification

After KDE authentication and the owner's next power cycle, the probe opened
the device at bus 3, address 20. Interface 0 exposed bulk endpoints **0x81 IN**
and **0x01 OUT**, both with a 512-byte maximum packet size. GET_ID succeeded
and returned **81 bytes**, containing five complete TLV blocks:

| Type | Length including format byte | Observed content |
| --- | --- | --- |
| 0x01 | 5 | Format 1; model bytes 4440; CH byte 07; revision byte 01 |
| 0x13 | 2 | Format 1; payload byte 00; meaning not independently established |
| 0x12 | 21 | Format 1; 20-byte identifier, saved locally |
| 0x14 | 33 | Format 1; nonzero 32-byte MPKH block, saved locally |
| 0x15 | 9 | Format 1; eight CRC-related bytes, saved locally |

The ROM's 4440 model tag is recorded independently of the later PPA/Linux
OMAP4460 ES1.1 identification; the product string alone is not used to revise
the hardware identification. CH/revision bytes describe the ROM response and
must not be treated as the silicon revision without matching documentation.

Raw response: `evidence/omap-rom-asic-id.bin`; parsed blocks:
`evidence/omap-rom-asic-id.json`. Raw-response SHA-256:
`50805f20c5ecdb0b62d8045d30a44a451b4b3831aa17042f20fdb867b61e3328`.

`evidence/control-rom-identify-serial.log` confirms that after this query the
unit continued through the same MLO/U-Boot to kernel decompression and a Linux
login prompt. No BOOT command, image length or code payload was sent. This
establishes ROM protocol communication, **not arbitrary code execution, root,
or a firmware backup**.

The older reference MLO contains CertPK_ at file offset 0x200, CertPPA at
0xc00, and CertISW at 0x4000. The public RSA root-key record begins at MLO
offset **0x234** and is 276 bytes: five 32-bit metadata fields followed by a
256-byte modulus. SHA-256 over those exact 276 bytes is
`8b846a5a4bd78d86fdbeee1c4ce0ed074e91b9f501f80652d1b6084b1c0fa742`,
**identical to the ROM's MPKH block**. This corrects the earlier incomplete
candidate-layout comparison, which omitted the 276-byte record. The
reproducible local-only check is `tools/check_rom_mlo_key.py`; result:
`evidence/reference-mlo-rom-mpkh-match.json`. The older reference MLO's first
stage therefore contains the root public key corresponding to this device's
reported trust-anchor hash. This does **not** establish that the complete
older image will satisfy version, certificate, rights or board compatibility
checks; no loader has been uploaded or executed.

The record layout was checked against the reference MLO's marker and fields
(key ID 1, type 0x30000, rights 1, modulus length 256, exponent 65537). An
independent [certificate reverse-engineering script](https://github.com/XVilka/hacklu/blob/master/demos/Firmware/demo1_arm_boot/motorola-crypto.py)
describes the same CertPK root-key structure; it is for a different OMAP-based
product, so the exact hash equality above is the stronger local evidence.

The reference CertPPA header points to a 12,736-byte image within the MLO;
CertISW points to a 24,396-byte image ending exactly at the MLO's 41,628-byte
file boundary. These are consistent with an integrated boot chain rather than
a standalone flash-read command. Before any RAM-only boot attempt, the PPA and
ISW behavior and possible writes need further review. The priority remains a
verified backup of this unit's own flash.
IDA's read-only string inventory of the reference ISW showed MMC initialization,
primary/secondary/legacy bootloader reads, and signature/hash errors. It did
not reveal a readback service. Strings alone cannot establish that the binary
performs no writes.

### Backup decision after the ROM comparison

The exact MPKH match makes the older signed MLO relevant to authentication
research, but uploading it would execute a different firmware's boot code and
could still fail version or board checks. It has not been used as a backup
method. The ROM GET_ID exchange offers no demonstrated eMMC or EEPROM read
operation. Running `selectsw` with an image argument is also unsuitable: the
older reference script explicitly invokes `upgradebootsw` when the selected
image carries boot software, before changing the active-image link.

Hardware readout was considered because a [first-hand Touch 10 hardware
investigation](https://wiki.taktpraha.cz/profile/trimen/ciscohax) obtained an
older unit's raw eMMC image after chip removal. The owner has ruled out opening
this unit, so the current investigation uses the serial and Ethernet interfaces.
That older dump is neither a backup nor the exact firmware of this unit.

KDE/polkit authentication granted host access for this bounded identification
probe. It exited successfully after receiving the identity response. The
associated passive serial capture was then stopped to free the console.
The subsequent guarded support-console check confirmed normal Linux boot,
`image2 - ce9.9.0 46f7ea38fda` still active/selected, and `eth0` up with
MAC 24:16:9d:b6:77:bb at 192.168.1.161/24. The session then exited to login;
see `evidence/rom-probe-postboot-check.log`.

## Latest control investigation

The owner connected Ethernet to the PC's LAN and reported an ordinary reboot.
After re-entering the support shell, the unit still reported CE9.9.0
46f7ea38fda. Its Ethernet MAC is unchanged and DHCP assigned **192.168.1.161/24**,
gateway 192.168.1.1; the PC uses 192.168.1.151 on this LAN. Earlier NO-CARRIER
observations below describe the previous connection state.

The device reports TCP listeners only on loopback. From the PC, targeted
connections to ports 22, 23, 80, 443, 873, 1300, 1305, 4043-4048, 4051, 4060,
5555 and 64777 were all refused. The target and results are saved in
`evidence/lan-target-ports.json`. No other LAN host was scanned.

Controlled command-execution checks with `/usr/bin/id` did not launch a process:
`ip netns exec` rejected the namespace path and `ip vrf exec default` failed
with permission denied creating `/var/run/cgroup2`. These were permitted
temporary process-state tests, not attempts to modify installed software.
`bootlogo --help` returned a read-status error, and no on/off argument was sent.
This does not establish the absence of every possible shell escape.

The read-only `ip -batch` reader successfully opened the empty `/tmp/releasesw`
marker, while `/config/sysconfig/rootsettings` was absent. This is live evidence
consistent with the production root gate found in the older reference. The
numeric `route_localnet` sysctl paths were also absent. No contents from a
potentially executable batch file were supplied as network configuration.

The older reference getty was decompiled: it calls login with `--` before the
username, so that binary does not suggest a login-option injection path. No
crafted username test was performed on the device. Analysis is saved in
`evidence/reference-getty-decompiled.txt`.

The Ethernet reboot invalidated an old console session; a queued diagnostic
batch initially reached a login prompt. It was cancelled and the support
account re-entered. `serial_probe.py --support-commands` now checks for a
support prompt before sending each requested command. A PTY fixture verified
that a simulated return to login prevents subsequent commands from being sent.

The bootloader capture and bounded interrupt test described above supersede
that earlier proposed diagnostic.

The first three-minute passive capture ended without receiving any bytes; no
bootloader behavior can be inferred from that. The later power-cycle capture
is saved in `evidence/control-bootcapture.log`.

## Service-console capability and vulnerability review, 2026-11-06

The FT230X USB UART exposes a Linux login on `ttyO2`. Passwordless `support`
reaches the restricted `supportsh` command dispatcher, not a general shell.
The live command map is `bootlogo`, `bye`/`exit`/`quit`, `head`, `help`, `ip`,
`netstat`, `selectsw`, `show`, `tail`, `tailf`, and `uname`. `show` lists only
`messages`, `console`, `dmesg`, `kern`, `main`, and `touchmenu`. The three file
readers use those same aliases. `bootlogo on/off` changes a setting and was
not invoked; `selectsw` with an image argument can switch software and was
not invoked. `tailf /etc/passwd` returned `Unknown file`, confirming its
alias restriction; it is not a file-transfer command.

The running `ip` is iproute2 `ss190708`; `netstat --help` identifies BusyBox
1.28.2. `ip netns list` was empty and `ip vrf show` reported no VRF, matching
the earlier failed `netns exec` and `vrf exec` tests. The shell rejects `;`
in `ip` arguments, while a benign single-quoted argument to `ip -V` returned
only the version. This does not prove complete input safety, but no command
injection has been demonstrated. `netstat -xan` lists local syslog, D-Bus,
netman, and udev sockets; `netstat -lntup` still cannot map process names as
the support user. Its TCP listeners are loopback-only.

`ip -batch` opens ordinary readable text files, and `-force` processes all
lines. When it rejects a line, it echoes only the first token and line number.
This revealed account names from `/etc/passwd` and the eMMC sizes from sysfs:
`mmcblk0` 7,733,248 sectors and both boot areas 4,096 sectors each. It does
not provide a byte-preserving or arbitrary block-device backup method. The
metadata probe did not attempt to parse eMMC bytes as `ip` commands, which
could have unintended network effects.

### Live eMMC map and diagnostic-partition lead

Read-only `ip -batch` requests against sysfs exposed the eMMC's CID, CSD,
model, serial and partition geometry without reading block data. The unit's
`mmcblk0` user area has **7,733,248 512-byte sectors (3,959,422,976 bytes)**;
both separate boot areas have 4,096 sectors (2 MiB) each. The full 16-partition
map, including checked byte offsets and lengths, is in
`evidence/service-storage-layout-2026-11-06.json`. Raw console evidence is in
`evidence/service-storage-identity-2026-11-06.log`,
`evidence/service-partition-map-2026-11-06.log`, and
`evidence/service-partition-geometry-2026-11-06.log`. This is metadata, **not
a firmware backup**. The boot log reported an invalid alternate GPT, so a
future raw backup should preserve the whole user area and verify both GPTs.

The live partition **p10 is named `diag_system`**, at sectors 326,912 through
457,983 inclusive (64 MiB). Its partition number, position, and size match
the older TI7.3.3 reference dump, but its **contents on this CE9.9.0 unit have
not been read**. The older reference's p10 was extracted offline with
`dd bs=512 skip=326912 count=131072`; SHA-256 of that 64 MiB reference
partition is `096a534f534f7a9614d716dc34675c217c863edce3979c97471610549c927d82`.
It is a U-Boot uImage titled `Foxconn diagnostic 20141105`, containing an
Android-style boot image and a 128 MiB ext2 ramdisk. The reference ramdisk's
`/etc/inittab` respawns `/bin/sh -l` directly on `ttyO2`; its root passwd entry
has an empty password field. If an equivalent image were booted, the serial
console could provide a root shell able to read the unit's eMMC. This is an
inference from **the older image**, not a verified access path on the unit.

The older U-Boot default environment contains
`bootdiagnostic=booti mmc 1 10 0x84000000`. Its `bootcmd` calls that command
only if `diag_booting` equals `BOOTING_DIAG_IMAGE`; its default is
`diag_booting=0`. The exact string `diag_booting` occurs only in those two
default-environment records of the extracted older U-Boot payload and not in
the reference MLO. No matching setter was found in the older extracted Linux
files. The recovered CE9.9.0 factory package now includes a signed 2018
U-Boot image; its equality to the bytes installed on this panel has not yet
been verified. No live command or documented button sequence has been
established to select p10. Changing
U-Boot environment would write persistent state before backup, so it has not
been attempted.

The live `/etc/uboot.conf` still says `UBOOT_DEVICE=/dev/mtd0` and
`UBOOT_ENV_OFFSET=0x100000`, exactly as in the older root filesystem. But the
live kernel has no `/proc/mtd` or `/sys/class/mtd/mtd0` entry, while the older
U-Boot binary contains `env_mmc.c` and `Writing to MMC(%d)...` strings. This
configuration file therefore does **not** establish a readable Linux MTD
bootloader device or the installed environment's location. Console evidence:
`evidence/live-uboot-config-2026-11-06.log` and
`evidence/live-mtd-identity-2026-11-06.log`. The normal boot reports an
environment CRC failure and uses built-in defaults, but the installed U-Boot
defaults have not been extracted.

The older diagnostic image is not yet established as a no-write boot path.
Its `inittab` mounts the ramdisk read-write, starts udev and Wi-Fi/Bluetooth
setup, and has the storage-remount script commented out. But the login shell
sources `/etc/profile`, which starts a test CLI, a Telnet server and helper
programs. The `make_bin_file.sh` helper can read the first 3 MiB of eMMC to a
USB file if invoked; recovery and TFTP upgrade helpers would write cache.
Those helpers were not identified as automatic `inittab` jobs, but binary
test-program behavior and the current partition contents remain unverified.
Therefore even a seemingly RAM-based diagnostic boot needs further side-effect
review before use for the initial backup.

IDA review and local ARM emulation of the older TI7.3.3 `supportsh` show a
fixed 11-command map (the live shell adds `bootlogo` and `tailf`), six fixed
log paths, bounded `fgets` calls, and an OS-command wrapper that rejects
common shell control characters before invoking `bash -l -c`. No usable
readback or shell escape was established from that older binary. It is not
binary evidence for the installed CE9.9.0 shell. Cisco's published
[CLI privilege escalation advisory]
(https://www.cisco.com/c/en/us/support/docs/csa/cisco-sa-20191106-telepres-roomos-privesc.html)
describes SSH connection arguments and releases before CE9.8.1. Its
[remote-support process advisory]
(https://www.cisco.com/c/en/us/support/docs/csa/cisco-sa-20190821-roomos-privesc.html)
lists fixes by CE9.7.3/CE9.8.0. Neither establishes an exploit for this
CE9.9.0 serial session, and there is no external SSH listener.

Evidence: `evidence/service-interface-inventory-2026-11-06.log`,
`evidence/service-interface-file-read-2026-11-06.log`,
`evidence/service-interface-argument-check-2026-11-06.log`, and
`evidence/service-interface-sockets-2026-11-06.log`, plus
`evidence/service-interface-tailf-2026-11-06.log`.

### BusyBox 1.28.2 vulnerability applicability

The live `netstat --help` banner identifies BusyBox 1.28.2, but a version
string alone does not reveal Cisco's patch set. The reachable `netstat`
applet falls in the published ranges for two terminal-output issues:

- [CVE-2022-28391](https://security-tracker.debian.org/tracker/CVE-2022-28391):
  a malicious DNS PTR result can place escape sequences in `netstat` output
  when name resolution is used. Our `netstat -n` runs do not resolve names.
  The affected terminal is on the operator side of the serial connection;
  this does not by itself execute code as root on the Touch 10.
- [CVE-2024-58251](https://www.cve.org/CVERecord?id=CVE-2024-58251):
  an attacker-controlled local process name can put escape sequences in
  `netstat -p` output and lock a terminal. The restricted shell does not
  provide a way to launch such a process, and `netstat -p` cannot map
  processes as `support` on this unit.

The 2021 [Claroty/JFrog BusyBox findings]
(https://claroty.com/team82/research/unboxing-busybox-14-vulnerabilities-uncovered-by-claroty-jfrog)
primarily involve `awk`, `hush`, and other applets receiving crafted input.
The console's fixed command map does not expose those applets. BusyBox
dispatches applets by executable name (or by invoking the `busybox`
multiplexer), so adding `awk` as an argument to `netstat` does not invoke
`awk`. In the older reference root filesystem, `/bin/sh` is a symlink to
`bash`, and `supportsh` explicitly launches Bash, so BusyBox shell bugs do
not describe that older command path. Even a code-execution bug in the running
`netstat` process would first yield the unprivileged `support` identity; its
output says it cannot inspect
root-owned process information. No BusyBox-based privilege escalation or
backup method has been demonstrated here.

### Exact CE9.9.0 kernel, libc, and shell audit

The recovered factory package's kernel embeds its build configuration, now
saved as `evidence/ce990-kernel-config-2026-11-07.txt`. Its version string
matches the live boot log exactly: Linux **3.4.113+**, built 2019-09-17.
The config disables namespaces, keyrings, and DCCP. The upstream 3.4.113
release includes the Dirty COW GUP race fix. AF_PACKET is compiled in, but
known local escalation paths through it require `CAP_NET_RAW`, which the
restricted `support` console has not demonstrated and cannot obtain through
user namespaces on this build. GhostLock (CVE-2026-43499) is a stronger
lead: this build enables futexes and RT mutexes, and upstream Linux 3.4 has
the vulnerable `remove_waiter()`/proxy-lock path. Its exact compiled Cisco
code and ARM32 exploitation remain unverified. It requires local program
execution before it can help with root access.

The rootfs has glibc **2.29**, Bash **3.2.57**, and BusyBox **1.28.2**.
Offline execution of the exact Bash rejected the classic Shellshock payload.
The exact CE9.9.0 `supportsh` binary has a fixed command map and a bounded
first-token buffer; IDA review found no established escape from the mapped
`ip`, `netstat`, or `sudo selectsw` commands. The package also contains a
setuid-root **sudo 1.8.21**, in the published range for CVE-2021-3156.
That is a credible second-stage local escalation candidate if we first gain
arbitrary unprivileged code execution, but the current service console
cannot invoke `sudoedit -s`, and no ARM exploit has been validated. The two
setuid package binaries lack the `$ORIGIN` RPATH required by newer glibc
loader flaws. Full evidence and primary sources are in
`evidence/ce990-local-escalation-audit-2026-11-07.md`.

A second decompilation pass covered every exact `supportsh` file and EEPROM
handler. `show`/`head`/`tail`/`tailf` resolve six fixed log aliases; the
apparent second token-buffer offset is in bounds. `historiclogs` is compiled
but absent from the command table. The exact root-running `selectsw` script
has no established command escape from its image argument and switching an
image can write boot state. Its extracted script is at
`firmware/codec-ce9.9.0/analysis/touch10-ce990-selectsw`.

A focused memory audit of the same binary found an infinite multi-file
parser loop (`show main kern`) and an uninitialized descriptor close in
`tailf` after an early file-open failure. Off-device QEMU reproduced both;
282 bounded/randomized console inputs and 21 successful file
reads produced no crash. Neither defect provides a root foothold. See
`evidence/ce990-supportsh-memory-audit-2026-11-07.md`.
Further QEMU testing found 15 looping two-alias combinations and confirmed
that Ctrl+C does not break the loop. The `tailf` early-failure cleanup can
close stdin or stdout; the panel's `main` log alias was absent in prior live
evidence, making that failure path plausible on-device. Neither sequence
was sent to the panel.
When `tailf` closes stdin, `main` repeatedly retries `fgets` because
`feof(stdin)` stays false; off-device it emitted 221 KB of prompts in
0.2 seconds without a buffered `quit`.

## Live results

- The passwordless `support` account still works.
- One additional blank root password was tested with LF termination after
  explicit user approval. It returned `Login incorrect`. Earlier CR-only input
  had not produced a clear authentication result. No password list or brute
  force was used.
- `head /etc/passwd` returns `/etc/passwd: Unknown file`; it is an alias-based
  log viewer rather than unrestricted filesystem access.
- `systemtools rootsettings get` returns `systemtools: Unknown command`.
  Codec instructions for that command cannot be applied through this shell.
- `netstat -lntup` reports that it cannot inspect processes without root and
  shows TCP listeners only on loopback, at ports 53, 1300, 1305 and 64777.
  There is no currently observed external SSH listener.
- The earlier `NO-CARRIER` result preceded the owner's LAN connection. Ethernet
  now has carrier and address 192.168.1.161/24.
- The startup log confirms signature verification, a 1280x800 Qt/KMS display,
  `/mnt/base` on mmcblk0p14, writable config/user images, and secure-storage
  mounting on mmcblk0p9. It names the GUI `Phoenix`.

Evidence files: `root-investigation-lf.log`, `root-support-investigation.log`,
`support-capabilities-02.log` and `network-recheck-02.log` under `evidence/`.

## Offline findings, from the older reference firmware

These are useful leads and are **not a binary-level verification of CE9.9.0**.
The reference `apps.img` and `tools.img` were read with 7-Zip. Executable analysis
used IDA; no reference executable was run.

The reference starts a `support` account with UID/GID 2. Its shell is the
restricted `supportsh`, not a root shell. The sudoers fragment allows only
reboot, software selection and a remote-support helper; it does not grant
unrestricted sudo. Software selection can update boot software and change the
active-image symlink, so it is unsuitable for a backup-before-changes approach.

The reference authenticates root through `libnss_root.so.2`, ahead of ordinary
passwd-file lookup. Its `is_login_allowed` checks `/tmp/releasesw`; the presence
of that production-release flag denies root login. Without it, a
`ROOTSETTING=on` value in `/config/sysconfig/rootsettings` can permit login;
the hash is read from `ROOTPW` in the same configuration file. Therefore an
initially empty root entry generated by `rc.sysinit` is not evidence that a
production device permits an empty root password.

The reference's `S01release` creates the production-release marker. Its
`S05setup_ssh` disables SSH on production builds unless an explicit marker or
boot argument enables it. This is consistent with the live lack of SSH, but
the actual CE9.9.0 policy still needs its own binary/configuration evidence.

Reference supportsh uses fixed file aliases for its file commands. Its OS
command wrapper checks allowed characters before calling a shell. Inspection
did not establish a usable read-only escape. It does not prove that the newer
shell has no vulnerabilities. Saved analyses:

- `evidence/reference-supportsh-decompiled.txt`
- `evidence/reference-root-nss-decompiled.txt`

The reference rsync daemon is disabled by default and exports `/upgrade`, not
the whole root filesystem. It does not establish a firmware readback service.

## Next access paths

The owner subsequently connected the injector's data port to the PC's LAN.

The remaining `bootlogo` command is documented as an on/off setting, so it was
not invoked. Only its help entry was read. No additional login credential
tests were made during this USB-only follow-up.

An alternative using `ip vrf exec` was reviewed in matching-era upstream
iproute2 v5.2.0 source. Its execution path first mounts/finds cgroup v2, creates
a cgroup path and writes `cgroup.procs`; it is not a read-only escape and was
not attempted. This is source-level review, not an examination of the exact
Cisco `ip` executable. The source was saved at
`firmware/reference/upstream/ipvrf-v5.2.0.c` from
<https://raw.githubusercontent.com/iproute2/iproute2/v5.2.0/ip/ipvrf.c>.

Cisco's [Room Kit Plus CE9.9.0 software catalog]
(https://software.cisco.com/download/home/286316402/type/280886992/release/CE9.9.0)
identifies the exact build bundles
`cmterm-s53200ce9_9_0-46f7ea38fda.k3.cop.sgn` (892.58 MB) and
`cmterm-ce9_9_0-46f7ea38fda.k3.cop.sgn` (2818.31 MB), both dated
2019-10-22. The catalog labels them `Login and Service Contract Required`;
its Deferral Notice says this release cannot be downloaded because it has
been deferred. Cisco's [January 2020 deferral notice]
(https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/software/ce9/release-notes/TC7-CE8-CE9-deferral-notice.pdf)
explicitly includes CE9.9.0 and attributes the withdrawal to
CVE-2020-3143, an authenticated **video-endpoint xAPI** path traversal that
can read and write files. It requires an In-Room Control or administrator
account; the Touch's service shell is not the codec xAPI and no external xAPI
listener has been observed on this panel. The notice therefore does not
establish a Touch 10 root or readback route. Cisco's
[Codec Plus CE9.15 administrator guide]
(https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/ce915/codec-plus-administrator-guide-ce915.pdf)
explains that Room Series COP files include separate peripheral PKG files,
so these are plausible containers for a matching Touch payload, but their
COP contents have **not** been acquired or inspected. The matching peripheral
PKG was subsequently recovered directly from the offline codec, as detailed
at the top of this report. A later package might provide a comparison image,
but it would not be a backup of this unit.

On 2026-11-07, the catalog was checked in a browser. It still listed both
CE9.9.0 COP files above with a Deferral Notice. The visible CE9.15.6
StepUpgrade entry was `s53200ce9.15.6-step-upgrade.pkg` (785.78 MB); clicking
Download produced a modal requiring Cisco login **and** a service contract.
That standalone Room Series PKG is a less useful research target for the
Touch: Cisco's [Room Kit CE9.15 administrator guide]
(https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/ce915/room-kit-administrator-guide-ce915.pdf)
says Room Series COP files contain separate video-device and peripheral PKGs,
whereas the video-device PKG alone lacks the peripheral images. A later COP
would be useful for structural comparison if legitimately obtainable, but its
Touch payload would not match the installed CE9.9.0 build.

The `.sgn` suffix establishes a signed COP wrapper, not by itself payload
encryption. A [firsthand CE9.14.5 extraction report on Cisco Community]
(https://community.cisco.com/t5/telepresence-and-video-infrastructure/error-message-when-upgrading-cisco-webex-kit-pro/m-p/4277054)
opened a `.k3.cop.sgn` with 7-Zip, then opened the nested `.cop` and extracted
an inner codec `.pkg`. Thus at least that release's **outer** layers are
readable. We have not inspected a CE9.9.0 COP. The Touch-specific PKG recovered
from the codec is readable and contains unencrypted boot and filesystem images;
its COP wrapper format remains untested. The older TI7.3.3 eMMC dump also
contains readable installed image files.

An exact-filename/build search on 2026-11-07 found no indexed public copy of
`cmterm-s53200ce9_9_0-46f7ea38fda.k3.cop.sgn`, and a local search of
`~/Downloads` and `~/ext_proj` found no COP or PKG. Cisco's
[CE9 release notes](https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/software/ce9/release-notes/ce-software-release-notes-ce9.pdf)
state that CE9.x through 9.9.1 is deferred and removed from downloads.
For a legitimately obtained COP, the [open-source `stripsgn` implementation]
(https://raw.githubusercontent.com/usecallmanagernz/certutils/master/stripsgn)
shows a Cisco `.sgn` wrapper as a short TLV header followed by archive data;
this is a format lead to verify on an actual COP. At the time of that search,
no package had been downloaded. The matching Touch PKG was later obtained
from the offline codec; no package was installed.
An Internet Archive search for the exact COP filename stem and the build ID
`46f7ea38fda` returned zero catalog items. Wayback reported that the exact
Cisco CE9.9.0 catalog URL was not archived; its CDX binary index was
temporarily offline during the check. This does not rule out a COP embedded
as an unindexed file in another archive item, but no verifiable archive copy
was found.

### Nearest CE9.9.0 comparison packages and update source (2026-11-07)

Cisco's Room Kit Plus catalog identifies the nearest chronological release
before this panel's `CE9.9.0.46f7ea38fda` as
[`CE9.8.1`](https://software.cisco.com/download/home/286316402/type/280886992/release/CE9.8.1),
dated 2019-09-05. Its Room Series COP is
`cmterm-s53200ce9_8_1-0f71ac008c3.k3.cop.sgn` (811.46 MB). The next
chronological release is
[`CE9.9.1`](https://software.cisco.com/download/home/286316402/type/280886992/release/CE9.9.1),
dated 2019-12-06, with
`cmterm-s53200ce9_9_1-47f2e107480.k3.cop.sgn` (892.83 MB).
`CE9.8.2` also released on 2019-12-06, so although its version number is
lower, it is not a predecessor in release time. Cisco labels the two nearest
COPs `Login and Service Contract Required` and gives them Deferral Notices.
Its [CE9 release notes](https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/software/ce9/release-notes/ce-software-release-notes-ce9.pdf)
say CE9.x through CE9.9.1 was deferred. Searches for the exact filenames and
build IDs found no public copy, and Internet Archive catalog searches for
Touch 10/TelePresence/Room Kit firmware found no relevant item. These are
identified targets, **not acquired images**. The TI7.3.3 eMMC dump remains
the only complete *raw-flash* Touch 10 reference locally; the exact CE9.9.0
factory PKG has now been recovered from the codec.

Per Cisco's [SX80 administrator guide](https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/ce83/sx80-administrator-guide-ce83.pdf),
the Touch 10 downloads its software from a paired codec automatically during
setup if their versions differ. It does not document direct Touch-to-Cisco
firmware updates. A [cloud-registered Room Series codec](https://help.webex.com/en-us/article/d67ai1/Software-upgrades-on-Board%2C-Desk%2C-and-Room-Series)
can update automatically from Webex; an [on-premises codec](https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/ce915/codec-plus-administrator-guide-ce915.pdf)
with cloud upgrades disabled uses local provisioning or manual packages.
Neither path gives a standalone Touch 10 an update download. Cisco says a
free Cisco.com account grants access to unrestricted software, while these
COPs require an associated service contract; it directs secondhand equipment
owners to [Customer Service or an authorized partner](https://web-help.cisco.com/faq)
to ask about eligibility. The [Cisco Cloud Upgrader](https://upgrade.cisco.com/)
describes IP phones and desktop video systems, not standalone Touch 10 panels.
A public Webex CDN URL observed in a Cisco support log for a later codec
`sunrise.pkg` returned HTTP 403 `AccessDenied` to both HEAD and a 1 KiB range
GET from this PC; this does not establish anonymous availability of CE9.9
packages. No update was initiated on this unit.

### Offline codec package readout, completed

The owner connected the original seller-tested codec without Internet.
The older Touch 10's `firmware/reference/tools/bin/swsync` reads
plain text on codec TCP 4045: `version:`, `method:`, `url:`, and `targets:`.
For a version mismatch, it fetches the advertised URL by `rsync` or HTTP
into `/upgrade/pkg`. Cisco's [CE9.9 port guide](https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/ce99/sx10-administrator-guide-ce99.pdf)
independently labels TCP 4045 as remote pairing version information and
4043 as software download. This gave us the exact Touch software **from the
codec**, before connecting the panel. The current CE9.9 panel did connect to
our simulated TCP 4045 endpoint earlier, but its package-fetch behavior was
not exercised.

`tools/probe_codec_package.py` is the read-only TCP 4045 probe used here; it
was first tested against a loopback mock. The codec was found at
`169.254.1.1`, and the exact package was copied and hashed as described above.
This factory image is not a backup of this panel's unique partitions or
configuration. A local codec can update a Touch 10 without Internet if their
versions differ, per Cisco's Touch setup guide; the prior seller pairing did
not by itself prove the two still match, though this codec and panel both
reported CE9.9.0 `46f7ea38fda`.

Once a general shell is available, a serial-only backup is technically
possible. At 115200 8N1, 4 billion raw bytes take about 96.5 hours before transfer
protocol overhead. Compression can reduce this substantially, but cannot be
estimated reliably from the older unit's dump. Small EEPROM and boot-area
backups should come first. The serial port's existence alone does not grant
block-device read permission.

1. Keep the current data connection away from a Cisco codec to avoid automatic
   software changes. Continue bounded, read-only serial and LAN investigation.
2. Trace the installed bootloader's diagnostic selector and determine whether
   p10 still contains a usable image, without writing the U-Boot environment.
   The older reference's `diag_system` root shell is the strongest current
   software-only lead, but its selection and startup side effects are unknown
   on CE9.9.0.
3. Obtain the exact CE9.9.0 Touch payload or corresponding vendor source to
   inspect its actual authentication, diagnostics and pairing implementation.
   The older TI7.3.3 dump cannot establish a safe current-firmware exploit.
4. Obtain software readback of this unit's eMMC and EEPROM before any firmware
   change. Hardware access is outside the owner's stated scope.

## UPnP discovery probe

Passive capture shows this Touch sends UPnP M-SEARCH requests. A bounded local
probe replied once per run with a unique, non-Cisco UPnP Basic device and served
only an XML description. The Touch fetched the description from this PC. A
complete benign description and 240-character friendly name or 300-character
serial number caused no observed daemon restart or software change. A description
with an external DTD was fetched, but no DTD request reached the local server;
that observation does not prove all XML external-entity paths are disabled.
Evidence is in `evidence/touch10-ssdp-*.json` and the matching postcheck logs.

IDA review of the **older TI7.3.3** `upnpdiscoverer` found unbounded string
copies into fixed fields after XML download. The exact CE9.9.0 factory package
instead uses `upnptool`. In that binary, the inspected SSDP and HTTP response
copies use explicit lengths, and XML is parsed by Expat 2.2.7. Thus the old
fixed-field copy is not established here. Off-device testing of the package's
Expat confirms it accepts malformed UTF-8 tag names from the upstream
CVE-2022-25235 regression tests. Whether `upnptool` mishandles those names
remains untested. See `evidence/ce990-network-parser-audit-2026-11-07.md`.
No root access or firmware readback resulted.
An additional direct-link probe used Cisco-like display labels in a dummy
Basic-device XML, with no pairing or upgrade endpoints. The Touch fetched the
document but made no subsequent request; the active image was unchanged.
Evidence: `evidence/touch10-direct-ssdp-codec-labels-2026-11-06.json` and
`evidence/post-codec-labels-2026-11-06.log`.

### Cisco Touch 10 pairing and downgrade advisories

Cisco's [CVE-2022-20793 advisory](https://www.cisco.com/c/en/us/support/docs/csa/cisco-sa-CTT-IVV-4A66Dsfj.html)
says an unauthenticated party can impersonate a legitimate codec in response
to a Touch 10 pairing broadcast. It covers TelePresence CE software, but does
not provide a per-release fixed-version table for this unit. The attack needs
user interaction according to its CVSS vector, and the advisory describes
unauthorized access to the panel as a codec, not a shell or eMMC readback.
Cisco's [CVE-2022-20931 advisory](https://www.cisco.com/c/en/us/support/docs/csa/cisco-sa-CTT-DAV-HSvEHHEt.html)
explicitly lists CE releases earlier than 10 as affected by a downgrade flaw;
CE9.9.0 is in that range. A downgrade writes firmware, so it is outside the
owner's backup-before-changes sequence.

Cisco's [CE9.15 codec port guide](https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/ce915/sx10-administrator-guide-ce915.pdf)
identifies codec-side TCP 4043 as software download, 4045 as version
information, 4047 as a paired session, and 4053 as a pairing port. These are
not listeners observed on the Touch 10. A bounded direct-link probe advertised
an inert local `http://10.77.10.1:4053/` presentation URL in a benign UPnP
description and served no pairing or software endpoint. The Touch fetched the
XML twice; its `Phoenix` log then reported `UPnP discovered  with address
"10.77.10.1"`. The name between `discovered` and `with` was blank, so this
does not establish a valid codec identity or completed pairing. No further
HTTP request was observed, and CE9.9.0 remained active/selected. The temporary
DHCP server was stopped. Evidence:
`evidence/touch10-codec-presentation-2026-11-06.json` and
`evidence/post-codec-presentation-2026-11-06.log`.

A second 35-second exchange was packet-captured on the isolated PC link. Its
22 packets include a single HTTP connection from the Touch to port 18080 for
the XML. There was no observed TCP attempt to 4043, 4045, 4047, 4053, 4060,
or another pairing/download port in that window. The subsequent UI log did
not show a completed pairing, and CE9.9.0 was still selected. Evidence:
`evidence/touch10-codec-discovery-traffic-2026-11-06.pcap`, the extracted
`evidence/touch10-codec-discovery-tcp-2026-11-06.txt`, and
`evidence/post-codec-traffic-2026-11-06.log`. The observation is bounded to
this descriptor and window; the panel may make additional requests if a user
selects a codec.

In the older reference image, `firmware/reference/apps-full/etc/pairing.conf`
labels TCP 4053 as the remote *initial pairing* port, 4051 as the remote
session port, and 4052 as logging. Its `pairingc` binary accepts a codec
address, a certificate/private-key pair, optional username/password, and a
server-certificate output path, and imports OpenSSL TLS functions. That is
protocol context for the older image, not evidence that CE9.9.0 would expose
a shell or eMMC readback after pairing. The live capture did not reach this
stage.

### Owner-approved initial connection, 2026-11-06

The owner selected the isolated PC's discovered address on the Touch 10 and
stopped before supplying credentials or approving software. A fixed local
listener accepted TCP 4045 (version information) and 4053 (pairing), bound
only to 10.77.10.1 and scoped to the Touch's 10.77.10.10 address. It did not
serve 4043, 4046, 4060 or any firmware file. The first run deliberately sent
no bytes: the panel showed `Connecting`, made 23 version-port connections,
and its UI log reported `CheckingSoftwareVersion` failed. Evidence:
`evidence/touch10-initial-connection-2026-11-06.json` and
`evidence/post-initial-connection-2026-11-06.log`.

The older `firmware/reference/tools/bin/swsync` script showed that
`version: N/A` plus `method: none` means no software package. One bounded
reply with only those lines produced exactly that result on the live unit:
the UI log parsed `N/A`, printed `Can't find pkg on host`, and exited with
code 3. It also disclosed the target's exact running version string,
`ce9.9.0 46f7ea38fda 2019-10-10`. Evidence:
`evidence/touch10-no-package-initial-connection-2026-11-06.json` and
`evidence/touch10-no-package-ui-2026-11-06.log`.

A final bounded reply on 4045 contained that **exact same version**, plus
`method: none` and **no URL**. The Touch then connected to 4053 and sent a
five-byte TLS ClientHello record header. The listener closed without sending
a TLS certificate or receiving credentials. The owner saw a login screen,
entered nothing, and returned to the device list. The post-cancel log confirms
`PairingCredentialsRequired` → `UnconnectedState`; `selectsw` still reports
CE9.9.0 active/selected. Evidence:
`evidence/touch10-same-version-retry-2026-11-06.json`,
`evidence/post-same-version-handshake-2026-11-06.log`, and
`evidence/post-pairing-cancel-2026-11-06.log`.

**Unexpected configuration write:** On entering the pairing stage, before
credentials or a completed TLS handshake, `Phoenix` logged generation of an
RSA private key and `writing new private key to '/config/pairing/privkey.pem'`.
This path is in the persistent configuration area. We have not read or changed
the key, and cannot establish from the log whether it replaced a preexisting
file. No firmware upgrade or downgrade occurred, but this automatic key write
crossed the intended backup-before-changes boundary. No further pairing
attempt was made. The temporary listener and DHCP server were stopped.

A separate [Cisco upgrade-process command-injection advisory](https://www.cisco.com/c/en/us/support/docs/csa/cisco-sa-tp-cmd-inj-7ZpWhvZb.html)
explicitly lists CE9.9.0 as fixed in 9.9.4, but exploitation requires an
**administrator** issuing malformed upgrade parameters to a codec console,
SSH interface, or xAPI. The panel's passwordless `supportsh` has none of those
interfaces exposed, so the advisory does not establish a route from our
current service account to root.

Offline IDA review of the older `pairingc` found a four-byte packet header
inside TLS. The client first sends type 3 with no payload. A type-6 packet
with a nonzero first payload byte causes it to report pairing success and
save the server certificate. It does not visibly configure peer certificate
verification. This is consistent with Cisco's later
[Touch 10 identity-verification advisory](https://www.cisco.com/c/en/us/support/docs/csa/cisco-sa-CTT-IVV-4A66Dsfj.html),
but neither proves the installed CE9.9.0 client has the same behavior nor
that codec pairing yields root or eMMC readback. Details are in
`evidence/reference-pairing-protocol-2026-11-07.txt`. The older pairing
hooks start services and can delete/repopulate `/user/videolayouts`, so a
completed pairing would cross the backup-before-changes boundary.

A subsequent observation-only TLS server offered the exact installed
CE9.9.0 version and `method: none` on TCP 4045, with no software URL. It was
prepared to complete the TLS handshake on 4053 and record the first request,
then close **without** a pairing-success packet. The direct PC link and
temporary DHCP lease were restored, and the Touch fetched the benign
discovery XML twice. During the 180-second listener window there was no
connection to 4045 or 4053, so no conclusion about the current pairing
protocol follows. No panel selection was reported during that window. Both
temporary servers were stopped. Evidence:
`evidence/touch10-tls-observe-2026-11-07.json` and
`evidence/touch10-tls-observe-discovery-2026-11-07.json`.

The owner then selected the test address while a fresh listener was active.
The Touch connected to 4045, received the exact installed version with
`method: none` and no software URL, completed TLS 1.2 with a locally generated
self-signed server certificate on 4053, and sent the four-byte application
request `00 03 00 00` (type 3, zero payload), matching the older `pairingc`
protocol. The observer sent **no application reply** and closed the session;
there was no completed pairing, credential exchange, or software package.
This confirms that CE9.9.0 reaches the old protocol and does not reject this
untrusted certificate before its first application request. It does not yet
show that a type-6 success response would be accepted or that a paired codec
can read eMMC. Evidence: `evidence/touch10-tls-observe-retry-2026-11-07.json`.

### Owner-approved fake-codec pairing and session capture, 2026-11-07

The owner explicitly approved one controlled pairing attempt despite possible
persistent pairing-configuration writes, using only a temporary root proof and
no firmware upgrade/downgrade. The isolated test codec offered the exact
installed version on TCP 4045 with `method: none` and no package. On TLS 4053,
the Touch sent `00 03 00 00`; the test codec replied `00 06 00 01 01` once.
The Touch then opened TLS 1.2 sessions on TCP 4051. The owner entered only
dummy `test` credentials on the panel and reported it stuck at “Verifying
credentials.” The server's older text-command root proof was never sent:
the session requests contained neither `systemtools network addrs` nor any
other text command. `pairing_success_sent` is a wire-level observation, not
proof that the GUI completed pairing or that root was obtained. Evidence:
`evidence/touch10-pairing-root-proof-2026-11-07.json`.

With the same temporary test certificate, a read-only follow-up captured two
repeating 4051 requests. Each begins with eight ASCII bytes `rxhtrths`, a
four-byte big-endian payload length, and a protobuf-like greeting with client
name `phoenix` or `codecquery`, version `1`, role `peripheral`, and a final
boolean field of value 1. Echoing each greeting exactly once led to another
frame, so the greeting is accepted far enough to reach the next protocol
stage. `codecquery` sent `rxhtrtci` with a zero-length payload. `phoenix` sent
two `rxhtrtx1` frames referring to `Status/SystemUnit/State`; their leading
protobuf field 1 values advanced from 0/1 to 2/3 in a later connection. No
second-stage response or software payload was sent. The actual 4051 reply
schema and a readback mechanism remain unknown. Evidence:
`evidence/touch10-pairing-session-capture-2026-11-07.json`,
`evidence/touch10-pairing-greeting-echo-2026-11-07.json`, and
`evidence/touch10-pairing-greeting-followups-2026-11-07.json`.
One further bounded trial echoed only the two observed
`Status/SystemUnit/State` query frames after the greeting. The client sent no
additional frame during the one-second follow-up window; that echo did not
provide a valid codec status response. Evidence:
`evidence/touch10-pairing-status-echo-2026-11-07.json`.

This test did not yield root access or a backup of this unit. The 2019 panel
protocol is different from the older TI7.3.3 script's text-based 4051 query,
so the older script's config-file injection hypothesis has not been reached
on this CE9.9.0 build. Pairing may have changed persistent configuration; we
cannot determine its exact contents from the restricted service shell.
After stopping the test listeners, read-only `selectsw` still reported
`image2 - ce9.9.0 46f7ea38fda 2019-10-10 [ACTIVE] [SELECTED]`;
see `evidence/post-pairing-selectsw-2026-11-07.log`.

## DHCP and DNS attack-surface check

The exact CE9.9.0 factory package has ISC `dhclient` **4.3.6-P1** for Ethernet
and dnsmasq **2.80** as a local caching resolver. Its startup log reports dnsmasq built with
`no-DHCP` and `no-DNSSEC`; the DNS listener is loopback-only. The DHCP client
requested options 1, 28, 3, 15, 6, 12, 42, 119, 242, 120, 66, 150, 43, and
252. The PC's temporary server supplied only ordinary network options, with
no default router. Live serial logs confirm the Touch accepted DNS server
10.77.10.1 via DHCP. A benign SSDP `LOCATION` hostname then caused A and AAAA
queries to that server and two XML fetches. This establishes a repeatable
input path through the installed resolver; it does **not** show an exploitable
flaw. See `evidence/dhcp-dns-live-path-2026-11-06.md` and its cited logs.

The **older TI7.3.3 reference image** contains ISC `dhclient` 4.1-ESV-R8,
which ISC's [CVE-2018-5732 advisory](https://kb.isc.org/docs/aa-01565)
lists as affected by a DHCP-option buffer overflow. ISC lists **4.3.6-P1 as
the fixed version**, so that older overflow is not a useful lead for the
matching CE9.9.0 package. The exact CE9.9.0 `/etc/dhclient-script` passes
vendor option 43 to `provisioninginfo` and writes supplied SIP, TMS, TFTP and
WPAD values to `/run/netman/dhcpinfo`. The extracted images contain no
`provisioninginfo` binary and no confirmed consumer of `dhcpinfo`. This is
an input path, not demonstrated code execution. No malformed DHCP option or
provisioning command was sent to the unit. See
`evidence/ce990-network-parser-audit-2026-11-07.md`.

The dnsmasq maintainer's
[2.83 security announcement](https://lists.thekelleys.org.uk/pipermail/dnsmasq-discuss/2021q1/014600.html)
distinguishes DNSSEC buffer overflows from cache-poisoning flaws. The observed
`no-DNSSEC` build rules out those DNSSEC code paths; cache poisoning would
redirect lookups but by itself would not provide root or raw firmware access.
The package's `dnsmasq -v` independently confirms `no-DNSSEC`, `no-DHCP`, and
`no-TFTP`; its default configuration binds DNS to loopback and drops to
`nobody`. Runtime configuration may be generated by the management framework.
The live hostname check used only ordinary A and AAAA answers. No malformed
DNS response was sent.
For the newer [CVE-2026-2291](https://bugzilla.redhat.com/show_bug.cgi?id=2439088),
Red Hat's version analysis says dnsmasq 2.73–2.89 reaches the relevant name
expansion only in DNSSEC-enabled builds, so the installed 2.80 `no-DNSSEC`
build does not appear exposed to that flaw. The separate
[CVE-2026-5172](https://access.redhat.com/security/cve/cve-2026-5172)
concerns malformed DNS responses and requires no special dnsmasq setting,
but its described effect is a resolver crash, not code execution or readback.
Applicability to Cisco's 2.80 binary is unverified, and a crash test would
not advance the firmware backup.

### Direct PC link, 2026-11-06

The owner connected the PoE injector's data port to the PC's second Ethernet
interface, `enp7s0`. The original LAN remains on `enp6s0`. A dedicated
NetworkManager profile, `touch10-direct-isolated`, gives `enp7s0` address
10.77.10.1/24 and IPv6 link-local only. A temporary `dnsmasq` instance bound
only to `enp7s0` assigned the Touch 10 (MAC 24:16:9d:b6:77:bb) 10.77.10.10.
The DHCP offer contained no router or DNS option; the host also reported
`net.ipv4.ip_forward = 0`. The temporary DHCP and packet-capture processes were
stopped after the test. The NetworkManager profile remains active for further
isolated work, but DHCP must be started again when the Touch renews its lease.

The Touch sent M-SEARCH for `urn:schemas-upnp-org:device:Basic:1` to IPv6
`ff02::c:1900` about every 11 seconds. The initial IPv4-only probe received
nothing. After enabling IPv6 link-local on the PC interface, one unicast
discovery response advertised a benign XML document at 10.77.10.1:18080. The
Touch fetched it twice: once with user agent `Simple UpnpTool/1.0`, then with
`Mozilla/5.0`. The complete capture shows no follow-on connection to a pairing
or upgrade service. A fixed list of 20 TCP ports on the Touch all refused
connections, including 22, 80, 443, 4043-4048 and 4060. This confirms a
controlled discovery channel, **not** root access or a backup.

Evidence: `evidence/direct-link-initial.pcap`,
`evidence/touch10-direct-ssdp-ipv6.json`, and
`evidence/direct-link-tcp-ports.json`. The probe now accepts host/target IPv4
addresses and an optional IPv6 link-local SSDP interface/address.
The post-probe support console still reports
`image2 - ce9.9.0 46f7ea38fda 2019-10-10 [ACTIVE] [SELECTED]`;
see `evidence/direct-link-serial-postcheck.log`. Recent `UPnPTool-d` log entries
report IPv4 network-unreachable writes, consistent with the deliberately
omitted default route; they do not report a software change.

## Cisco open-source notice

Cisco's [Touch 10 CE8.0 open-source
document](https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/software/ce8/licensing-guide/touch10-open-source-documentation-ce80.pdf)
is a component/license inventory, not a firmware or source archive. It lists
Linux 3.4.107, libupnp 1.6.19, Qt 4.8.2 and OpenSSH 6.7p1. This unit runs a
later CE9.9.0 build with Linux 3.4.113+, so those versions cannot be assumed to
match. Cisco directs requests for corresponding license-covered source to
`external-opensource-requests@cisco.com`, quoting reference
`78EE117C99-94437712`. A draft request for this unit is in
`SOURCE-REQUEST.md`; it has not been sent. No CE9.9.0 source archive or exact
Touch firmware image has been acquired.
The full 37-component CE8.0 list and versions confirmed on this unit are in
`OPEN-SOURCE-INVENTORY.md`. Cisco's later RoomOS 11.5.2.x inventory also lists
`linux-omap 3.4.113-cisco` and `u-boot v2013.04`, supporting a specific
source-request lead but not identifying this unit's exact CE9.9.0 components.

Cisco documents a pairing identity-verification issue (CVE-2022-20793) and a
downgrade issue (CVE-2022-20931). These advisories are research leads, not proof
of read-only root access to this build. A downgrade writes software and was
excluded from this backup-first investigation:

- <https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/cisco-sa-CTT-IVV-4A66Dsfj>
- <https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/cisco-sa-CTT-DAV-HSvEHHEt>

## Prepared backup procedure

`tools/backup_readonly.py` is ready for an **existing, authorized root SSH
connection**, with an already verified SSH host key and working key/agent
authentication. It does not enable SSH, change credentials, install keys, or
try passwords. It has not been tested against the Touch because that access
does not exist yet. Do not change persistent SSH settings merely to run it
before the initial backup; if root becomes available only on serial, a
temporary in-memory TCP transfer can be prepared instead.

Example, once those preconditions actually hold:

```sh
python3 tools/backup_readonly.py \
  --host TOUCH_IP_ADDRESS \
  --output /home/marius/ext_proj/touch10/backups/FOC2403P431-initial
```

Create the `backups` parent directory first. The output directory must be new.
The tool checks UID 0 and the expected Ethernet MAC before reading data. It
creates private local output and reads, in order:

1. The entire 256-byte board EEPROM, preserving board identity and any keys.
2. `/dev/mmcblk0boot0`, the separate eMMC boot area.
3. `/dev/mmcblk0boot1`, the other eMMC boot area.
4. `/dev/mmcblk0`, the entire eMMC user area, including partition tables.

Block-device sizes are read from the target's sysfs rather than copied from
the public dump. The eMMC boot-area `force_ro` flags are not changed. All remote
commands are reads (`id`, `uname`, `cat`, `sha256sum`). Device identification,
mounts, command line, partition listing, CID and CSD are also saved.

Each image is accepted only if its length is correct and the local SHA-256
matches source SHA-256 readings both before and after transfer. Failed or
changing transfers retain `.partial` output and a manifest with `complete:
false`. This detects transfer corruption and changing source bytes; a live
raw dump still is not a certified offline filesystem snapshot. An offline
second read is preferable before relying on it for recovery.

Local checks exercised matching transfer/hash, truncation, oversized output,
failed producer exit, and retention of incomplete files. Syntax compilation
and command-line help checks also pass. No live backup is implied by these
host-only checks.

A raw eMMC user-area dump alone does not include the two eMMC boot areas,
EEPROM, SoC fuses, RPMB contents, or every eMMC configuration register. Record
those distinctions in any recovery plan; this tool does not access RPMB or
alter controller configuration.
