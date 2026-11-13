# Room Navigator CE26.5 SELinux follow-up, 2026-11-07

## Scope and tooling

Queried the packaged `/etc/selinux/cisco/policy/policy.33` from the extracted
CE26.5 `bifrost.pkg`; policy SHA-256:
`533f588ddaa5b60d2c69012f3ece7441a59b705216ca85252cf4923db86bed14`.
SELinux is configured `enforcing` in the image. No device was accessed.

The host lacked `seinfo`/`sesearch`, so SETools 4.7.0 from the
[SELinuxProject release](https://github.com/SELinuxProject/setools/releases/tag/4.7.0)
and `libsepol`/`libselinux` packages from the host distribution were unpacked
under `/tmp/touch10-policytools`. SETools was compiled there against the
libraries without installing or changing host system packages. Its generated
C source was used instead of Cython. The commands below run from the SETools
source directory with the extracted policy as the last argument.

## Control-file writer

`/upgrade` is a symlink to `/mnt/base/active/tmp-upgrade`; tmpfiles creates
the target `0775 root:swupgrade`. `/etc/group` lists `main` in `swupgrade`.
The packaged `file_contexts` labels `/mnt/base(/.*)?` as `base_mount_t` and
the `/upgrade` symlink itself as `upgrade_t`.

Relevant queries and results (using `python3 ./sesearch`):

```text
--allow -s main_t -t upgrade_t -c lnk_file
  allow main_t upgrade_t:lnk_file { getattr read };
--allow -s main_t -t base_mount_t -c dir -p add_name
  allow main_t base_mount_t:dir { add_name create ... search ... write };
--allow -s main_t -t base_mount_t -c file -p create
  allow main_t base_mount_t:file { ... create ... open ... rename ... write };
```

The directory and file rules are unconditional in the packaged policy.
Together with the shipped Unix group mode, they permit a process in
`main_t` running as `main` to create and move a control file into the
upgrade directory. This resolves the previous uncertainty about SELinux
blocking *that particular writer*. It does not show that a remote codec or
unauthenticated network client can make `main` create the file.

`seinfo --permissive` lists `peripheral_swsync_t`, `swupgrade_t`, and
`installimage_t` among 25 permissive types; it does not list `main_t` or
`initrc_t`. A permissive domain logs denials but does not enforce them, so
SELinux rules are not an effective file-access barrier for those three
domains in this packaged policy. Unix permissions still apply, and a live
device could load a different policy.

`peripheral_swsync_t` also has unconditional `add_name/create/write` access
to `base_mount_t` directories/files. Its service runs as `swupgrade`, whose
primary group is `swupgrade`. The analyzed transfer protocol, however,
does not let a codec choose the exact `/upgrade/installimage` path.

The shipped `vega.service` runs the web application as `web`, another member
of the `swupgrade` group. Its `vega_exec_t` transition leads to `vega_t`;
the policy grants `vega_t` unconditional `add_name/create/write` and
`rename` access to `base_mount_t`, as well as read access to the `/upgrade`
symlink. The authenticated admin upgrade route does write this control file,
but it supplies a fixed local package path. A compromised `vega` process
could choose different contents; the reviewed HTTP route itself exposes no
arbitrary local path parameter. See the
[Vega writer follow-up](room-navigator-ce26.5-vega-writer-followup-2026-11-07.md).

## Root watcher and deletion target

The `/sbin/updatesw` executable has no specific file-context entry. The
`/sbin -> /usr/sbin` substitution and the general `/usr/sbin(/.*)?` rule
label it `bin_t`. The shipped policy contains:

```text
type_transition init_t bin_t:process initrc_t;
allow init_t initrc_t:process { getattr transition };
```

The unit has no `User=` or `SELinuxContext=` override, so its expected
process identity is root in `initrc_t`. `seinfo -t initrc_t -x` lists
`files_unconfined_type` among its attributes. The policy's
`files_unconfined_type file_type` rules grant directory remove-name/rmdir
and file unlink across file types, including the writable `/config` and
`/mnt/base` mounts. The watcher parser and cleanup logic are detailed in
the [updater audit](room-navigator-ce26.5-updater-symlink-audit-2026-11-07.md):
its `/upgrade/installimage` control file accepts an existing path outside
`/upgrade`, invokes the installer, then removes the named path even after
installer failure. Directory arguments reach recursive `nftw` cleanup.

This policy analysis therefore supports a **local cross-privilege deletion
candidate from a compromised `main` or `vega` process**, without a package signature.
It still requires a controlled reproduction to confirm the installed
watcher's runtime behavior and actual labels. It is not evidence of a
codec-only or unauthenticated remote exploit.

## Other symlink paths

`main_t` lacks `add_name` on `upgrade_t` (`/config/swupgrade`) and
`extension_files_t` (`/config/extensions`) directories, even though the Unix
group modes look writable. `main_t` is not permissive, so those missing
allows matter for it. `peripheral_swsync_t` has unconditional
`add_name/create` access to both, runs as `swupgrade`, and is permissive.
Consequently the root prestart `chown` symlink candidate and the root
`post-main@.service` log-redirection candidate are plausible from a
compromised `swupgrade` process, but not established from `main_t` merely by
its group membership. The [ownership-change follow-up](room-navigator-ce26.5-chown-symlink-followup-2026-11-07.md)
identifies a concrete local root-execution chain for the `chown` path:
symlink `extensions.json` to `/run/sysconfig.d`, gain ownership of that
directory, then supply a Bash startup file through the `sshd.service`
environment file and its watched restart. The packaged `fswatcher`
[dispatched that restart in an isolated run](room-navigator-ce26.5-fswatcher-dispatch-followup-2026-11-07.md).
The complete chain and live SELinux labels were not tested on hardware.
The [post-main follow-up](room-navigator-ce26.5-post-main-symlink-followup-2026-11-07.md)
identifies `/run/sysconfig.d/ssh` as a useful sink and reproduces the
watcher dispatch after a symlinked write. It still requires `main` to
terminate while the attacker-controlled inputs are in place; that trigger
and live root execution were not established.

## Limits

`file_contexts` describes intended labels; a running device may contain
stale or relabeled files. The analysis assumes the default SELinux domain
transition for `updatesw` and its shipped systemd unit. No live labels,
process contexts, or exploit outcome were measured. The subsequent
[isolated reproduction](room-navigator-ce26.5-watcher-offline-repro-2026-11-07.md)
confirmed the exact watcher's deletion behavior with a disposable test tree.
