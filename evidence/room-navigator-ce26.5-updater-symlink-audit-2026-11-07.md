# Room Navigator CE26.5 updater symlink audit, 2026-11-07

## Scope and method

This is offline analysis of the downloaded `bifrost.pkg` with rootfs revision
`ce-26.5.0.50-44-gc49cadf5f59` (`osversion` `1a05e663977`). The package
SHA-256 is `5cae11d2a314890b48e8683b11ad6e819139a522a26c9aefaa4194cdfab3cc93`.
The relevant extracted filesystem is
`firmware/room-navigator-ce26.5/rootfs-unpacked/`. IDA analysis used these
ARM64 executables:

| Program | SHA-256 |
| --- | --- |
| `bin/peripheral-swsync` | `4166af84c873dcfdc2c6f1eafd18c4ec8b479c1ab475da6b58358bffe351248e` |
| `bin/swupgrade` | `23df3ea4608534f0a37e9b0875455e7e08ea71b378895026ceae8760ddb7d3da` |
| `sbin/updatesw` | `9ca01c92dec305353a36ae984fbf46e48d2e404916aad810e9bf8e5ea4c45a3c` |

No Room Navigator was connected, modified, or run. We did not observe live
SELinux contexts or perform a live exploit. This image is one April
2026 cloud build, not evidence about every later RoomOS release.

## Layout and trust boundaries

`/upgrade` is a symlink to `/mnt/base/active/tmp-upgrade`. The latter is
created `0775 root:swupgrade` by `etc/tmpfiles.d/basic.conf`. The
`swupgrade` group includes `main`, `remotesupport`, and `web` in `etc/group`;
ordinary Unix permissions therefore allow those identities to create names
in the upgrade directory. A later [policy follow-up](room-navigator-ce26.5-selinux-followup-2026-11-07.md)
found unconditional `main_t` and `peripheral_swsync_t` file-creation rules
for the target's `base_mount_t` label. SELinux is configured enforcing;
the packaged policy nevertheless marks `peripheral_swsync_t` and
`swupgrade_t` permissive. Actual device labels have not been measured.

The shipped `peripheral-swsync.service` runs its main executable as
`swupgrade:swupgrade`; its two `ExecStartPre=+` shell commands run with root
privileges. `swupgrade.service` and `updatesw.service` specify no `User=` and
run as root. `swupgrade.service` additionally requires
`UPGRADE_MODE=swupgrade`; `peripheral-swsync.service` requires the
`/run/sysconfig.d/use-swsync` and `/run/tam_success` markers. IDA of
`bin/initsysconfig` found that `write_peripheral_swupgrade_config`
(`0x4cb80`) defaults to `UPGRADE_MODE=swupgrade`; the exact
`provisioning_type` value `PairedToCodec` switches to `UPGRADE_MODE=swsync`
and creates `/run/sysconfig.d/use-swsync`. Other provisioning types remove
that marker. Thus paired and standalone modes use different receive paths;
no live device parameter was read.

The extracted initramfs `firmware/room-navigator-ce26.5/initramfs-init`
(line 127) mounts the active `rootfs` with
`mount -o ro,loop -t squashfs`. Release builds also have a
`verify-no-rootfs-overlay` sanity check. Thus the old Touch 10 target
`/etc/profile.d` is normally read-only on this image. The installed
`/sbin/installimage` still sources `/etc/profile` and its `profile.d` files
before verifying a package, but the original writable-rootfs assumption no
longer holds.

## Specific Touch 10 chain

The CE9.9.0 chain used a root-run `/bin/swsync` shell script: codec-selected
rsync created a dangling `/upgrade/pkg` symlink, then codec-selected curl
wrote HTTP content through it to `/etc/profile.d`. This CE26.5 rootfs has
`/bin/curl` but no `/bin/swsync` script or rsync executable. The compiled
receiver does not accept a codec-selected rsync/curl method. Its package
destination is fixed by the shipped service. The exact two-transfer chain
cannot be replayed unchanged against this image.

In `peripheral-swsync`, `SWSyncClient::receivePkg` (`0xc2f30`) opens
`/upgrade/pkg.tmp` at `0xc3038` with flags `0x242`
(`O_RDWR|O_CREAT|O_TRUNC`), mode `0644`, then writes network bytes via
`pug::recv_binary` (`0xc306c`). This open **does follow** an existing symlink
and lacks `O_NOFOLLOW` and `O_EXCL`, but the process has `swupgrade` rather
than root privileges. `handleCommitSoftware` (`0xbde30`) calls
`rename("/upgrade/pkg.tmp", "/upgrade/pkg")` at `0xbdffc`. Rename replaces a
symlink at the destination; it does not write through its target. A symlink
at the source is moved as a symlink. The root prestart command deletes
`/upgrade/pkg?*` at service start; that leaves a post-start race for an actor
already able to write the directory, but no codec-only symlink planting
route was found. A local `--destination` CLI option exists, yet the shipped
service passes no option and the codec protocol does not choose that path.

`SWSyncClient::receiveExtension_` (`0xc08e0`) creates
`/upgrade/ext-<codec-name>.tmp` from an unsanitized extension name and opens
it at `0xc09e0` with the same flags. The `ext-` prefix means a name alone
cannot begin with a `../` component; traversing out would require an
existing `ext-*` child directory or symlink. After receipt, the destination
name is sanitized and the source is renamed to `*.ext.new`. The root
`bin/extension-handle-upgrade` hook processes those final files, not the
temporary path. The prestart cleanup removes `/upgrade/ext*` before the
receiver runs. We have not demonstrated a remotely reachable traversal or
root write here.

The alternate, **root-run** `swupgrade` daemon has a different downloader.
`LoadsFileHandler::use_new_loads_file` (`0x1a9490`) sets its download base
to `swupgrade_path("")`, which resolves to `/upgrade/`; the codec/request
does not provide that base path. `ImageTask::target_path` (`0x1940b0`)
constructs image names below it. `ResultFile::open_` (`0x29ea30`) opens a
new `.downloading-<eight-hex-digits>` or `.chunk-<index>` file with flags
`577` (`O_WRONLY|O_CREAT|O_TRUNC`), or an existing resumable chunk with
flags `1025` (`O_WRONLY|O_APPEND`). Neither form uses `O_NOFOLLOW`; the new
file form also lacks `O_EXCL`. `CurlRequest` (`0x2a9770`) enumerates existing
chunk paths using `std::filesystem::status` and `file_size`, which follow
symlinks. `close_success` (`0x29f200`) renames the completed temp file to
its final target; `commit_full_system_upgrade` (`0x1a49e0`) moves that
file to `/upgrade/pkg` or `/upgrade/cop` by rename. This does not write
through a final `/upgrade/pkg` symlink, but a pre-existing or raced symlink
on a resumable chunk could be opened for a root append **if this mode is
enabled**. The request configuration's resume flag defaults off, and we
have not found the swupgrade caller enabling it. The ordinary new download
uses an eight-hex-digit randomized temporary name; `unique_path` does not
reserve it, leaving a theoretical check-to-open race but no demonstrated
way to learn and occupy the name in time. `IRFetcher::fetch_file_`
(`0x19a850`) downloads a loads file and its `.sgn` companion before
`on_new_loads_state_` (`0x19b330`) calls
`verify_loadsfile_signature` (`0x22e960`), so HTTP bytes reach the staging
directory before that signature check. The fixed final
`/upgrade/tmp-loadception` name is reached by rename, not by a direct
network write. The later image request performs trust/checksum checks;
their full effect on remote content control is unresolved. SELinux access
and a viable symlink placement must also be resolved before treating this
as an exploitable root write. No codec-only way to create such a symlink
has been found.

## Root watcher and install handoff

The root `updatesw.service` watches `/upgrade/pkg`, `/upgrade/cop`, and the
built-in `/upgrade/installimage` control file. `updatesw` main (`0x1380`)
removes watched paths on startup, then uses inotify mask `0x180`:
`IN_CREATE|IN_MOVED_TO` (watch call `0x1720`). An event is gated by
`access(path,F_OK)` (`0x17d0`), which follows symlinks. A dangling package
symlink fails that check; a later write to its target does not create or
move a name in `/upgrade`. Header reads use `fopen(path,"r")` (`0x23d0`) and
size checks use `stat`, both following symlinks, but this watcher does not
write through the package path. Cleanup calls `unlink`, removing a package
symlink itself. This code does not supply the missing root-write stage of
the old chain.

There is a **separate potentially serious path-handling issue** in the new
`/upgrade/installimage` control-file branch. The watcher reads up to 511
bytes from that file and accepts `-f`/`--file` or `-c`/`--cop` followed by a
path. `run_installimage` (`0x2490`) checks only that the path consists of
ASCII letters, digits, `.`, `-`, `_`, and `/`, and that `access(F_OK)` succeeds.
It does not require a regular file, a package suffix, or a path within
`/upgrade`; absolute paths, relative paths, and `..` fit the character
check. After `/sbin/installimage` returns, including failure, main invokes
`remove_path` on the supplied path (`0x1dc8`, failure rejoins at `0x1dbc`).
`remove_path` (`0x2310`) calls `unlink`; for a directory (`EISDIR`) it walks
and removes the tree via `nftw(..., 0xB)` and `remove` (`0x23b8`, callback
`0x2280`). The `nftw` flags include `FTW_PHYS` and `FTW_MOUNT`, so this
cleanup does not follow a directory symlink or cross a nested mount; a
directly named directory is enough to reach the recursive branch. This is
a candidate root file/directory deletion primitive. The packaged SELinux
policy and Unix permissions permit the shipped `main` and `vega` processes
to create the control file. The [Vega web upgrade route](room-navigator-ce26.5-vega-writer-followup-2026-11-07.md)
normally writes it with a **fixed package path** after an authenticated
admin action; no HTTP parameter directly selects an arbitrary local path
there. An [isolated run of the exact watcher](room-navigator-ce26.5-watcher-offline-repro-2026-11-07.md)
confirmed deletion of a named directory outside `/upgrade` after a fake
installer returned failure. A network route to supply arbitrary control-file
contents and live device behavior are still unproven.

`/sbin/installimage` resolves `-f`/`-c` with `readlink -f` (lines 214-225)
and applies `chmod a-w` to the resolved input (lines 282-288) before calling
`pkgverify` (lines 438-451). Accordingly, an invalid signature prevents
package extraction but does not prevent this pre-verification permission
change or the watcher's subsequent path removal. No signature bypass was
found. The control-file cleanup branch is absent from the examined CE9.9.0
watcher.

## Other symlink-sensitive root operations

* `peripheral-swsync.service` runs
  `test -e /config/extensions/extensions.json && chown swupgrade /config/extensions/extensions.json`
  in a root `ExecStartPre=+` command. `/config/extensions` is created
  `2775 root:swupgrade` by `etc/tmpfiles.d/main.conf`. The packaged BusyBox
  `chown` follows a symlink by default; this was confirmed by its QEMU
  `fchownat(..., 0)` syscall. A planted `extensions.json -> /run/sysconfig.d`
  changes that directory from `root:config` to `swupgrade:config`. Its owner
  can then replace `/run/sysconfig.d/ssh` with an `EnvironmentFile` setting
  `BASH_ENV` to a controlled Bash file. The packaged `fswatcher` restarts
  `sshd.service` on that file event, and the service's first root pre-start is
  a Bash script. This is a concrete **local `swupgrade`-to-root candidate**
  requiring paired mode and a service start after symlink placement. The
  [ownership-change analysis](room-navigator-ce26.5-chown-symlink-followup-2026-11-07.md)
  and [isolated watcher dispatch](room-navigator-ce26.5-fswatcher-dispatch-followup-2026-11-07.md)
  document the chain and component tests. A
  [reachability review](room-navigator-ce26.5-extensions-json-reachability-2026-11-07.md)
  found no codec transfer or reviewed Vega route that plants the symlink;
  local `swupgrade` file control remains a prerequisite. No live device
  execution was tested.
* `post-main@.service` (root) redirects the last matching event-log lines to
  `/config/swupgrade/previous-sysinfo.txt` and then `chmod 664`s that path.
  `/config/swupgrade` is created `2775 swupgrade:swupgrade`. A compromised
  `swupgrade` process can also write a matching line to the group-writable
  event log. A symlink to `/run/sysconfig.d/ssh` therefore yields a root
  overwrite of that environment file with an attacker-selected `BASH_ENV`
  assignment; the watcher then dispatches an SSH restart. An
  [isolated exact-watcher run](room-navigator-ce26.5-post-main-symlink-followup-2026-11-07.md)
  confirmed the write-through-symlink event and restart dispatch.
  `main.service` invokes `post-main@...` on success or failure, but an
  attacker-controlled way to make `main` terminate has not been shown.
  This is a conditional local escalation path, not a live root execution
  demonstration.
* The RWFS copy hooks use `tar cf - . | tar -xf -` with
  `EXTRACT_UNSAFE_SYMLINKS=1` to copy old `/config` and `/storage` into freshly
  created filesystems. The exact packaged BusyBox tar preserved symlinks in
  isolated tests but did not follow them outside the destination, even for a
  crafted archive containing a descendant beneath an escaping link. The
  [focused hook review](room-navigator-ce26.5-rwfs-tar-symlink-followup-2026-11-07.md)
  found no direct extraction escape. A malicious link can persist across an
  upgrade and still affect a later privileged operation, including the
  `extensions.json` ownership change above.

## Status and follow-up

**Confirmed from the image:** the old rsync-to-curl root method is absent;
the new receivers' temporary-file opens and several root maintenance paths
remain symlink-sensitive; the watcher control-file branch has an
unrestricted cleanup path before or regardless of successful signature
verification. The pre-start `chown` has a plausible local root-execution
chain through the watched system configuration directory and the SSH service
environment. The `post-main` log redirection has a second conditional chain
to the same root service, requiring `main` termination. **Not established:**
a codec-only exploit, a live Room Navigator root escalation, the provisioning
mode on a particular device, the pairing protocol's authentication
properties, or live SELinux labels.

The packaged policy was decoded and the watcher behavior reproduced in the
linked offline follow-ups. A controlled check of live process labels and
directory permissions on an owned Navigator would remain read-only, but
triggering the deletion branch on a device would change device state and is
outside the current investigation scope. No live test was performed.

Cisco's September 2026 RoomOS 26 release notes list a newer standalone
Navigator package. Its July 2026 hardening advisory groups multiple fixes
under broad CVEs but does not identify either chain in this report. The
[public-advisory check](room-navigator-ce26.5-public-advisory-check-2026-11-07.md)
records the exact versions and explains why those CVEs cannot yet be
assigned to these findings. A post-fix firmware comparison is still needed.

For a vendor fix, remove symlink-following privileged operations on paths
in `swupgrade`-writable directories and prevent attacker-controlled log
text from becoming a root service environment file. The root watcher should
only remove its own fixed staging names after checking them as regular files
beneath the upgrade directory. Downloaders should create temporary files
atomically without following symlinks. Signature verification should precede
any mutation of a caller-supplied path.
