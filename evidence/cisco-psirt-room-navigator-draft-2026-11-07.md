# Draft for Cisco PSIRT — not sent

To: psirt@cisco.com  
Subject: Suspected local privilege escalation and updater path handling in Room Navigator CE26.5

Hello Cisco PSIRT,

I analyzed the publicly served Room Navigator `bifrost.pkg` at
`https://binaries.webex.com/collaboration-endpoint-ce-production-stable/20260415114153/bifrost.pkg`
offline. Its SHA-256 is
`5cae11d2a314890b48e8683b11ad6e819139a522a26c9aefaa4194cdfab3cc93`;
the extracted revision is `ce-26.5.0.50-44-gc49cadf5f59`. I found the
following possible privilege-boundary issues. I have not tested a live Room
Navigator or changed device state.

1. **Paired updater user to root through a symlink-following pre-start.**
   `/lib/systemd/system/peripheral-swsync.service` runs as `swupgrade`, but
   its privileged `ExecStartPre=+` runs
   `chown swupgrade /config/extensions/extensions.json` after `test -e`.
   `/config/extensions` is `2775 root:swupgrade`. The packaged BusyBox
   `chown` dereferences a symlink. A link at `extensions.json` to the existing
   `/run/sysconfig.d` changes that directory from `root:config` to
   `swupgrade:config`. A process already controlling the `swupgrade` account
   can then write `/run/sysconfig.d/ssh`. The packaged `fswatcher` restarts
   `sshd.service` on a change to that file; the root service reads it as an
   `EnvironmentFile` before executing its Bash `ExecStartPre` script. A
   `BASH_ENV` assignment in that file can cause Bash to read a file
   controlled by `swupgrade` before the pre-start script runs. This chain
   requires paired mode and a service start after link placement. The
   symlink, watcher dispatch, policy, and Bash behavior were checked offline
   in separate disposable tests; complete root execution on hardware has
   not been demonstrated.
2. **Root updater cleanup of a caller-selected path.** `/sbin/updatesw`
   accepts an existing path from `/upgrade/installimage`, calls
   `/sbin/installimage`, and removes the named path even if installation
   fails. A directory argument reaches a recursive `nftw` branch. An
   isolated run of the exact ARM64 watcher removed a named directory outside
   `/upgrade` after a fake installer failed. The normal authenticated admin
   Vega web upgrade route writes a fixed package pathname to this control
   file. Arbitrary control-file contents would require another way to
   control a local writer; I have not found a codec-only or unauthenticated
   network route to this primitive.
3. **Conditional root overwrite in `post-main@.service`.** Its root shell
   redirects selected event-log lines through
   `/config/swupgrade/previous-sysinfo.txt`, a path in an
   `swupgrade`-owned directory, and then follows the path with `chmod`.
   The `swupgrade` account can also influence the group-writable event log.
   A symlink to `/run/sysconfig.d/ssh` can supply a root service environment
   assignment and trigger `fswatcher`'s SSH restart. The symlinked watcher
   dispatch was reproduced offline; an attacker-controlled way to make
   `main` terminate at the necessary time has not been established.

The older Touch 10 CE9.9.0 `swsync`/`rsync`/`curl` method does not appear
unchanged in this image. I have not assigned a CVE to any of the findings
above. Cisco's July 2026 RoomOS hardening advisory groups multiple fixes by
broad CWE class, but does not identify these paths. Could you confirm whether
these behaviors are known and whether they remain in the current Room
Navigator image (the Cisco catalog lists `s53350ce26_7_4_3.pkg`)? The
catalog requires a Cisco login and valid service contract in my session, so
I could not compare a post-fix binary.

I can provide the detailed offline traces, isolated reproduction logs, and
file-level evidence privately. In particular, I have the packaged BusyBox
`fchownat(..., 0)` trace, `fswatcher` decompilation and dispatch log, and
the `updatesw` deletion reproduction. Please let me know the preferred
secure transfer method and whether these findings should be tracked under an
existing Cisco advisory or new cases.

Regards,

[Researcher name and contact information]

## Local supporting notes, not part of email body

- [Ownership-change chain](room-navigator-ce26.5-chown-symlink-followup-2026-11-07.md)
- [File-watcher dispatch](room-navigator-ce26.5-fswatcher-dispatch-followup-2026-11-07.md)
- [Updater audit](room-navigator-ce26.5-updater-symlink-audit-2026-11-07.md)
- [Updater deletion reproduction](room-navigator-ce26.5-watcher-offline-repro-2026-11-07.md)
- [Post-main chain](room-navigator-ce26.5-post-main-symlink-followup-2026-11-07.md)
- [Newer package access](room-navigator-newer-package-access-2026-11-07.md)
