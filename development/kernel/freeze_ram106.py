#!/usr/bin/env python3
"""Freeze the qualified isolated DHCP address and renewal RAM image."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from common import HERE, ROOT, SOURCE, sha

VERSION = 'ram106'
KERNEL = '6.18.48-perrier-ram106'
IMAGE = ROOT / 'development/perrier-ramenv/network-dhcp'
RUN = ROOT / 'development/runs/20261112T152105Z-uboot-ram106-34efcd'
DEST = HERE / 'baselines' / VERSION
FACTORY_P8 = 'f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad'


def main():
    review = json.loads((IMAGE / 'reviewed-image.json').read_text())
    result = json.loads((RUN / 'result.json').read_text())
    source = json.loads((HERE / 'out/source-tree-verification.json').read_text())
    patch_manifest = json.loads((HERE / 'patches/manifest.json').read_text())
    live = (RUN / 'dhcp-renewal.log').read_text()
    rescue = (RUN / 'rescue-ssh.log').read_text()
    assert review['passed'] and review['kernel'] == KERNEL
    assert review['board_dtb_identical_to_ram105']
    assert source['passed'] and source['source_manifest_sha256'] == sha(HERE / 'patches/manifest.json')
    assert review['inputs']['source_manifest']['sha256'] == source['source_manifest_sha256']
    assert result['status'] == 'passed' and result['stock_recovered']
    assert result['profile'] == 'network-dhcp' and result['ram']['kernel'] == KERNEL
    assert result['stock_p8_sha256'] == FACTORY_P8
    assert result['adc_postflight']['passed'] and result['adc_postflight']['restored'] == \
        {'48:e4': '00', '49:04': '04', '49:06': '14'}
    assert all(result['markers'].values()) and result['qt_started']
    for item in review['artifacts'].values():
        assert sha(item['path']) == item['sha256']
    assert 'kernel=' + KERNEL in live
    assert 'boot_id=' + result['ram']['boot_id'] in live
    assert 'mac=24:16:9d:b6:77:bb' in live
    assert 'before=bound interface=eth0 ip=10.77.10.10 subnet=255.255.255.0' in live
    assert 'after=renew interface=eth0 ip=10.77.10.10 subnet=255.255.255.0' in live
    assert live.count('inet 10.77.10.11/24') == 2
    assert live.count('inet 10.77.10.10/24') == 2
    assert 'udhcpc: sending renew to server 10.77.10.1' in live
    assert 'default via' not in live
    assert 'qt_pid=126' in live and 'qt_after=126' in live
    assert '"state":"feeding"' in live and '"nowayout":true' in live
    assert KERNEL in rescue and result['ram']['boot_id'] in rescue
    assert 'renew interface=eth0 ip=10.77.10.10' in rescue
    assert '"state":"feeding"' in rescue
    checks = {
        'passed': True, 'kernel': KERNEL, 'boot_id': result['ram']['boot_id'],
        'dhcp_address_applied_and_renewed': True,
        'independent_rescue_ssh_passed': True,
        'no_router_or_dns_accepted_on_isolated_link': True,
        'emmc_readonly_and_unmounted': True, 'qt_pid_stable': True,
        'watchdog_feeding': True, 'no_display_reset_or_qt_restart_performed': True,
        'stock_recovered_and_adc_postflight_passed': True,
    }
    (RUN / 'machine-checks.json').write_text(json.dumps(checks, indent=2) + '\n')
    source_checks = {
        'passed': True, 'kernel': KERNEL,
        'source_manifest_sha256': source['source_manifest_sha256'],
        'board_dtb_sha256': sha(IMAGE / 'board.dtb'),
        'source_tree_verification_sha256': sha(HERE / 'out/source-tree-verification.json'),
        'dt_identical_to_ram105': True, 'unmodified_upstream_ipv6': True,
    }
    if DEST.exists():
        raise FileExistsError(DEST)
    paths = {}
    for name in patch_manifest['files']:
        paths[SOURCE / name] = Path('source') / name
    for path in (HERE / 'patches').rglob('*'):
        if path.is_file():
            paths[path] = Path('patches') / path.relative_to(HERE / 'patches')
    for name in ('build_ram106.py', 'audit_ram106.py', 'freeze_ram106.py',
                 'export_patches.py', 'prepare_source.py',
                 'record_validation.py', 'common.py'):
        paths[HERE / name] = Path(name)
    for name in ('dhcp-apply-isolated.sh', 'isolated-dhcp-policy.json'):
        paths[HERE / 'network' / name] = Path('network') / name
    paths[HERE / 'configs/perrier-ram106.config'] = Path('configs/perrier-ram106.config')
    for name in ('touch10_uboot.py', 'touch10_ram.py', 'touch10_dev.py',
                 'test_touch10_uboot.py', 'test_touch10_ram_identity.py'):
        paths[ROOT / 'tools' / name] = Path('runner') / name
    for name in ('prepare_uboot.py', 'audit_uboot.py'):
        paths[ROOT / 'development/perrier-watchdog' / name] = Path('runner') / name
    for name in ('reviewed-image.json', 'manifest.json', 'board.dtb',
                 'kernel-build/arch/arm/boot/zImage'):
        paths[IMAGE / name] = Path('image') / name
    for name in ('result.json', 'dhcp-renewal.log', 'rescue-ssh.log',
                 'machine-checks.json'):
        paths[RUN / name] = Path('reports') / name
    paths[ROOT / 'development/runs/20261112T151440Z-uboot-ram106-76ffce/result.json'] = \
        Path('reports/first-host-runner-failure.json')
    paths[HERE / 'out/source-tree-verification.json'] = Path('reports/source-tree-verification.json')
    with tempfile.TemporaryDirectory(prefix='ram106-freeze-', dir=HERE / 'baselines') as folder:
        temp = Path(folder) / VERSION
        for source_path, relative in paths.items():
            target = temp / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            assert sha(target) == sha(source_path)
        (temp / 'reports/source-checks.json').write_text(json.dumps(source_checks, indent=2) + '\n')
        files = {str(path.relative_to(temp)): sha(path)
                 for path in sorted(temp.rglob('*')) if path.is_file()}
        snapshot = {'kernel': KERNEL, 'profile': 'network-dhcp',
                    'qualification_at_snapshot': 'live passed and stock recovered',
                    'files': files}
        (temp / 'snapshot.json').write_text(json.dumps(snapshot, indent=2) + '\n')
        temp.rename(DEST)
    print('Frozen', VERSION, 'files', len(files), 'at', DEST)


if __name__ == '__main__':
    main()
