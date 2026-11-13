#!/usr/bin/env python3
"""Audit the ram111 SMPS1 observation image before any device trial."""
import gzip
import json
from pathlib import Path
import re
import subprocess

from common import HERE, ROOT, SOURCE, WORK, audit_archive, sha

BASE = ROOT / 'development/perrier-ramenv/smp-boot-two'
IMAGE = ROOT / 'development/perrier-ramenv/smps1-observe'


def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def dt_text(path):
    dtc = IMAGE / 'kernel-build/scripts/dtc/dtc'
    return subprocess.run([dtc, '-I', 'dtb', '-O', 'dts', '-q', path],
                          check=True, capture_output=True, text=True).stdout


def main():
    raise RuntimeError('ram111 was invalidated: CTL-I2C does not expose the live SmartReflex selector')
    manifest = json.loads((IMAGE / 'manifest.json').read_text())
    baseline = json.loads((BASE / 'reviewed-image.json').read_text())
    assert baseline['passed'] and baseline['kernel'] == '6.18.48-perrier-ram110'
    assert manifest['kernel'] == '6.18.48-perrier-ram111'
    assert manifest['profile'] == 'smps1-observe'
    assert manifest['watchdog_backend'] == 'linux-watchdog'
    assert manifest['guard_sha256'] == baseline['guard_sha256']
    for item in manifest['artifacts'].values():
        path = Path(item['path'])
        assert path.stat().st_size == item['size'] and sha(path) == item['sha256'], path
    for item in manifest['inputs'].values():
        assert sha(item['path']) == item['sha256'], item['path']
    for key, path in {
        'rootfs_manifest_sha256': IMAGE / 'rootfs-manifest.json',
        'initramfs_sha256': IMAGE / 'initramfs.cpio',
        'kernel_config_sha256': IMAGE / 'kernel-build/.config',
        'guard_sha256': IMAGE / 'rootfs/usr/sbin/ram-guard',
    }.items():
        assert sha(path) == manifest[key], key
    proof = json.loads((ROOT / 'development/perrier-ramenv/native-watchdog/watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['stock_recovered']
    assert proof['guard_sha256'] == manifest['guard_sha256']

    old = config(BASE / 'kernel-build/.config')
    new = config(IMAGE / 'kernel-build/.config')
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    assert changed == {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE',
                       'CONFIG_REGULATOR_TWL4030'}, changed
    assert new['CONFIG_REGULATOR_TWL4030'] == 'y'
    assert new['CONFIG_LOCALVERSION'] == '"-perrier-ram111"'
    assert new['CONFIG_INITRAMFS_SOURCE'] == '"' + str(IMAGE / 'initramfs.cpio') + '"'
    for key in ('CONFIG_SMP', 'CONFIG_HOTPLUG_CPU', 'CONFIG_WATCHDOG_NOWAYOUT',
                'CONFIG_OMAP_WATCHDOG'):
        assert new[key] == 'y', key
    assert new['CONFIG_NR_CPUS'] == '2'
    assert new.get('CONFIG_CPU_FREQ') != 'y'

    before = json.loads((BASE / 'rootfs-manifest.json').read_text())
    after = json.loads((IMAGE / 'rootfs-manifest.json').read_text())
    assert {name for name in before.keys() | after.keys()
            if before.get(name) != after.get(name)} == {'etc/init.d/rcS'}
    assert (IMAGE / 'rootfs/etc/init.d/rcS').read_text() == \
        (BASE / 'rootfs/etc/init.d/rcS').read_text().replace('ram110', 'ram111')
    audit_archive(IMAGE / 'initramfs.cpio', after)
    packed = (IMAGE / 'kernel-build/usr/initramfs_inc_data').read_bytes()
    assert gzip.decompress(packed) == (IMAGE / 'initramfs.cpio').read_bytes()
    assert packed in (IMAGE / 'kernel-build/vmlinux').read_bytes()

    patches = json.loads((HERE / 'patches/manifest.json').read_text())
    for name, item in patches['files'].items():
        assert sha(SOURCE / name) == sha(WORK / name) == item['after_sha256'], name
    driver = (SOURCE / 'drivers/regulator/twl6030-regulator.c').read_text()
    ops = re.search(r'twl6032smps1_readonly_ops = \{([^}]+)\}', driver)
    assert ops and re.findall(r'\.([a-z_]+)\s*=', ops.group(1)) == ['get_voltage']
    assert 'twl6032smps1_get_voltage' in (IMAGE / 'kernel-build/System.map').read_text()
    assert '0x30 PM_RECEIVER base + 0x21 bank + 4 = 0x55' in driver
    assert 'SMPS_MULTOFFSET_SMPS1\tBIT(3)' in driver
    assert 'TWL6030_SMPS_OFFSET' in driver

    old_dt = dt_text(BASE / 'board.dtb')
    new_dt = dt_text(IMAGE / 'board.dtb')
    node = re.search(r'\n\s*regulator-smps1 \{\n[^{}]*\n\s*\};', new_dt)
    assert node and 'compatible = "ti,twl6032-smps1";' in node.group()
    assert new_dt.replace(node.group(), '') == old_dt, 'Unexpected DTB change'
    assert 'vcc-supply' not in new_dt

    symbols = (IMAGE / 'kernel-build/System.map').read_text().splitlines()
    end = next(int(line.split()[0], 16) for line in symbols if line.endswith(' _end'))
    span = end - 0xc0000000
    assert span < 0x02000000
    result = {'offline_audit_passed': True, 'live_tested': False,
              'kernel': manifest['kernel'], 'kernel_span_bytes': span,
              'config_delta': sorted(changed), 'rootfs_delta': ['etc/init.d/rcS'],
              'dtb_delta': ['regulator-smps1'],
              'watchdog_guard_sha256': manifest['guard_sha256'],
              'manifest_sha256': sha(IMAGE / 'manifest.json')}
    (IMAGE / 'offline-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    review = dict(manifest, passed=True, live_tested=False,
                  kernel_span_bytes=span, changed_rootfs=['etc/init.d/rcS'],
                  board_dtb_only_smps1_node=True,
                  watchdog_proof_preserved=True,
                  cpu1_boot_policy_identical_to_ram110=True,
                  cpu_frequency_and_voltage_writes_disabled=True)
    (IMAGE / 'reviewed-image.json').write_text(json.dumps(review, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
