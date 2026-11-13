# CE9.9.0 updater path audit, 2026-11-07

## Scope and status

This audit uses the exact Touch 10 CE9.9.0 `46f7ea38fda` package recovered from
the owner's offline codec. The initial tests ran on the PC with the package's
ARM binaries under QEMU. The chain was subsequently confirmed on the live
panel, yielding temporary root access and a verified raw backup.

## Privileged download path

The exact `/bin/swsync` script (`firmware/codec-ce9.9.0/apps-unpacked/bin/swsync`):

1. Sources `/etc/profile` before checking for `/upgrade/pkg` (lines 15–19).
2. Treats `/upgrade/pkg` as busy only when `[ -f /upgrade/pkg ]` is true
   (lines 64–67). A symlink to a nonexistent file is therefore not busy.
3. Gets `version`, `method`, `url` and `targets` from codec TCP 4046, with
   TCP 4045 as fallback (`apps-unpacked/etc/swsync.conf` and lines 94–118).
4. For a different version, runs `rsync -a --progress --timeout=7 "$url"
   /upgrade/pkg` or `curl -# --progress-bar "$url" -o /upgrade/pkg`
   (lines 143–190). The URL is one shell argument, so this is not a shell
   metacharacter injection.

The normal root-run `S95synccheck` service starts `/bin/synccheck` without a
privilege drop; that script periodically invokes `swsync` when paired.
`swsync` also participates in the initial device-selection flow. The live
sequence below established the root UID of the later profile source.

The exact `/sbin/updatesw` watches the `/upgrade` directory for
`IN_CREATE|IN_MOVED_TO` (mask `0x180`), checks that its target path exists, and later
opens a completed package. A dangling `/upgrade/pkg` symlink fails that
existence check. A later curl write through it closes a file outside the
watched directory, so the watcher does not see a completed package event.
Its `installimage` invocation is not reached in the tested chain.

The kernel unpacks this build's `rootfs` as an initramfs. The `apps.img`
`postprocess` creates `/etc/profile.d` in that RAM filesystem, and the exact
`/etc/profile` sources every file there. A new
`/etc/profile.d/zz_touch10_upgrade_probe` is absent from the extracted
rootfs, apps and extra images. It is a suitable **volatile** proof target.

## End-to-end off-device result

With the exact ARM rsync 2.6.9 client pulling a symlink from a real local
rsync daemon, `-a` created `/tmp/touch10-rsync-symlink-lab/dst/pkg` as a
symlink to an initially nonexistent file outside the destination directory.
Exit status was 0. The exact ARM curl 7.66.0 client then fetched a harmless
HTTP body to `-o` that symlink. Exit status was 0, and the outside target
contained the body while the symlink remained. A separate watcher test showed
no package-install event for this path. The exact `nc6` binary successfully
sent a UID-proof message to a loopback listener.

This established an arbitrary-file-write chain before package signature
verification; the subsequent live test confirmed its root-access impact. It
is a composition of two legitimate tool behaviors with `swsync`'s file check
and path choice; it is not being attributed to an rsync or curl CVE. The
prepared server is
`tools/touch10_upgrade_probe_server.py`: `rsync` stage offers the symlink,
`http` stage offers a script that sends only `id`, and `proof` stage receives
the UID. On a successful send, that script removes its volatile profile file
and the `/upgrade/pkg` symlink. It serves no firmware package. Its three stages passed a loopback
integration check, including the exact ARM rsync and curl clients and Bash
syntax of the 397-byte proof script. A SIGTERM check confirmed the server
writes its event log.

## Signature and crypto observations

`installimage` invokes `pkgverify -f` before clearing or extracting the
inactive image. The exact `pkgverify` and `pkgextract` use CiscoSSL
`1.0.2s.6.2.352-fips` and embedded PEM public keys. They call
`EVP_VerifyFinal` and require a return value of 1. They do not use a TLS
certificate chain for package signature verification.

After that initial gate, `installimage` extracts the signed package into the
inactive image, verifies `sha256sum.txt` where present, executes package
postinstall hooks as root, and selects the new image. `pkgextract` itself
checks its signature after extraction, but the installed script's earlier
`pkgverify -f` blocks a simply modified package before extraction. The
`pkgextract -F` option skips signature and target checks for a named-file
extraction; the installed automatic path does not pass that option.

On copies of the 113,785,221-byte package, `pkgverify -f` accepted one-bit
changes at header offset 4 and optional-field-0 offset 199 (both exit 0),
but rejected a one-bit change in the version string at offset 70 (exit 1,
`Signature invalid!`). The first two fields are omitted from the signature
digest in `pkg2ReadHeader`; the observed installer has no identified control
flow that uses them. This is signed-byte coverage evidence, not a useful
signature bypass. The `-c` checksum mode returned 1 even for the unmodified
package and is not called by `installimage`.

An optional-field declared length of 0 or 1 underflows in `pkg2ReadHeader`.
The exact ARM verifier's off-device tests returned `Bad address` and an error
or unsigned-package result, without a crash or accepted signature. The huge
read request does not presently establish a usable heap overwrite.

## Live panel result

The panel was connected directly to the PC on `enp7s0`; its DHCP address was
`10.77.10.10`. The fake codec's rsync stage was fetched by the panel, and its
support log recorded `link -> /etc/profile.d/zz_touch10_upgrade_probe`
(`evidence/touch10-root-stage2-console-live-2026-11-07.log`). The HTTP stage
then supplied the volatile script. A first callback was truncated by the
listener's one-read handling, so it was not counted as a complete UID proof.
The corrected follow-up connected a temporary root shell and returned
`uid=0(root) gid=0(root)` from live `id`. The server event record is
`evidence/touch10-root-shell-http-live-2026-11-07.json`; it records
`firmware_package_served: false`.

Through that root shell, raw reads of `/dev/mmcblk0`, `/dev/mmcblk0boot0`,
`/dev/mmcblk0boot1`, and the board EEPROM were transferred to
`backups/touch10-2026-11-07`. The manifest records sizes and matching
SHA-256 checks before and after transfer on the panel and twice on the PC.
The temporary `/upgrade/pkg` symlink and profile script were removed and
confirmed absent; the shell and test codec services were stopped. The owner
power-cycled the panel, which returned to its normal screen. No firmware
package was served or installed. RPMB was not read.

The exact codec package in `firmware/codec-ce9.9.0/idefix.pkg` is a recovery
reference, **not** a dump of this panel's eMMC, EEPROM or configuration. The
prepared `tools/backup_readonly.py` was not used for this backup; the live
transfer used `tools/touch10_receive_dump.py` and the temporary root shell.

## Later-firmware applicability review, 2026-11-07

**Confirmed affected: CE9.9.0 `46f7ea38fda`. Later releases: unknown.**
The local firmware inventory contains the exact CE9.9.0 package and an older
TI7.3.3 reference, with no newer Touch 10 payload. Public searches in this
review did not locate a newer downloadable `idefix.pkg` or published
`swsync` implementation. Cisco's dynamic download catalog and pairing bug
details could not be read through the web tool. Earlier browser observations
of login/service-contract requirements are recorded in `ROOT-AND-BACKUP.md`;
this review did not acquire a newer package or recheck those requirements
in a browser. No device commands or firmware changes were performed.

Related Cisco advisories do not establish a fixed release for this chain:

- [CVE-2020-3336](https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/cisco-sa-tp-cmd-inj-7ZpWhvZb)
  describes administrator-triggered upgrade command injection and lists
  CE9.9.4 as the fix for its CE9.9 branch. Our downloader symlink chain
  does not depend on shell parameter injection, so that version cannot be
  treated as its fixed release.
- [CVE-2022-20793](https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/cisco-sa-CTT-IVV-4A66Dsfj)
  concerns pairing identity verification. Its public advisory delegates fixed
  versions to bug CSCvw08723; it does not describe this arbitrary write.
- [CVE-2022-20931](https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/cisco-sa-CTT-DAV-HSvEHHEt)
  lists 10.15.2.2 as a downgrade fix. We did not downgrade the panel to gain
  root, so that fix does not establish that the downloader chain was removed.
- [Cisco's April 2023 file-write advisory](https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/cisco-sa-roomos-file-write-rHKwegKf)
  includes symbolic-link overwrite vulnerabilities requiring a remote-support
  account. The public descriptions do not identify this network-delivered
  `swsync` chain. Shared bug class alone does not establish an identical bug.

The next decisive input is a newer Touch 10 `idefix.pkg`, obtainable from a
codec's peripheral package or a Room Series COP containing peripheral images.
Analyze a local copy: compare `swsync`, its callers, `/etc/profile`,
`updatesw`, and bundled downloader behavior. Check whether an untrusted source
can still create the destination symlink, whether a subsequent transfer can
follow it, and whether the resulting write has a reachable root execution
path. Authentication changes can block the original entry path even if the
unsafe file handling remains. A changed script or a newer rsync/curl version
alone is insufficient to declare the complete chain fixed. Reproduce any
remaining file-write behavior in an isolated off-device temporary directory;
no panel upgrade is needed for that comparison.

### Additional package and CVE search

A [Cisco Community diagnostic log from a CE10.4.1.1 codec](https://community.cisco.com/t5/webex-devices/webex-board-maintenance-mode/m-p/4414257)
lists `Idefix @ ce10.4.1.1 85ff0a04877 2021-05-12` and identifies its
peripheral package as `/mnt/base/active/peripherals/idefix.pkg` with SHA-512
`0241d658a06b256573fafb1708c11c3da3f82e23b4a02717688a47ca584329c7e06b1480d1da70e5cab807115ef1ab4db7ed093bca413bf2cb55bf7bf6a7c662`.
This confirms that a newer comparison package exists on a later codec; it is
not a public package download. Searches for that filename and later COPs did
not yield a verifiable downloadable image. The Cisco software catalog showed
that the selected CE9.15.18.5 release may no longer be available and offered
a login check. The local shell's external DNS is unavailable. No later package
was acquired or compared.

No public CVE found in this search describes the observed two-transfer
`swsync` chain. [CVE-2020-3336](https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/cisco-sa-tp-cmd-inj-7ZpWhvZb)
is an authenticated upgrade parameter command injection.
[CVE-2023-20004/20091/20092/20093](https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/cisco-sa-roomos-file-write-rHKwegKf)
describe local CLI symlink overwrites requiring a remote-support account.
Neither published description matches the network-delivered `swsync` path.
The [2018 public report on unauthenticated codec rsync downloads](https://herolab.usd.de/security-advisories/usd-2018-0035/)
has no CVE and concerns disclosure of the package, not this root write.

The exact clients behaved as invoked: `rsync -a` copied a symlink as a
symlink, and `curl -o` opened the named destination through that symlink.
The vulnerable composition is in Cisco's privileged `swsync`: it accepts a
codec-selected transfer method and URL, uses `[ -f /upgrade/pkg ]` as the
busy check (which misses a dangling symlink), and reuses `/upgrade/pkg` for
both transfers without clearing or rejecting a symlink. The later profile
source supplied the execution step. No malformed rsync protocol or curl
response is needed, and this evidence does not establish a flaw in either
upstream tool.
