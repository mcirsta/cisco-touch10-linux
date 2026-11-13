#!/usr/bin/env python3
"""Freeze the qualified IPv6 and DHCP-observation RAM image."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import tempfile

from common import HERE, ROOT, SOURCE, sha

VERSION = 'ram105'
KERNEL = '6.18.48-perrier-ram105'
IMAGE = ROOT / 'development/perrier-ramenv/network-dualstack'
RUN = ROOT / 'development/runs/20261112T144631Z-uboot-ram105-72df51'
DEST = HERE / 'baselines' / VERSION
FACTORY_P8 = 'f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad'


def main():
    review = json.loads((IMAGE / 'reviewed-image.json').read_text())
    result = json.loads((RUN / 'result.json').read_text())
    source = json.loads((HERE / 'out/source-tree-verification.json').read_text())
    patch_manifest = json.loads((HERE / 'patches/manifest.json').read_text())
    live = (RUN / 'network-live.log').read_text()
    peer = (RUN / 'ipv6-peer.log').read_text()
    clock = json.loads((RUN / 'ram-clock-sync.json').read_text())
    assert review['passed'] and review['kernel'] == KERNEL
    assert review['board_dtb_identical_to_ram104']
    assert source['passed'] and source['source_manifest_sha256'] == sha(HERE / 'patches/manifest.json')
    assert review['inputs']['source_manifest']['sha256'] == source['source_manifest_sha256']
    assert result['status'] == 'passed' and result['stock_recovered']
    assert result['profile'] == 'network-dualstack' and result['ram']['kernel'] == KERNEL
    assert result['stock_p8_sha256'] == FACTORY_P8
    assert result['adc_postflight']['passed'] and result['adc_postflight']['restored'] == \
        {'48:e4': '00', '49:04': '04', '49:06': '14'}
    assert all(result['markers'].values()) and result['qt_started']
    for item in review['artifacts'].values():
        assert sha(item['path']) == item['sha256']
    assert 'kernel=' + KERNEL in live
    assert 'boot_id=' + result['ram']['boot_id'] in live
    assert 'mac=24:16:9d:b6:77:bb' in live
    assert 'fe8000000000000026169dfffeb677bb' in live
    assert 'dhcp_exit=0' in live
    assert 'bound interface=eth0 ip=10.77.10.10 subnet=255.255.255.0' in live
    assert 'qt_alive=yes' in live and 'emmc_ro=1' in live
    assert '2 packets received' in peer and '0% packet loss' in peer
    assert clock['passed'] and clock['after']['kernel'] == KERNEL
    assert clock['after']['system_epoch'] == clock['host_epoch_sent']
    assert clock['before']['qt_pid'] == clock['after']['qt_pid']
    assert clock['after']['guard']['state'] == 'feeding'
    assert re.search(r'qt_pid=(\d+)', live).group(1) == str(clock['after']['qt_pid'])
    checks = {
        'passed': True, 'kernel': KERNEL, 'boot_id': result['ram']['boot_id'],
        'stock_mac_and_ipv6_link_local_matched': True,
        'ipv6_loopback_and_host_link_local_ping_passed': True,
        'bounded_dhcp_lease_observed_without_address_change': True,
        'host_time_set_in_volatile_system_clock_only': True,
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
        'dt_identical_to_ram104': True, 'unmodified_upstream_ipv6': True,
    }
    if DEST.exists():
        raise FileExistsError(DEST)
    paths = {}
    for name in patch_manifest['files']:
        paths[SOURCE / name] = Path('source') / name
    for path in (HERE / 'patches').rglob('*'):
        if path.is_file():
            paths[path] = Path('patches') / path.relative_to(HERE / 'patches')
    for name in ('build_ram105.py', 'audit_ram105.py', 'freeze_ram105.py',
                 'sync_ram_clock.py', 'export_patches.py', 'prepare_source.py',
                 'record_validation.py', 'common.py'):
        paths[HERE / name] = Path(name)
    for name in ('dhcp-observe.sh', 'test-lan.json'):
        paths[HERE / 'network' / name] = Path('network') / name
    paths[HERE / 'configs/perrier-ram105.config'] = Path('configs/perrier-ram105.config')
    for name in ('touch10_uboot.py', 'touch10_ram.py', 'touch10_dev.py',
                 'test_touch10_uboot.py'):
        paths[ROOT / 'tools' / name] = Path('runner') / name
    for name in ('prepare_uboot.py', 'audit_uboot.py'):
        paths[ROOT / 'development/perrier-watchdog' / name] = Path('runner') / name
    for name in ('reviewed-image.json', 'manifest.json', 'board.dtb',
                 'kernel-build/arch/arm/boot/zImage'):
        paths[IMAGE / name] = Path('image') / name
    for name in ('result.json', 'network-live.log', 'ipv6-peer.log',
                 'ram-clock-sync.json', 'machine-checks.json'):
        paths[RUN / name] = Path('reports') / name
    paths[HERE / 'out/source-tree-verification.json'] = Path('reports/source-tree-verification.json')
    with tempfile.TemporaryDirectory(prefix='ram105-freeze-', dir=HERE / 'baselines') as folder:
        temp = Path(folder) / VERSION
        for source_path, relative in paths.items():
            target = temp / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            assert sha(target) == sha(source_path)
        (temp / 'reports/source-checks.json').write_text(json.dumps(source_checks, indent=2) + '\n')
        files = {str(path.relative_to(temp)): sha(path)
                 for path in sorted(temp.rglob('*')) if path.is_file()}
        snapshot = {'kernel': KERNEL, 'profile': 'network-dualstack',
                    'qualification_at_snapshot': 'live passed and stock recovered',
                    'files': files}
        (temp / 'snapshot.json').write_text(json.dumps(snapshot, indent=2) + '\n')
        temp.rename(DEST)
    print('Frozen', VERSION, 'files', len(files), 'at', DEST)


if __name__ == '__main__':
    main()
