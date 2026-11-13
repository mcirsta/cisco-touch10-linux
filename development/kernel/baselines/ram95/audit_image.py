#!/usr/bin/env python3
"""Check the combined ram95 peripheral extension with unchanged display and power policy."""
import gzip
import hashlib
import json
from pathlib import Path
import stat
import subprocess

from common import BASELINE, HERE, IMAGE, ROOT, SOURCE, WORK, audit_archive, sha


def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def main():
    m = json.loads((IMAGE / 'manifest.json').read_text())
    assert m['kernel'] == '6.18.48-perrier-ram95' and m['profile'] == 'peripherals'
    baseline = json.loads((HERE / 'working-baseline.json').read_text())
    assert baseline['display_visible_and_aligned'] and baseline['native_gen4_touch_verified']
    assert baseline['hardware_expiry_verified'] and baseline['recovery_elapsed_seconds'] >= 100
    assert sha(baseline['result']) == baseline['result_sha256']
    for item in m['artifacts'].values():
        path = Path(item['path'])
        assert sha(path) == item['sha256'] and path.stat().st_size == item['size'], path
    for item in m['inputs'].values():
        assert sha(item['path']) == item['sha256'], item['path']
    for key, path in {'rootfs_manifest_sha256': IMAGE / 'rootfs-manifest.json',
                      'initramfs_sha256': IMAGE / 'initramfs.cpio',
                      'kernel_config_sha256': IMAGE / 'kernel-build/.config',
                      'guard_sha256': IMAGE / 'rootfs/usr/sbin/ram-guard'}.items():
        assert sha(path) == m[key], key
    sources = json.loads((HERE / 'patches/manifest.json').read_text())
    tree = json.loads((HERE / 'out/source-tree-verification.json').read_text())
    assert tree['passed'] and tree['source_manifest_sha256'] == sha(HERE / 'patches/manifest.json')
    for name, record in sources['files'].items():
        assert sha(SOURCE / name) == sha(WORK / name) == record['after_sha256'], name
    proof = json.loads((ROOT / 'development/perrier-ramenv/native-watchdog/watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['guard_sha256'] == m['guard_sha256']
    previous = ROOT / 'development/perrier-ramenv/native-leds'
    a, b = config(previous / 'kernel-build/.config'), config(IMAGE / 'kernel-build/.config')
    differences = {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}
    peripheral_options = {'CONFIG_EEPROM_AT24', 'CONFIG_SENSORS_INA3221',
                          'CONFIG_TWL4030_CORE', 'CONFIG_PWM_TWL', 'CONFIG_LEDS_PWM',
                          'CONFIG_NVMEM', 'CONFIG_NVMEM_SYSFS', 'CONFIG_NVMEM_LAYOUTS',
                          'CONFIG_MFD_CORE'}
    assert differences == {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE'} | peripheral_options, differences
    assert all(b[key] == 'y' for key in peripheral_options)
    for key in ('CONFIG_REGULATOR_TWL4030', 'CONFIG_REGULATOR_TWL6030', 'CONFIG_CLK_TWL',
                'CONFIG_TWL6030_GPADC', 'CONFIG_TWL4030_MADC', 'CONFIG_TWL4030_USB',
                'CONFIG_TWL6030_USB', 'CONFIG_RTC_DRV_TWL4030'):
        assert b.get(key) != 'y', key
    assert b['CONFIG_LOCALVERSION'] == '"-perrier-ram95"'
    assert b['CONFIG_INITRAMFS_SOURCE'] == '"' + str(IMAGE / 'initramfs.cpio') + '"'
    for key in ['CONFIG_OMAP_WATCHDOG', 'CONFIG_WATCHDOG_NOWAYOUT', 'CONFIG_TOUCHSCREEN_CYTTSP4']:
        assert b[key] == 'y', key
    before = json.loads((previous / 'rootfs-manifest.json').read_text())
    after = json.loads((IMAGE / 'rootfs-manifest.json').read_text())
    rootfs_changes = {'etc/init.d/rcS', 'qt/bin/perrier-touch-grid'}
    assert {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)} == rootfs_changes
    assert (IMAGE / 'rootfs/etc/init.d/rcS').read_bytes() == (previous / 'rootfs/etc/init.d/rcS').read_bytes().replace(b'ram94', b'ram95')
    qt = json.loads(Path(m['inputs']['qt_runtime_manifest']['path']).read_text())
    assert sha(IMAGE / 'rootfs/qt/bin/perrier-touch-grid') == qt['files']['bin/perrier-touch-grid']['sha256']
    for name, info in after.items():
        path = IMAGE / 'rootfs' / name
        if 'symlink' in info:
            assert path.is_symlink() and str(path.readlink()) == info['symlink'], name
        else:
            assert sha(path) == info['sha256'] and path.stat().st_size == info['bytes'], name
    for name in ['etc/shadow', 'etc/dropbear/ram_host_key', 'root/.ssh/authorized_keys']:
        assert stat.S_IMODE((IMAGE / 'rootfs' / name).stat().st_mode) == 0o600
    audit_archive(IMAGE / 'initramfs.cpio', after)
    packed = (IMAGE / 'kernel-build/usr/initramfs_inc_data').read_bytes()
    assert gzip.decompress(packed) == (IMAGE / 'initramfs.cpio').read_bytes()
    assert packed in (IMAGE / 'kernel-build/vmlinux').read_bytes()
    from audit_bus import audit_bus
    dt = audit_bus(BASELINE / 'board.dtb', IMAGE / 'board.dtb')
    from audit_peripherals import audit_peripherals
    peripherals = audit_peripherals(IMAGE / 'board.dtb')
    old_sources = json.loads((HERE / 'baselines/ram94/patches/manifest.json').read_text())
    changed_files = {name for name, item in sources['files'].items()
                     if item != old_sources['files'].get(name)}
    assert changed_files == {
        'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier.dtsi',
        'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier-ram.dts',
        'Documentation/devicetree/bindings/mfd/ti,twl.yaml'}
    for script in ['test_bus_audit.py', 'test_led_audit.py', 'test_peripheral_audit.py']:
        subprocess.run(['python3', HERE / 'tests' / script], check=True)
    symbols = (IMAGE / 'kernel-build/System.map').read_text().splitlines()
    image_end = next(int(line.split()[0], 16) for line in symbols if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    result = dict(m, passed=True, kernel_span_bytes=image_end - 0xc0000000,
                  dt_audit=dt, peripheral_audit=peripherals, unchanged_drivers_reuse_ram94_checks=True, rootfs_changes=sorted(rootfs_changes),
                  sources_apply_to_pristine_linux=True, embedded_initramfs_verified=True,
                  previous_physical_baseline=str(HERE / 'working-baseline.json'))
    (IMAGE / 'reviewed-image.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': True, 'kernel': m['kernel'], 'dt_audit': dt}, indent=2))


if __name__ == '__main__':
    main()
