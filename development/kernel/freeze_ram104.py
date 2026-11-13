#!/usr/bin/env python3
"""Freeze the qualified mailbox/audio trial and its exact source evidence."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import tempfile

from common import HERE, ROOT, SOURCE, sha

VERSION = 'ram104'
KERNEL = '6.18.48-perrier-ram104'
IMAGE = ROOT / 'development/perrier-ramenv/mailbox-audio-dt'
RUN = ROOT / 'development/runs/20261112T141303Z-uboot-ram104-9d19fd'
DEST = HERE / 'baselines' / VERSION


def main():
    review = json.loads((IMAGE / 'reviewed-image.json').read_text())
    result = json.loads((RUN / 'result.json').read_text())
    audio = json.loads((RUN / 'packaged-dmix.json').read_text())
    source = json.loads((HERE / 'out/source-tree-verification.json').read_text())
    patch_manifest = json.loads((HERE / 'patches/manifest.json').read_text())
    live = (RUN / 'provider-live.log').read_text()
    health = (RUN / 'provider-health.log').read_text()
    assert review['passed'] and review['kernel'] == KERNEL
    assert review['board_dtb_changes_isolated_to_mailbox_and_spinlock']
    assert source['passed'] and source['source_manifest_sha256'] == sha(HERE / 'patches/manifest.json')
    assert review['inputs']['source_manifest']['sha256'] == source['source_manifest_sha256']
    assert result['status'] == 'passed' and result['stock_recovered']
    assert result['profile'] == 'mailbox-audio-dt' and result['ram']['kernel'] == KERNEL
    assert result['stock_p8_sha256'] == 'f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad'
    assert result['adc_postflight']['passed'] and result['adc_postflight']['restored'] == \
        {'48:e4': '00', '49:04': '04', '49:06': '14'}
    assert all(result['markers'].values()) and result['qt_started']
    assert audio['passed'] and audio['kernel'] == KERNEL
    assert audio['packaged']['first_exit'] == audio['packaged']['second_exit'] == 0
    for item in review['artifacts'].values():
        assert sha(item['path']) == item['sha256']
    assert 'kernel=' + KERNEL in live
    assert 'boot_id=' + result['ram']['boot_id'] in live
    assert 'qt_alive=yes' in live and 'emmc_ro=1' in live
    assert 'emmc_mounts=driver=omap-mailbox' in live
    assert 'remoteproc_class=absent' in live
    for address, driver in (('4a0f4000.mailbox', 'omap-mailbox'),
                            ('4a0f6000.spinlock', 'omap_hwspinlock')):
        assert address + ' -> ' in live and 'driver=' + driver in live
        assert address + ' driver=' in health and driver in health
        assert address + ' runtime_status=suspended' in health
    assert re.search(r'qt_pid=(\d+)', live).group(1) == \
        re.search(r'qt_pid=(\d+)', health).group(1)
    assert '"state":"feeding"' in health and '"nowayout":true' in health
    checks = {
        'passed': True, 'kernel': KERNEL, 'boot_id': result['ram']['boot_id'],
        'provider_bindings': ['4a0f4000.mailbox:omap-mailbox',
                              '4a0f6000.spinlock:omap_hwspinlock'],
        'providers_runtime_suspended': True, 'remoteproc_not_started': True,
        'emmc_readonly_and_unmounted': True, 'qt_pid_stable': True,
        'watchdog_feeding': True, 'packaged_two_client_dmix_passed': True,
        'no_display_reset_or_qt_restart_performed': True,
        'stock_recovered_and_adc_postflight_passed': True,
    }
    (RUN / 'machine-checks.json').write_text(json.dumps(checks, indent=2) + '\n')
    source_checks = {
        'passed': True, 'kernel': KERNEL,
        'source_manifest_sha256': source['source_manifest_sha256'],
        'board_dtb_sha256': sha(IMAGE / 'board.dtb'),
        'source_tree_verification_sha256': sha(HERE / 'out/source-tree-verification.json'),
        'dt_delta_exactly_audited': True, 'unmodified_upstream_provider_drivers': True,
    }
    if DEST.exists():
        raise FileExistsError(DEST)
    paths = {}
    for name in patch_manifest['files']:
        paths[SOURCE / name] = Path('source') / name
    for path in (HERE / 'patches').rglob('*'):
        if path.is_file():
            paths[path] = Path('patches') / path.relative_to(HERE / 'patches')
    for name in ('build_ram104.py', 'audit_ram104.py', 'export_patches.py',
                 'prepare_source.py', 'record_validation.py', 'common.py',
                 'remaining-support.md'):
        paths[HERE / name] = Path(name)
    paths[HERE / 'configs/perrier-ram104.config'] = Path('configs/perrier-ram104.config')
    for name in ('touch10_uboot.py', 'touch10_ram.py', 'touch10_dev.py',
                 'test_touch10_uboot.py'):
        paths[ROOT / 'tools' / name] = Path('runner') / name
    for name in ('prepare_uboot.py', 'audit_uboot.py'):
        paths[ROOT / 'development/perrier-watchdog' / name] = Path('runner') / name
    for name in ('asound-mix.conf', 'shared-install/libasound-dmix.so.2',
                 'build_dmix_lib.py', 'test_concurrent_playback.py'):
        paths[ROOT / 'development/audio' / name] = Path('audio') / name
    for name in ('reviewed-image.json', 'manifest.json', 'board.dtb',
                 'kernel-build/arch/arm/boot/zImage'):
        paths[IMAGE / name] = Path('image') / name
    for name in ('result.json', 'provider-live.log', 'provider-health.log',
                 'packaged-dmix.json', 'machine-checks.json', 'stage-cleanup.log'):
        path = RUN / name
        if path.exists():
            paths[path] = Path('reports') / name
    paths[HERE / 'out/source-tree-verification.json'] = Path('reports/source-tree-verification.json')
    with tempfile.TemporaryDirectory(prefix='ram104-freeze-', dir=HERE / 'baselines') as folder:
        temp = Path(folder) / VERSION
        for source_path, relative in paths.items():
            target = temp / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            assert sha(target) == sha(source_path)
        (temp / 'reports/source-checks.json').write_text(json.dumps(source_checks, indent=2) + '\n')
        files = {str(path.relative_to(temp)): sha(path)
                 for path in sorted(temp.rglob('*')) if path.is_file()}
        snapshot = {'kernel': KERNEL, 'profile': 'mailbox-audio-dt',
                    'qualification_at_snapshot': 'live passed and stock recovered',
                    'files': files}
        (temp / 'snapshot.json').write_text(json.dumps(snapshot, indent=2) + '\n')
        temp.rename(DEST)
    print('Frozen', VERSION, 'files', len(files), 'at', DEST)


if __name__ == '__main__':
    main()
