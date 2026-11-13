# Room Navigator CE26.5 RWFS tar symlink follow-up, 2026-11-07

## Scope

Offline review of the CE26.5 Room Navigator package and extracted rootfs. No
device, host service, or installed filesystem was changed. The packaged
`/bin/tar` is the BusyBox 1.36.1 applet (`/bin/tar -> busybox`); BusyBox SHA-256
is `6724652ac1df2beeb659268122f3a1a7e67667cb076f6b3490e55aac81b7a743`.

## Which hook runs

`sbin/installimage:438-451` verifies the package signature before extraction;
`installimage:627-653` runs existing image `userdatahooks.d` hooks first and
then runs executable `postinstall.d` hooks from the newly installed package.
The existing image's
`share/installimage/userdatahooks.d/installimage-copy-rwfs.hook:58` appends
`10-save-rwfs.hook` to `/run/installimage/disabled-hooks`. Its line 5 exports
`EXTRACT_UNSAFE_SYMLINKS=1`, and line 31 uses
`(cd "$old_mp" && tar cf - .) | tar -xf - -C "$new_mp"`.

The package archive lists `postinstall.d/10-save-rwfs.hook.exec`. A selective,
disposable extraction with the packaged ARM64 `pkgextract -x -n -F ...` produced
`postinstall.d/10-save-rwfs.hook` mode 0755: the `.exec` suffix is removed on
installation. Therefore the disabled hook name matches the installed hook,
and this CE26.5-to-CE26.5 path runs the existing image's copy implementation
once. The packaged postinstall hook has substantially the same tar copy, but
can run when upgrading from an image without the current userdata hook.

The hook reads the **new signed rootfs's** `/etc/fstab` and selects entries
containing `x-save` (`userdatahooks.d/installimage-copy-rwfs.hook:82-111`). In
this package these are `/config` and `/storage`. Both are encrypted writable
filesystems mounted `nosuid,noexec,nodev` (`rootfs-unpacked/etc/fstab:1-2`).
For each, `/bin/createfs` creates a new encrypted filesystem image under the
inactive installation; the hook mounts it at a fresh `mktemp -d` directory and
copies the old mount's contents into it. The path to the new image comes from
the signed fstab entry and fixed inactive installation path, not from a name
inside `/config` or `/storage`.

## Exact BusyBox tar behavior checked offline

I ran the extracted ARM64 BusyBox through `qemu-aarch64 -L` against disposable
directories under `/tmp`. A source tree containing a normal file and
`escape -> ../outside` produced these archive entries from `tar cf - .`:

```text
.             directory
./escape      symlink -> ../outside
./ordinary    regular file
```

With `EXTRACT_UNSAFE_SYMLINKS=1`, `tar xf - -C <fresh destination>` returned
success, left `escape` as a symlink in the destination, and left the sibling
`outside` directory empty. The source `tar` command lacks `-h`, so it did not
descend through the symlink or archive a file below `escape`.

I also constructed an archive manually with `./escape -> ../outside` followed
by regular member `./escape/marker` and extracted it with the packaged BusyBox
and `EXTRACT_UNSAFE_SYMLINKS=1`. Extraction returned 1 with
`tar: can't create symlink './escape' to '../outside`; it did not create
`outside/marker`. This crafted archive is **not** what the hook's filesystem
walk normally emits, but checks whether the extractor follows an archived
link into a later member. A single absolute-target symlink was preserved both
with and without this environment variable in the same isolated test; the
test does not establish the variable's purpose in all cases.

## Assessment and limits

The hook preserves attacker-created symlinks from the old RWFS into the new
RWFS. That can carry a malicious `/config` link across an upgrade, including
the `extensions.json` link relevant to the separate root `chown` issue.
This review did **not** find a direct tar extraction escape: the source is a
filesystem walk without symlink dereference, and the destination is a freshly
created filesystem, not an attacker-prepared directory tree. Package
signature verification occurs before either hook executes. Concurrent
mutation of the source during `tar cf - .`, alternate older-image hooks, and
live runtime labels were not reproduced; the result does not rule out every
race or every later use of a preserved symlink.
