#!/usr/bin/env python3
"""Freeze the validated volatile DHCP route/DNS and lease-loss RAM image."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from common import HERE, ROOT, SOURCE, sha

VERSION = 'ram107'
KERNEL = '6.18.48-perrier-ram107'
IMAGE = ROOT / 'development/perrier-ramenv/network-route-dns'
RUN = ROOT / 'development/runs/20261112T154108Z-uboot-ram107-80e01b'
DEST = HERE / 'baselines' / VERSION
FACTORY_P8 = 'f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad'


def main():
    review = json.loads((IMAGE / 'reviewed-image.json').read_text())
    result = json.loads((RUN / 'result.json').read_text())
    source = json.loads((HERE / 'out/source-tree-verification.json').read_text())
    patch_manifest = json.loads((HERE / 'patches/manifest.json').read_text())
    loss = (RUN / 'dhcp-loss.log').read_text()
    renewed = (RUN / 'dhcp-post-loss-renew.log').read_text()
    assert review['passed'] and review['kernel'] == KERNEL
    assert review['board_dtb_identical_to_ram105']
    assert source['passed'] and source['source_manifest_sha256'] == sha(HERE / 'patches/manifest.json')
    assert review['inputs']['source_manifest']['sha256'] == source['source_manifest_sha256']
    assert result['status'] == 'passed' and result['stock_recovered']
    assert result['profile'] == 'network-route-dns' and result['ram']['kernel'] == KERNEL
    assert result['stock_p8_sha256'] == FACTORY_P8
    assert result['adc_postflight']['passed'] and result['adc_postflight']['restored'] == \
        {'48:e4': '00', '49:04': '04', '49:06': '14'}
    assert all(result['markers'].values()) and result['qt_started']
    for item in review['artifacts'].values():
        assert sha(item['path']) == item['sha256']
    assert loss.startswith('deconfig\n') and 'LEASE_LOSS_CLEANUP_PASSED' in loss
    assert 'inet 10.77.10.11/24' in loss and 'inet 10.77.10.10/24' not in loss
    assert renewed.startswith('renew interface=eth0 ip=10.77.10.10')
    assert 'inet 10.77.10.11/24' in renewed and 'inet 10.77.10.10/24' in renewed
    assert 'default via' not in renewed and '"state":"feeding"' in renewed
    assert renewed.rstrip().endswith('1')  # eMMC ro flag
    checks = {
        'passed': True, 'kernel': KERNEL, 'boot_id': result['ram']['boot_id'],
        'real_dhcp_address_and_renewal': True,
        'route_dns_test_event_applied_and_real_renewal_removed_both': True,
        'rescue_ssh_lease_loss_and_rebind': True,
        'emmc_readonly_and_unmounted': True, 'watchdog_feeding': True,
        'no_display_reset_or_qt_restart_performed': True,
        'stock_recovered_and_adc_postflight_passed': True,
        'route_dns_dhcp_server_delivery_tested': False,
    }
    (RUN / 'machine-checks.json').write_text(json.dumps(checks, indent=2) + '\n')
    source_checks = {
        'passed': True, 'kernel': KERNEL,
        'source_manifest_sha256': source['source_manifest_sha256'],
        'board_dtb_sha256': sha(IMAGE / 'board.dtb'),
        'source_tree_verification_sha256': sha(HERE / 'out/source-tree-verification.json'),
        'dt_identical_to_ram106': sha(IMAGE / 'board.dtb') ==
        sha(ROOT / 'development/perrier-ramenv/network-dhcp/board.dtb'),
        'kernel_config_changes_from_ram106': [],
    }
    assert source_checks['dt_identical_to_ram106']
    if DEST.exists():
        raise FileExistsError(DEST)
    paths = {}
    for name in patch_manifest['files']:
        paths[SOURCE / name] = Path('source') / name
    for path in (HERE / 'patches').rglob('*'):
        if path.is_file():
            paths[path] = Path('patches') / path.relative_to(HERE / 'patches')
    for name in ('build_ram107.py', 'audit_ram107.py', 'freeze_ram107.py',
                 'export_patches.py', 'prepare_source.py', 'record_validation.py',
                 'common.py', 'network-route-dns.md', 'expander-pin-investigation.md'):
        paths[HERE / name] = Path(name)
    for name in ('dhcp-apply-route-dns.sh', 'test_dhcp_apply.py'):
        paths[HERE / 'network' / name] = Path('network') / name
    paths[HERE / 'configs/perrier-ram107.config'] = Path('configs/perrier-ram107.config')
    for name in ('touch10_uboot.py', 'touch10_ram.py', 'touch10_dev.py',
                 'test_touch10_uboot.py', 'test_touch10_ram_identity.py'):
        paths[ROOT / 'tools' / name] = Path('runner') / name
    for name in ('prepare_uboot.py', 'audit_uboot.py'):
        paths[ROOT / 'development/perrier-watchdog' / name] = Path('runner') / name
    for name in ('reviewed-image.json', 'manifest.json', 'board.dtb',
                 'kernel-build/arch/arm/boot/zImage'):
        paths[IMAGE / name] = Path('image') / name
    for name in ('result.json', 'dhcp-loss.log', 'dhcp-post-loss-renew.log',
                 'machine-checks.json'):
        paths[RUN / name] = Path('reports') / name
    paths[HERE / 'out/source-tree-verification.json'] = Path('reports/source-tree-verification.json')
    with tempfile.TemporaryDirectory(prefix='ram107-freeze-', dir=HERE / 'baselines') as folder:
        temp = Path(folder) / VERSION
        for source_path, relative in paths.items():
            target = temp / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            assert sha(target) == sha(source_path)
        (temp / 'reports/source-checks.json').write_text(json.dumps(source_checks, indent=2) + '\n')
        files = {str(path.relative_to(temp)): sha(path)
                 for path in sorted(temp.rglob('*')) if path.is_file()}
        snapshot = {'kernel': KERNEL, 'profile': 'network-route-dns',
                    'qualification_at_snapshot': 'live passed and stock recovered',
                    'files': files}
        (temp / 'snapshot.json').write_text(json.dumps(snapshot, indent=2) + '\n')
        temp.rename(DEST)
    print('Frozen', VERSION, 'files', len(files), 'at', DEST)


if __name__ == '__main__':
    main()
