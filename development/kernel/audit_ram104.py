#!/usr/bin/env python3
"""Audit the provider-only ram104 kernel and shared-audio initramfs."""
import gzip
import hashlib
import json
from pathlib import Path
import runpy
import stat

from common import ROOT, HERE, SOURCE, WORK, audit_archive, sha

IMAGE = ROOT / 'development/perrier-ramenv/mailbox-audio-dt'
BASE = ROOT / 'development/perrier-ramenv/native-diagnostics'
AUDIO = ROOT / 'development/audio'


def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def main():
    manifest = json.loads((IMAGE / 'manifest.json').read_text())
    base = json.loads((BASE / 'reviewed-image.json').read_text())
    assert base['passed'] and base['kernel'] == '6.18.48-perrier-ram100'
    assert manifest['kernel'] == '6.18.48-perrier-ram104'
    assert manifest['profile'] == 'mailbox-audio-dt'
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
    assert manifest['guard_sha256'] == base['guard_sha256']
    proof = json.loads((ROOT / 'development/perrier-ramenv/native-watchdog/watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['stock_recovered']
    assert proof['guard_sha256'] == manifest['guard_sha256']
    patches = json.loads((HERE / 'patches/manifest.json').read_text())
    baseline_patches = json.loads((HERE / 'baselines/ram100/patches/manifest.json').read_text())
    new_dts = 'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier-mailbox-ram.dts'
    makefile = 'arch/arm/boot/dts/ti/omap/Makefile'
    assert set(patches['files']) == set(baseline_patches['files']) | {new_dts}
    assert patches['files'][new_dts]['before_sha256'] is None
    for name, item in baseline_patches['files'].items():
        if name == makefile:
            assert item['before_sha256'] == patches['files'][name]['before_sha256']
            assert item['after_sha256'] != patches['files'][name]['after_sha256']
            original = (HERE / 'baselines/ram100/source' / name).read_text()
            updated = (SOURCE / name).read_text()
            assert updated == original.replace('omap4-cisco-perrier-ram.dtb \\\n',
                                               'omap4-cisco-perrier-ram.dtb \\\n\tomap4-cisco-perrier-mailbox-ram.dtb \\\n')
        else:
            assert item == patches['files'][name], name
    for name, item in patches['files'].items():
        assert sha(SOURCE / name) == sha(WORK / name) == item['after_sha256'], name
    for name in ('drivers/mailbox/omap-mailbox.c',
                 'drivers/hwspinlock/omap_hwspinlock.c'):
        assert name not in patches['files'], name
    parse = runpy.run_path(str(ROOT / 'development/perrier-simpledrm/audit.py'))['fdt_nodes']
    old_dt = parse((BASE / 'board.dtb').read_bytes())
    new_dt = parse((IMAGE / 'board.dtb').read_bytes())
    assert set(old_dt) == set(new_dt)
    segment = '/ocp/interconnect@4a000000/segment@80000'
    changes = {path: {key for key in old_dt[path].keys() | new_dt[path].keys()
                      if old_dt[path].get(key) != new_dt[path].get(key)}
               for path in old_dt}
    changes = {path: props for path, props in changes.items() if props}
    expected = {segment: {'status'}}
    for offset in ('2b000', '2d000', '36000', '4d000', '59000', '5b000', '5d000'):
        expected[segment + '/target-module@' + offset] = {'status'}
    for offset in ('74000', '76000'):
        expected[segment + '/target-module@' + offset] = {'status', 'ti,no-reset-on-init'}
    assert changes == expected, changes
    assert old_dt[segment]['status'] == b'disabled\0'
    assert new_dt[segment]['status'] == b'okay\0'
    for path, fields in expected.items():
        if path == segment:
            continue
        assert new_dt[path]['status'] == (b'okay\0' if 'ti,no-reset-on-init' in fields
                                          else b'disabled\0'), path
        if 'ti,no-reset-on-init' in fields:
            assert new_dt[path]['ti,no-reset-on-init'] == b'', path

    old = config(BASE / 'kernel-build/.config')
    new = config(IMAGE / 'kernel-build/.config')
    changes = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    providers = {'CONFIG_MAILBOX', 'CONFIG_OMAP2PLUS_MBOX',
                 'CONFIG_HWSPINLOCK', 'CONFIG_HWSPINLOCK_OMAP'}
    assert changes == providers | {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE'}, changes
    assert all(new[key] == 'y' for key in providers)
    assert new['CONFIG_LOCALVERSION'] == '"-perrier-ram104"'
    assert new['CONFIG_INITRAMFS_SOURCE'] == '"' + str(IMAGE / 'initramfs.cpio') + '"'
    for key in ('CONFIG_CPU_FREQ', 'CONFIG_REGULATOR_TWL4030',
                'CONFIG_REGULATOR_TWL6030', 'CONFIG_REMOTEPROC',
                'CONFIG_OMAP_IOMMU', 'CONFIG_RTC_HCTOSYS'):
        assert new.get(key) != 'y', key
    for key in ('CONFIG_OMAP_WATCHDOG', 'CONFIG_WATCHDOG_NOWAYOUT',
                'CONFIG_TOUCHSCREEN_CYTTSP4'):
        assert new[key] == 'y', key

    before = json.loads((BASE / 'rootfs-manifest.json').read_text())
    after = json.loads((IMAGE / 'rootfs-manifest.json').read_text())
    changed = {'etc/init.d/rcS', 'etc/asound.conf', 'qt/lib/libasound.so.2'}
    assert {name for name in before.keys() | after.keys()
            if before.get(name) != after.get(name)} == changed
    assert (IMAGE / 'rootfs/etc/init.d/rcS').read_bytes() == \
        (BASE / 'rootfs/etc/init.d/rcS').read_bytes().replace(b'ram100', b'ram104')
    assert sha(IMAGE / 'rootfs/etc/asound.conf') == sha(AUDIO / 'asound-mix.conf')
    assert sha(IMAGE / 'rootfs/qt/lib/libasound.so.2') == \
        sha(AUDIO / 'shared-install/libasound-dmix.so.2')
    for name, item in after.items():
        path = IMAGE / 'rootfs' / name
        if 'symlink' in item:
            assert path.is_symlink() and str(path.readlink()) == item['symlink'], name
        else:
            assert sha(path) == item['sha256'] and path.stat().st_size == item['bytes'], name
    for name in ('etc/shadow', 'etc/dropbear/ram_host_key',
                 'root/.ssh/authorized_keys'):
        assert stat.S_IMODE((IMAGE / 'rootfs' / name).stat().st_mode) == 0o600
    audit_archive(IMAGE / 'initramfs.cpio', after)
    packed = (IMAGE / 'kernel-build/usr/initramfs_inc_data').read_bytes()
    assert gzip.decompress(packed) == (IMAGE / 'initramfs.cpio').read_bytes()
    assert packed in (IMAGE / 'kernel-build/vmlinux').read_bytes()
    symbols = (IMAGE / 'kernel-build/System.map').read_text().splitlines()
    image_end = next(int(line.split()[0], 16) for line in symbols if line.endswith(' _end'))
    span = image_end - 0xc0000000
    assert span < 0x02000000
    review = dict(manifest, passed=True, kernel_span_bytes=span,
                  changed_rootfs=sorted(changed), new_mainline_drivers=sorted(providers),
                  board_dtb_changes_isolated_to_mailbox_and_spinlock=True,
                  watchdog_proof_preserved=True,
                  emmc_ram_policy_inherited_from_ram100=True)
    (IMAGE / 'reviewed-image.json').write_text(json.dumps(review, indent=2) + '\n')
    print(json.dumps({'passed': True, 'kernel': manifest['kernel'],
                      'changed_rootfs': sorted(changed),
                      'new_config': sorted(providers), 'kernel_span_bytes': span}, indent=2))


if __name__ == '__main__':
    main()
