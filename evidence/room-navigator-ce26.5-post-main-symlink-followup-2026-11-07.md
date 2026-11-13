# Room Navigator CE26.5 `post-main` symlink follow-up, 2026-11-07

## Scope

Offline analysis of the extracted CE26.5 `bifrost.pkg` root filesystem. No
Room Navigator or Touch 10 was accessed or changed. This examines the second
root-run symlink candidate identified in the [updater audit](room-navigator-ce26.5-updater-symlink-audit-2026-11-07.md).

## Source and trigger

`lib/systemd/system/post-main@.service:7` runs as root (no `User=`) and has:

```sh
grep swupgrade /var/log/eventlog/sysinfo.txt | tail -10 > /config/swupgrade/previous-sysinfo.txt
chmod 664 /config/swupgrade/previous-sysinfo.txt
```

Both shell redirection and `chmod` follow a symlink at the destination.
`main.service:6-7` starts this separate unit through `OnSuccess=` or
`OnFailure=` when `main` terminates. A compromised `swupgrade` process cannot
be assumed to make `main` stop; that trigger remains a prerequisite.

The destination directory is `2775 swupgrade:swupgrade` in
`etc/tmpfiles.d/basic.conf:5`. A process running as `swupgrade` can replace
`previous-sysinfo.txt` with a symlink, regardless of an existing file's owner,
because the directory has no sticky bit. The packaged SELinux policy permits
`peripheral_swsync_t` to add names to `upgrade_t` directories, and the domain
is permissive in this image. The service supplying that domain is
`peripheral-swsync.service`, which runs as `swupgrade` in paired mode.

The input is also under local influence after compromising that process.
`/var/log/eventlog` is created `2775 root:log` by
`etc/tmpfiles.d/basic.conf:59`, and `etc/group:25` includes `swupgrade` in
`log`. `bin/update-sysinfo` creates `sysinfo.txt` and makes it group-writable.
The directory itself is group-writable and non-sticky even if a preexisting
file's mode differs. `peripheral_swsync_t` is permissive, so its lack of an
explicit SELinux `var_log_t:file write` allow is not an enforced obstacle in
the packaged policy. Appending a line containing `swupgrade` makes it part of
the `grep` output; as one of the last ten matching lines, it reaches the
root redirection.

## Practical target and impact

The direct primitive is **root truncation/overwrite with selected log lines,
followed by `chmod 0664`**, of an existing or new path selected by the
symlink. The root filesystem is a read-only SquashFS, but `/config` and
`/mnt/base/active` are writable at runtime.

The most direct conditional root-execution route is a symlink to
`/run/sysconfig.d/ssh`. An attacker-controlled input line such as
`BASH_ENV=/config/swupgrade/new.loads.factoryreset-save` contains the
`swupgrade` grep term. The payload path is in an updater-owned directory;
it is read as a Bash startup file, so `/config` being mounted `noexec` does
not prevent it from running. Root `post-main` redirection follows the
symlink, creating or replacing `/run/sysconfig.d/ssh`. The packaged
`fswatcher` watches `/run/sysconfig.d` for `IN_CLOSE_WRITE | IN_MOVED_TO`,
and its `sysconfig.ssh` action is `systemctl restart sshd.service`.
`sshd.service` loads this optional environment file and then executes the
root `#!/bin/bash` script `/bin/sshd_generate_kex_config` as its first
`ExecStartPre`. Bash reads `BASH_ENV` before that script's body.

An isolated test with the exact CE26.5 ARM64 `fswatcher` under QEMU and
bubblewrap used `/config/swupgrade/previous-sysinfo.txt ->
../../run/sysconfig.d/ssh`; a write through this symlink produced watcher
output `Running action systemctl restart sshd.service` and a fake
`systemctl` log of `restart sshd.service`. The fake command only logged its
arguments. This extends the separate [dispatch
reproduction](room-navigator-ce26.5-fswatcher-dispatch-followup-2026-11-07.md),
which had created `/run/sysconfig.d/ssh` directly. It proves the watched
target directory receives the event even when the write uses a symlink in
another directory.

There is a shutdown timing condition. `post-main@.service` calls
`reboot-or-not` after the redirection and several other hooks. A compromised
`swupgrade` process can create `/tmp/noboot` beforehand: the packaged
`tmp.mount` is enabled and mounts a `1777` tmpfs, and `reboot-or-not`
explicitly exits without reboot if that marker exists. This removes the
normal crash-reboot deadline in that scenario, but whether an attacker can
make `main` terminate and actually start `post-main@.service` is unproven.

An alternative persistent target is a symlink to
`/config/pairing/config`. That file is listed in the
`etc/filesystem-cleaner/config.json` keep set (line 368), so it is a more
plausible persistent target than `/config/system_state_logger`, which is not
listed. The root `forward-to-metaproxy.service` and related forwarder units
load `/config/pairing/config` as an `EnvironmentFile=` and then execute
`/bin/sslc-wrapper`, a `#!/bin/bash` script. A selected log line can be an
environment assignment such as `BASH_ENV=/config/swupgrade/new.loads.factoryreset-save`;
the path contains `swupgrade` for the grep filter. That payload path is also
on the cleaner keep list (line 571) and lies in the updater-owned directory.
Bash reads `BASH_ENV` before running the wrapper body, including its own
`verify-config-file` calls. `/config` is mounted `noexec`, but Bash reads the
startup file as data. The `sslc_wrapper_t` domain is permissive in the
packaged policy.

This execution route depends on the forwarder service starting after the
overwrite. Its `.path` unit is enabled under `multi-user.target.wants` and
starts the service when `/run/forward-to-metaproxy` exists. The marker is
produced by `local-pairing-proxy-check.service` when
`bin/should-support-http-proxy` accepts the platform/product; that script
accepts `Bifrost`/`Vecchio` and `Harmony`/`Vasco`, among others. The live
product identity, marker, service state, and installed policy have not been
checked on a Room Navigator. Overwriting pairing config could also disrupt
the forwarder after the startup file has run.

The persistent pairing-config route adds a forwarder-start condition and is
not needed for the same-boot SSH candidate when the no-reboot marker is in
place.

## Offline checks and limits

Using only disposable `/tmp` files, the host's `/bin/sh` reproduced the exact
pipeline/redirection/chmod structure with a symlinked destination. It
replaced the target's original contents with
`LD_PRELOAD=/mnt/base/active/tmp-upgrade/swupgrade.so\n`, changed target
mode from `0600` to `0664`, and left the symlink in place. This confirms POSIX
shell behavior, not the complete device service sequence. Separately, the
shipped BusyBox `chmod` applet was run under QEMU on a disposable symlink:
it changed the target from `0600` to `0664`, and QEMU traced
`fchmodat(..., 0664, 0)`. The shipped
`/bin/sh` points to the firmware Bash; that Bash failed to run under the
available QEMU user-mode setup with an internal `xmalloc` error even for a
plain `-c 'echo hello'`, so no firmware-Bash execution result is claimed.

No codec-only, unauthenticated HTTP, or live root escalation was demonstrated.
The entry condition remains local control of a `swupgrade`-identity process,
plus an actual `main` termination that starts `post-main@.service` and a later
root SSH service restart or forwarder start. The already identified `peripheral-swsync` startup
`chown` chain has fewer timing requirements.
