#!/usr/bin/env python3
"""Freeze an audited candidate before live testing, without overwriting baselines."""
import json
import os
from pathlib import Path
import shutil
import tempfile

from common import HERE, IMAGE, ROOT, sha


def main():
    os.umask(0o077)
    review = json.loads((IMAGE / 'reviewed-image.json').read_text())
    checks = json.loads((HERE / 'out/source-checks.json').read_text())
    assert review['passed'] and checks['passed']
    assert checks['source_manifest_sha256'] == sha(HERE / 'patches/manifest.json')
    assert checks['board_dtb_sha256'] == sha(IMAGE / 'board.dtb')
    assert review['inputs']['source_manifest']['sha256'] == checks['source_manifest_sha256']
    version = review['kernel'].removeprefix('6.18.48-perrier-')
    if not version.startswith('ram') or not version[3:].isdigit():
        raise ValueError('Unexpected kernel version')
    for item in review['artifacts'].values():
        assert sha(item['path']) == item['sha256']
    destination = HERE / 'baselines' / version
    if destination.exists():
        raise FileExistsError('Preserved baseline already exists: ' + str(destination))
    paths = {p: p.relative_to(HERE) for p in HERE.glob('*.py')}
    paths[HERE / 'remaining-support.md'] = Path('remaining-support.md')
    for folder in ('source', 'patches', 'configs', 'diagnostics'):
        paths.update({p: p.relative_to(HERE) for p in (HERE / folder).rglob('*')
                      if p.is_file() and '__pycache__' not in p.parts})
    for p in (HERE / 'tests').glob('*.py'):
        paths[p] = p.relative_to(HERE)
    for p in (HERE / 'tests/fixtures').iterdir():
        if p.is_file():
            paths[p] = p.relative_to(HERE)
    reports = {
        'reviewed-image.json': IMAGE / 'reviewed-image.json',
        'source-checks.json': HERE / 'out/source-checks.json',
        'source-tree-verification.json': HERE / 'out/source-tree-verification.json',
        'bus-audit-tests.json': HERE / 'out/bus-audit-tests.json',
        'plan.json': HERE / 'out/audio/plan.json',
        'led-audit-tests.json': HERE / 'out/led-audit-tests.json',
        'qt-main.cpp': ROOT / 'development/perrier-qt/app/main.cpp',
        'qt-Main.qml': ROOT / 'development/perrier-qt/app/Main.qml',
        'qt-runtime-manifest.json': ROOT / 'development/perrier-qt/runtime-manifest.json',
        'qt-preflight.log': HERE / 'out/application-audio/qt-preflight.log',
        'peripheral-audit-tests.json': HERE / 'out/peripheral-audit-tests.json',
        'stock-inventory.log': HERE / 'out/rtc-expander-audio/stock-inventory.log',
        'stock-rtc-gpio-clocks.log': HERE / 'out/rtc-expander-audio/stock-rtc-gpio-clocks.log',
        'stock-expander-analysis.json': HERE / 'out/rtc-expander-audio/stock-expander-analysis.json',
        'rtc-gpio-check': HERE / 'out/rtc-expander-audio/rtc-gpio-check',
        'rtc-alarm-check': HERE / 'out/rtc-expander-audio/rtc-alarm-check',
        'stock-alsa-controls.log': HERE / 'out/rtc-expander-audio/stock-alsa-controls.log',
        'stock-audio-pads-gpio-clock-index.log': HERE / 'out/rtc-expander-audio/stock-audio-pads-gpio-clock-index.log',
        'aux-audit-tests.json': HERE / 'out/aux-audit-tests.json',
        'pcf-shutdown-tests.json': HERE / 'out/pcf-shutdown-tests.json',
        'audio-audit-tests.json': HERE / 'out/audio-audit-tests.json',
        'stock-audio-mapping.json': HERE / 'out/audio/stock-audio-mapping.json',
        'stock-route-table.json': HERE / 'out/audio/stock-route-table.json',
        'stock-dapm-supplies-clocks.log': HERE / 'out/audio/stock-dapm-supplies-clocks.log',
        'stock-audio-pads-rails.log': HERE / 'out/audio/stock-audio-pads-rails.log',
        'audio-tools-manifest.json': ROOT / 'development/audio/manifest.json',
        'audio-arm-toolchain.cmake': ROOT / 'development/audio/arm-toolchain.cmake',
        'tinymix': ROOT / 'development/audio/build/tinymix',
        'tinyplay': ROOT / 'development/audio/build/tinyplay',
        'tinypcminfo': ROOT / 'development/audio/build/tinypcminfo',
    }
    for name in ('build', 'audit', 'check-sources'):
        reports[f'{name}-{version}.log'] = HERE / f'out/application-audio/{name}-{version}.log'
    for name in ('audio_backend.cpp', 'audio_backend.h', 'CMakeLists.txt'):
        reports['qt-' + name] = ROOT / 'development/perrier-qt/app' / name
    for name in ('asound.conf', 'build_application_audio.py', 'test_conversion.py', 'application-manifest.json'):
        reports['application-' + name] = ROOT / 'development/audio' / name
    reports['conversion-checks.json'] = HERE / 'out/application-audio/conversion-checks.json'
    for test, source in (('dsi-timing', 'drivers/gpu/drm/omapdrm/dss/dsi.c'),
                         ('dsi-vc', 'drivers/gpu/drm/omapdrm/dss/dsi.c'),
                         ('dsi-null', 'drivers/gpu/drm/omapdrm/dss/dsi.c'),
                         ('dsi-power', 'drivers/gpu/drm/omapdrm/dss/dsi.c'),
                         ('bridge-regmap', 'drivers/gpu/drm/bridge/tc358775.c')):
        p = HERE / 'tests/out' / test / 'result.json'
        if p.exists():
            record = json.loads(p.read_text())
            if record['source_sha256'] == sha(HERE / 'source' / source):
                assert record['passed']
                reports[test + '-tests.json'] = p
    for name, p in reports.items():
        paths[p] = Path('reports') / name
    for name in ('tools/touch10_uboot.py', 'tools/touch10_ram.py',
                 'tools/test_touch10_uboot.py', 'development/perrier-watchdog/prepare_uboot.py',
                 'development/perrier-watchdog/audit_uboot.py'):
        paths[ROOT / name] = Path('runner') / name
    with tempfile.TemporaryDirectory(prefix=version + '-freeze-', dir=HERE / 'baselines') as folder:
        temporary = Path(folder) / version
        for source, relative in paths.items():
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            assert sha(target) == sha(source)
        files = {str(p.relative_to(temporary)): sha(p)
                 for p in sorted(temporary.rglob('*')) if p.is_file()}
        record = {'original_root': 'development/kernel', 'kernel': review['kernel'],
                  'profile': review['profile'],
                  'qualification_at_snapshot': 'offline passed; live qualification recorded separately',
                  'files': files}
        (temporary / 'snapshot.json').write_text(json.dumps(record, indent=2) + '\n')
        temporary.rename(destination)
    print(f'Frozen {version}: {len(files)} verified files at {destination}')


if __name__ == '__main__':
    main()
