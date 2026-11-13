#!/usr/bin/env python3
"""Export canonical source overrides as patches against Linux 6.18.48."""
import difflib
import hashlib
import json
from pathlib import Path
import tarfile

from common import HERE, ROOT, SOURCE, sha

ARCHIVE = ROOT / 'development/sources/linux-6.18.48.tar.xz'


def pristine(paths):
    wanted = {'linux-6.18.48/' + p: p for p in paths}
    files = {}
    with tarfile.open(ARCHIVE, 'r|xz') as archive:
        for member in archive:
            if member.name in wanted and member.isfile():
                files[wanted[member.name]] = archive.extractfile(member).read()
    return files


def main():
    paths = sorted(str(p.relative_to(SOURCE)) for p in SOURCE.rglob('*') if p.is_file())
    before = pristine(paths)
    groups = {
        '0001-dt-bindings-cyttsp4-perrier.patch': [],
        '0002-input-restore-cyttsp4-dt.patch': [],
        '0003-drm-omap-perrier-display.patch': [],
        '0004-arm-dts-cisco-perrier.patch': [],
        'ram-only/0001-perrier-ram-safety.patch': [],
    }
    safety = {'drivers/clk/ti/clk-44xx.c', 'arch/arm/mach-omap2/io.c', 'drivers/mmc/core/block.c'}
    records = {}
    for name in paths:
        old = before.get(name)
        new = (SOURCE / name).read_bytes()
        if name in safety:
            group = 'ram-only/0001-perrier-ram-safety.patch'
        elif name.startswith('drivers/gpu/'):
            group = '0003-drm-omap-perrier-display.patch'
        elif name.startswith('arch/arm/boot/dts/'):
            group = '0004-arm-dts-cisco-perrier.patch'
        elif name.startswith('Documentation/'):
            group = '0001-dt-bindings-cyttsp4-perrier.patch'
        else:
            group = '0002-input-restore-cyttsp4-dt.patch'
        diff = ''.join(difflib.unified_diff(
            old.decode().splitlines(True) if old is not None else [], new.decode().splitlines(True),
            fromfile='a/' + name if old is not None else '/dev/null', tofile='b/' + name))
        assert diff, 'Unchanged source override: ' + name
        groups[group].append('diff --git a/' + name + ' b/' + name + '\n' + diff)
        records[name] = {'before_sha256': hashlib.sha256(old).hexdigest() if old is not None else None,
                         'after_sha256': hashlib.sha256(new).hexdigest(), 'patch': group}
    patches = {}
    for name, chunks in groups.items():
        path = HERE / 'patches' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(chunks))
        patches[name] = sha(path)
    (HERE / 'patches/series').write_text('\n'.join(groups) + '\n')
    record = {'base_version': '6.18.48', 'base_archive': str(ARCHIVE),
              'base_archive_sha256': sha(ARCHIVE), 'patches': patches, 'files': records}
    (HERE / 'patches/manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Exported five patches; ordinary driver/board changes and RAM-only safeguards are separate')


if __name__ == '__main__':
    main()
