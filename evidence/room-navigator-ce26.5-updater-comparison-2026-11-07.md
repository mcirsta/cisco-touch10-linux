# Room Navigator updater comparison, 2026-11-07

## Image and scope

Downloaded the publicly served Cisco Webex `bifrost.pkg` from
`https://binaries.webex.com/collaboration-endpoint-ce-production-stable/20260415114153/bifrost.pkg`.
The [Cisco RoomOS 26 release notes](https://github.com/cisco-ce/roomos.cisco.com/blob/master/doc/WhatsNew/ReleaseNotesRoomOS_26.md)
also identify the standalone Room Navigator as platform `s53350` and list
newer standalone packages, but those Cisco Software Download links led to
sign-in. This `bifrost.pkg` is an April 2026 cloud package, not the latest
November 2026 on-premises package. The URL was found in a public Webex
deployment document; HTTP HEAD returned 200 and a 418,091,312-byte object.
The downloaded file size matches. Its SHA-256 is
`5cae11d2a314890b48e8683b11ad6e819139a522a26c9aefaa4194cdfab3cc93`.
Independent signature verification was not performed.

`tools/extract_touch_pkg.py` recognized the same `pkg\0` container format,
validated its member table and extracted 40 members to
`firmware/room-navigator-ce26.5/extracted/`. The manifest has offsets, sizes,
and SHA-256 hashes. `vcinfo.txt` says
`Revision:ce-26.5.0.50-44-gc49cadf5f59`; `osversion` is `1a05e663977`.
The package includes an ARM64 i.MX8 root filesystem as a SquashFS image,
an initramfs, kernel, device trees and flash images. This is a different
platform from the OMAP4460 Touch 10 CE9.9.0 image.

## Specific CE9.9.0 chain

The Touch 10 chain depended on a root-run `/bin/swsync` **shell script**:
an attacker-controlled codec could first offer an rsync symlink to a dangling
`/upgrade/pkg` destination, then offer HTTP content that curl wrote through
that symlink to `/etc/profile.d`. A later root profile source executed it.
See [the original audit](ce990-updater-symlink-chain-2026-11-07.md).

The Room Navigator rootfs listing contains **no** `/bin/swsync` shell script
and **no** `/bin/rsync`; it **does** contain `/bin/curl`. Its updater
components include ARM64 ELF binaries `/bin/peripheral-swsync` and
`/bin/swupgrade`. The initramfs file inventory showed no `swsync`, rsync or
curl entry. `/bin/upgrade_software` sends
a `SoftwareUpgrade requestUpgrade` message through `jebus-send`; it does not
invoke the old `swsync` script. `/etc/profile` still sources
`/etc/profile.d/*`, but that alone does not provide an attacker file-write
path.

IDA decompilation of `peripheral-swsync` (file SHA-256
`4166af84c873dcfdc2c6f1eafd18c4ec8b479c1ab475da6b58358bffe351248e`)
shows that the main package path **is still** `/upgrade/pkg`. Its
`receivePkg` function writes to `/upgrade/pkg.tmp` as user `swupgrade`, then
`handleCommitSoftware` renames that file to `/upgrade/pkg`. The rename
replaces a destination symlink without writing through it. The extension
receiver separately writes to `/upgrade/ext-<name>.tmp`. These opens use
flags `0x242` (`O_RDWR|O_CREAT|O_TRUNC`) without `O_NOFOLLOW`, but the
codec cannot choose a symlink transfer method as it could on Touch 10.
The image's `initsysconfig` selects this unprivileged receiver for
`PairedToCodec` provisioning; standalone mode uses the separate root-run
`swupgrade` downloader.
This establishes that the **specific two-stage Touch 10 exploit cannot be
replayed unchanged** against this Room Navigator image. The newer updater
has other symlink-sensitive paths and a potentially serious unrestricted
cleanup path; see the [detailed audit](room-navigator-ce26.5-updater-symlink-audit-2026-11-07.md).

No Room Navigator hardware was used or modified. The comparison is offline
analysis of this one downloaded image, not a live exploit attempt or a claim
about all Room Navigator firmware versions.
