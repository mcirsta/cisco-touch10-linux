# Room Navigator CE26.5 fswatcher dispatch follow-up, 2026-11-07

## Scope and inputs

This is offline analysis of the extracted CE26.5 Room Navigator image, revision
`ce-26.5.0.50-44-gc49cadf5f59`. The exact ARM64
`rootfs-unpacked/bin/fswatcher` binary has SHA-256
`ef33aafeaed9fb34ad8991702a433e16580a7053b222f78dde98e3351a2a3b56`.
No Room Navigator was accessed or modified.

The shipped `/etc/fswatcher.conf` watches `/run/sysconfig.d` and loads
`/etc/sysconfig.services.d`. The latter's `sysconfig.swupgrade` maps a
`swupgrade` file event to both
`/bin/systemctl restart swupgrade.service` and
`/bin/systemctl restart peripheral-swsync.service`. The `sysconfig.ssh` map
contains `ssh=systemctl restart sshd.service`.

## Static binary trace

IDA decompilation of `main` at `0x81c0` shows an `inotify_add_watch` on each
configured directory with mask `0x88` (`IN_CLOSE_WRITE | IN_MOVED_TO`). The
event loop reads the event's **basename** and passes it to
`actiondb_register_modified` at `0x9500`. That function compares the basename
to each configured action's path/name and records a pending action; it does
not inspect the triggering file's owner, mode, contents, or type. At `0x95c0`,
`actiondb_foreach_modified` runs the pending action after a roughly one-second
delay. `run_action` at `0x9100` calls `run_command` at `0x235b0`, whose command
runner at `0x234c0` forks and calls `execvp`. The command string is loaded
from the shipped action map at startup. The packaged `fswatcher.service` has
no `User=` override, so systemd starts it as root.

Changing the ownership of an already watched directory does not replace its
inode or invalidate the inotify watch. This point follows from the watch being
installed on the directory inode; it was not tested with a real device `chown`.

## Isolated dispatch reproduction

I ran the exact ARM64 binary with QEMU user mode inside bubblewrap, bound the
extracted firmware read-only at `/armroot`, and used an unprivileged disposable
directory as `/`. The sandbox config watched `/run/sysconfig.d` and loaded the
firmware's **unchanged** `sysconfig.ssh` map. A fake `systemctl` script at
`/fakebin/systemctl` only wrote its arguments to `/run/action-ran`. Its path
was prepended to `PATH`, so host `systemctl` was never invoked.

The setup and trigger were:

```python
from pathlib import Path
import os, signal, subprocess, tempfile, time

root = Path(tempfile.mkdtemp(prefix='touch10-fswatcher-lab-', dir='/tmp'))
for d in ('etc', 'run/sysconfig.d', 'usr', 'armroot', 'dev', 'proc', 'fakebin'):
    (root / d).mkdir(parents=True, exist_ok=True)
(root / 'bin').symlink_to('usr/bin')
(root / 'lib64').symlink_to('usr/lib')
(root / 'etc/fswatcher.conf').write_text(
    'dir=/run/sysconfig.d\n'
    'config-file=/armroot/etc/sysconfig.services.d/sysconfig.ssh\n'
)
fake = root / 'fakebin/systemctl'
fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> /run/action-ran\n')
fake.chmod(0o755)
firmware = '/home/marius/ext_proj/touch10/firmware/room-navigator-ce26.5/rootfs-unpacked'
cmd = [
    'bwrap', '--bind', str(root), '/', '--ro-bind', '/usr', '/usr',
    '--ro-bind', firmware, '/armroot', '--dev-bind', '/dev', '/dev',
    '--proc', '/proc', '--', '/usr/bin/qemu-aarch64', '-L', '/armroot',
    '/armroot/bin/fswatcher', '-c', '/etc/fswatcher.conf',
]
with (root / 'run/fswatcher-output').open('w') as log:
    proc = subprocess.Popen(
        cmd, stdout=log, stderr=subprocess.STDOUT,
        env={**os.environ, 'PATH': '/fakebin:/usr/bin:/bin'},
        start_new_session=True,
    )
    try:
        time.sleep(2)
        print('before:', proc.poll())
        (root / 'run/sysconfig.d/ssh').write_text('ANY=content\n')
        time.sleep(4)
        print('after:', proc.poll())
        print('fake:', (root / 'run/action-ran').read_text())
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
print('watcher:', (root / 'run/fswatcher-output').read_text())
```

The actual lab was `/tmp/touch10-fswatcher-lab-egqk9n1t`. `proc.poll()` was
`None` before and after the event. `/run/action-ran` contained
`restart sshd.service`; watcher output contained
`Running action systemctl restart sshd.service`. Thus a file created by the
unprivileged test process dispatched the firmware-defined action. The fake
command had no service or device effect.

This confirms the watcher dispatch and absence of a file-ownership check for
the tested `ssh` mapping. The identical watcher code loads the shipped
`swupgrade` mapping, but that exact mapping was not executed in this test.
Live SELinux labels, service state, and the separate symlink/chown prerequisite
remain outside this reproduction.
