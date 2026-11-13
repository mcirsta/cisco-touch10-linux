# Room Navigator CE26.5 Vega upgrade writer follow-up, 2026-11-07

## Missing filesystem and writer

The Vega web application is in the package's separate `fs/web.img`
(SquashFS SHA-256
`365ed6277fc2f5b85f6998ce7ef25776e51671c4de321ad3d67819f9bdb7a742`),
not the rootfs image searched in the first audit. It was extracted to
`firmware/room-navigator-ce26.5/web-unpacked/`. Its source contains the
concrete writer of the watcher's `/upgrade/installimage` control file:

* `vega/vega/models/codec.py:53` defines `installimage_args_file` as
  `{.upgrade}/installimage`; `upgrade` is `{.prefix}/upgrade` (line 39), and
  the production `TouchPeripheral` model for `vecchio`/`vasco` inherits an
  empty prefix. The fixed uploaded codec-package path is
  `{.run}/web/uploads/swpkg/codec.pkg.req` (lines 69-71).
* `vega/vega/models/upgrade.py:144-151` starts `UpgradeThread` with that
  fixed filename after a package has been parsed. `UpgradeThread.run`
  (lines 303-329) constructs `--file <filename> -o <offset>` or
  `--cop <filename> -o <offset> --size <size>` and calls
  `self.codec.installimage_args_file.write_text(install_args)` at line 324.
  `filename` comes from `CodecPackage`, `offset` and `size` are numeric
  multipart boundaries, and the package type only switches the flag.
  The request does not supply an arbitrary local path to this call.

The exact rootfs-wide `/upgrade/installimage` literal search found only
`sbin/updatesw` because Vega constructs the path from two strings in a
different image. The `bin/main` ELF has no such path literal; its three
`installimage` substrings concern a lock, a result file, and a separate
`swupgrade-initiated-upgrade` marker. A complete `main` decompilation was
not obtained, so dynamic construction there is not excluded by that
negative search.

## HTTP route and input control

`vega/vega/routes/__init__.py:190-195` registers POST
`/web/api/upgrade/upload` and `/web/api/upgrade/install`.
`vega/vega/webapi/upgrade.py:17` requires `roles.Upgrade |
roles.DisplayUpgrade`; both equal `ADMIN` in `vega/vega/models/roles.py:113-114`.
The base controller calls `auth.assert_permission` before the action;
unauthenticated requests get 401 and insufficient roles get 403.
Its CSRF redirector checks unsafe methods for session-based requests.

The upload action takes the reverse proxy's `X-File` header and moves that
server-side temporary request-body file to the fixed package path
(`webapi/upgrade.py:121-149`). The shipped Nginx upload configuration sets
`X-File` from its own `$request_body_file` and stores bodies under
`/run/web/uploads/swpkg`; the Vega backend listens on `127.0.0.1:3000`.
This configuration does not show an external client selecting `X-File` or
the local package path. The install action checks that the fixed package
exists, parses its header, and starts `UpgradeThread`
(`webapi/upgrade.py:177-207`). Signature verification happens later in the
root installer; parsing here is not a signature gate.

The normal **authenticated admin** web path therefore *does* trigger a
write to `/upgrade/installimage`, correcting the earlier missing-writer
assumption, but its path argument is fixed. It does not directly expose the
watcher's unrestricted deletion argument to an HTTP request. The web
application itself runs as `web` in `vega_t`; `web` belongs to the
`swupgrade` group and the packaged SELinux policy allows `vega_t` to create
files in the upgrade directory. A compromise of the Vega process could
write a differently populated control file and reach the deletion branch.
No unauthenticated web or codec-only route to arbitrary argument contents
was established.

## Additional symlink observation

`Path.write_text` follows an existing `/upgrade/installimage` symlink.
If another local actor first plants such a link, Vega could overwrite a
file writable by the `web` user with its fixed argument text. This is
separate from the watcher's root deletion, and no network-only symlink
planting route was found.
