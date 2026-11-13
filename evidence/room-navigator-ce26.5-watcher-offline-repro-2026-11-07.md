# Room Navigator CE26.5 watcher offline reproduction, 2026-11-07

## Test boundary

Ran the exact extracted ARM64 `/sbin/updatesw` binary (SHA-256
`9ca01c92dec305353a36ae984fbf46e48d2e404916aad810e9bf8e5ea4c45a3c`)
with QEMU user mode 11.1.3 inside bubblewrap 0.13.1. Bubblewrap bound a
disposable `/tmp/touch10-updatesw-lab/root` as `/`, mounted host `/usr`
read-only for QEMU and a shell, and mounted the extracted firmware rootfs
read-only at `/armroot` for ARM libraries. The watcher ran as the host user,
not root. There was no device connection and no firmware installation.

The sandbox's `/sbin/installimage` was a three-line fake script that logged
its arguments and returned status 23 without touching the supplied path:

```sh
#!/bin/sh
printf '%s\n' "$*" > /run/fake-installimage-args
exit 23
```

Before the event, the sandbox contained
`/proof/remove-me/child` with text `sentinel`. The watcher was started with
`-v -i /sbin/installimage -p /upgrade/pkg -c /upgrade/cop
-e /run/install-error`. The `-i` argument pointed to the sandbox's fake
installer; its default installed path is also `/sbin/installimage`.
After the watcher was running, a control file containing
`-f /proof/remove-me` was moved into the sandbox's `/upgrade/installimage`,
triggering the watched `IN_MOVED_TO` event.

## Observed result

The watcher's output was:

```text
updatesw: detected 'installimage'
updatesw: Failed to run installimage
updatesw: /proof/remove-me is a directory
```

`/run/fake-installimage-args` contained `-f /proof/remove-me`, proving the
fake installer was invoked. `/run/install-error` contained
`Invalid software package received`. The control file disappeared, and
`/proof/remove-me` and its `child` were absent after the failure. The
watcher stayed running until it was stopped with SIGINT.

This confirms the static finding that the exact watcher removes a
caller-named directory **outside `/upgrade`**, recursively, after a failed
installer invocation. The fake installer did not delete it. The test does
not demonstrate device-root privileges or a remote route to create the
control file. The [SELinux follow-up](room-navigator-ce26.5-selinux-followup-2026-11-07.md)
shows the packaged policy and Unix permissions permit the shipped `main`
and `vega` processes to create such a control file. The normal Vega admin
upgrade route writes fixed path arguments; live labels and a route to
supply arbitrary path arguments remain unmeasured.

## Reproduction outline

The sandbox was built under `/tmp` with directories `usr`, `sbin`, `dev`,
`proc`, `armroot`, `upgrade`, `run`, `tmp`, and `proof/remove-me`; `/bin`
and `/lib64` were symlinks to `usr/bin` and `usr/lib`. The exact watcher
launch command was:

```sh
bwrap --bind /tmp/touch10-updatesw-lab/root / \
  --ro-bind /usr /usr \
  --ro-bind /home/marius/ext_proj/touch10/firmware/room-navigator-ce26.5/rootfs-unpacked /armroot \
  --dev-bind /dev /dev --proc /proc -- \
  /usr/bin/qemu-aarch64 -L /armroot /armroot/sbin/updatesw \
  -v -i /sbin/installimage -p /upgrade/pkg -c /upgrade/cop \
  -e /run/install-error
```

The input file was prepared under the sandbox's `/tmp` and moved to its
`/upgrade/installimage` after the watcher started. The only deletion target
was the disposable sandbox directory.
