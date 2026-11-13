# Source layout and retained builds

The editable sources live in the normal project directories. Full upstream
checkouts and pre-Git source backups are not permanent working copies.

- `kernel/source/` and `kernel/patches/` contain the canonical board support.
- `standalone/kernel/` contains the ram116 CPU-voltage patch and configuration.
- `perrier-qt/app/`, the diagnostic C files and host Python tools remain in place.
- `standalone/inputs.json` pins the upstream source archives and Git commits.

Use `python3 development/standalone/build.py` from a clean clone to rebuild
the complete latest image. The build recreates its source trees and tools.
One compressed copy of each existing pinned upstream archive is retained
locally; duplicate expanded trees, installed runtimes and compiler caches
have been removed.

Future full builds perform this cleanup automatically after their audits.
They stage work under `standalone/out/.work/`, preserve unpublished source
changes under `source-preservation/auto/`, promote a compact image and retain
two successful bundles. Failed builds preserve changes and diagnostics before
removing partial compiler output. See the [build guide](standalone/README.md#automatic-cleanup-and-retention)
for recovery commands, runner deferral and the explicit debugging opt-out.

## Preserved unpublished changes

Local recovery records are under `development/source-preservation/2026-11-13/`.
This directory is excluded from public Git because it also contains ongoing,
unreviewed work and private diagnostic records. Its README documents recovery.
The same records are retained in the local-only Git branch
`local/source-preservation-2026-11-13`; that branch is not pushed. If the
working copies of the records are missing, recover them from the repository
root with:

```sh
umask 077
git archive local/source-preservation-2026-11-13 \
  development/source-preservation/2026-11-13 | tar -x
```

The source-tree snapshots retain only differences from a pinned upstream
archive. Content already committed is referenced by Git revision and path;
unpublished bytes, file modes, links and deletions are preserved explicitly.
The former kernel trees passed complete reconstruction checks, and one
ram116 tree was physically restored and verified before removal.

For example, restore a historical kernel source tree with:

```sh
python3 development/source-preservation/2026-11-13/preserve_kernel_trees.py restore \
  --tree ram116 --destination /tmp/touch10-ram116-source
```

`input-trees/README.md` covers the earlier Linux input tree, Qt changes,
modified kexec loader and other upstream checkouts. `unpublished-worktree/`
adds a safety copy of the ongoing Git diff and untracked source files; their
original editable files remain in place.

Generated-directory metadata keeps unique configurations, logs, readbacks
and manuals. Reproducible installed headers, generated CMake files and caches
are represented by provenance rather than copied again.

## Superseded checkpoints in Git

Historical source/patch/runner copies that were already committed are indexed
in the local `generated-metadata/checkpoint-source-history-index.json`.
Their exact bytes remain in revision
`cc8def6c88aa374209ff4acc0b9b501c97cbe648`. Restore an individual former path
from the repository root with:

```sh
git restore --source=cc8def6c88aa374209ff4acc0b9b501c97cbe648 -- path/to/file
```

Historical reports, measured fixtures, validation records and unique evidence
remain available. Older documents can still refer to the former source-copy
paths; use Git history or the local source snapshots to recover those versions.

## Two retained image bundles

The two retained image sets at consolidation were ram116 and ram117:

- `development/standalone/out/ram116/`
- `development/standalone/out/ram117/`

Each keeps `kernel-build/arch/arm/boot/zImage`, `board.dtb`, `initramfs.cpio`,
configuration and review/build records. `retained-build.json` identifies the
current files with relative paths. Compiler intermediates, unpacked rootfs
copies and older ram114/ram115/duplicate ram116 binaries were removed.

Ram117 was created by concurrent work during consolidation, so its source
differences are preserved too. The standalone builder targets ram116; ram117
is the newer experimental SmartReflex profile. These retained image sets
have host-side build reviews, not new hardware qualification from this task.
This consolidation does not change the device. The existing device backups,
access keys, firmware/reference originals and unique captured evidence remain
local and preserved. The standing ADC authorization JSON remains at its
documented runtime path. Its exact approved helper is retained with ram117;
the original runtime path links to that copy, so a repeated trial does not
require keeping or re-extracting a compiler just for recovery cleanup.
Automatic retention rehomes that exact approved helper when its bundle ages out.
