# Room Navigator CE26.5: `extensions.json` symlink reachability

Date: 2026-11-07. Scope: offline analysis of the extracted CE26.5 firmware and
Vega web image. No Room Navigator was accessed or modified.

## Question and result

The [ownership-change follow-up](room-navigator-ce26.5-chown-symlink-followup-2026-11-07.md)
requires a symlink at `/config/extensions/extensions.json` before the paired
`peripheral-swsync.service` next starts. The service runs its daemon as the
unprivileged `swupgrade` user, and `/config/extensions` is group-writable by
`swupgrade` (`rootfs-unpacked/lib/systemd/system/peripheral-swsync.service:9-16`,
`rootfs-unpacked/etc/tmpfiles.d/main.conf:10`). A process already executing as
`swupgrade` in the permissive `peripheral_swsync_t` domain can place the link.

I did **not** find a codec protocol operation or a reviewed Vega web route
that creates this symlink directly. The root chain therefore currently has a
**local `swupgrade` file-control prerequisite**. This is a bounded negative
finding, not proof that every network or xAPI path is safe.

## Paired codec receiver

IDA of packaged `rootfs-unpacked/bin/peripheral-swsync` shows
`SWSyncClient::receivePkg` at `0xc2f30` opens a fixed regular output
`/upgrade/pkg.tmp` and writes received bytes through `pug::recv_binary`, then
`handleCommitSoftware` at `0xbde30` renames it to `/upgrade/pkg`. The codec
does not select a symlink transfer method. For extensions,
`SWSyncClient::receiveExtension_` at `0xc08e0` formats
`upgrade/ext-{}.tmp` from a codec-supplied name, opens the path with
`O_RDWR|O_CREAT|O_TRUNC`, and calls `pug::recv_binary` on the resulting file
descriptor. This is a byte stream into an opened file, with no symlink
creation operation. The temporary extension name can involve a pre-existing
`ext-*` directory/link, as discussed in the [main audit](room-navigator-ce26.5-updater-symlink-audit-2026-11-07.md),
but no codec-only route to plant that link or to reach
`/config/extensions/extensions.json` was established.

The daemon's own metadata writer uses the fixed relative path
`extensions/extensions.json` (`save_path` at `0x132620`).
`write_metadata_cache` at `0x138cc0` builds `extensions.json.tmp`, opens it as
an output file, writes JSON, then calls `SoftwareUpgrade::move_file` at
`0x113400` to move the temporary file onto `extensions.json`. The latter
calls `std::filesystem::rename`; it replaces an existing symlink at the
destination with a regular file. It does not generate a symlink from codec
metadata. This also means that a cache refresh between an attacker's link
placement and the root pre-start could remove the link. The pre-start executes
before the daemon on a service restart, so this is a timing caveat rather than
a mitigation.

## Boot cleanup of a planted link

The packaged `filesystem-cleaner.service` runs after
`systemd-tmpfiles-setup.service` and before `sysinit.target` (`:4-16`), using
`/etc/filesystem-cleaner/config.json`. That configuration explicitly lists
`/config/extensions/extensions.json` under `keep` (`:214-220`). In an isolated
unprivileged bubblewrap/QEMU run of the exact ARM64 `filesystem-cleaner` with
the exact shipped configuration, a disposable
`/config/extensions/extensions.json -> /run/sysconfig.d` symlink remained a
symlink with the same target after the cleaner exited 0. The test was entirely
under `/tmp/touch10-cleaner-lab-pwjavnae`; no host `/config`, service, or device
was touched. The result supports persistence through this boot cleanup step,
but does not rule out later replacement by the metadata writer or other
services. There is no tmpfiles rule that creates `extensions.json`; the
packaged rule only creates its parent directory.

The sandbox ran the following command after creating the disposable symlink:

```text
bwrap --bind LAB / --ro-bind /usr /usr --ro-bind ROOTFS /armroot \
  --dev-bind /dev /dev --proc /proc -- \
  /usr/bin/qemu-aarch64 -L /armroot /armroot/bin/filesystem-cleaner \
  -d /config -c /armroot/etc/filesystem-cleaner/config.json
```

`LAB` was the temporary directory above and `ROOTFS` was the extracted CE26.5
`rootfs-unpacked` directory. Before and after, `is_symlink()` was true and
`readlink()` returned `/run/sysconfig.d`.

## Vega web application

The extracted Vega Python application contains no `/config/extensions` path
or extension API route in its reviewed source. Its admin upgrade upload route
(`webapi/upgrade.py:121-154`) moves the reverse proxy's upload file to the
fixed package destination specified in `models/codec.py:69-71`; the install
route writes a fixed package path into `/upgrade/installimage`. See the
[Vega writer follow-up](room-navigator-ce26.5-vega-writer-followup-2026-11-07.md)
for authentication and request-flow details. These routes do not offer a
filesystem link type or destination under `/config/extensions`.

The only `symlink_to` call found in Vega's Python source is certificate
management (`models/edgecertificates.py:71-83`). Its PUT controller rejects
`/` in the URL certificate id before calling that code
(`webapi/edge.py:43-48`), and the model uses the fixed certificate directory
from `models/codec.py:46-47`. I found no path from that route to
`extensions.json`.

## Limit

This review covers the paired receiver's file-transfer and metadata paths,
the extracted Vega Python routes, and the packaged service configuration. It
does not include a complete audit of the 54 MiB `main` binary, all xAPI
commands, or protocol authentication. A separate `swupgrade` code-execution
flaw, a local shell in that account, or a future device-specific route could
satisfy the prerequisite; none was demonstrated here.
