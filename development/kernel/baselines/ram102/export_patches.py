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
        '0003-drm-omap-pll-search.patch': [],
        '0004-drm-omap-dsi-host.patch': [],
        '0005-drm-bridge-tc358765.patch': [],
        '0006-drm-omap-perrier-sync.patch': [],
        '0007-arm-dts-cisco-perrier.patch': [],
        '0008-dt-bindings-twl-irq.patch': [],
        '0009-dt-bindings-pcf-retain-state.patch': [],
        '0010-gpio-pcf857x-retain-state.patch': [],
        '0011-asoc-twl6040-dt-routes.patch': [],
        'ram-only/0001-perrier-ram-safety.patch': [],
    }
    safety = {'drivers/clk/ti/clk-44xx.c', 'arch/arm/mach-omap2/io.c',
              'arch/arm/mach-omap2/perrier-pmu-probe.h', 'drivers/mmc/core/block.c'}
    records = {}
    for name in paths:
        old = before.get(name)
        new = (SOURCE / name).read_bytes()
        if name in safety:
            group = 'ram-only/0001-perrier-ram-safety.patch'
        elif name == 'drivers/gpu/drm/omapdrm/dss/pll.c':
            group = '0003-drm-omap-pll-search.patch'
        elif name in {'drivers/gpu/drm/omapdrm/dss/dsi.c',
                       'drivers/gpu/drm/omapdrm/dss/dsi.h'}:
            group = '0004-drm-omap-dsi-host.patch'
        elif name == 'drivers/gpu/drm/bridge/tc358775.c':
            group = '0005-drm-bridge-tc358765.patch'
        elif name.startswith('drivers/gpu/'):
            group = '0006-drm-omap-perrier-sync.patch'
        elif name.startswith('arch/arm/boot/dts/'):
            group = '0007-arm-dts-cisco-perrier.patch'
        elif name == 'Documentation/devicetree/bindings/mfd/ti,twl.yaml':
            group = '0008-dt-bindings-twl-irq.patch'
        elif name == 'Documentation/devicetree/bindings/gpio/nxp,pcf8575.yaml':
            group = '0009-dt-bindings-pcf-retain-state.patch'
        elif name == 'drivers/gpio/gpio-pcf857x.c':
            group = '0010-gpio-pcf857x-retain-state.patch'
        elif name == 'sound/soc/ti/omap-abe-twl6040.c':
            group = '0011-asoc-twl6040-dt-routes.patch'
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
    groups = {name: chunks for name, chunks in groups.items() if chunks}
    old_manifest = HERE / 'patches/manifest.json'
    if old_manifest.exists():
        old = json.loads(old_manifest.read_text())
        for name, digest in old['patches'].items():
            if name not in groups:
                path = HERE / 'patches' / name
                assert sha(path) == digest, 'Unrecorded generated-patch edit: ' + name
                path.unlink()
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
    print(f'Exported {len(groups)} patches; generic fixes, board support and RAM safeguards are separate')


if __name__ == '__main__':
    main()
