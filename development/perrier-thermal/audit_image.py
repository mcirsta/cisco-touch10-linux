#!/usr/bin/env python3
"""Audit the ram58 thermal image against the tested single-core ram57."""
import hashlib
import json
from pathlib import Path
import runpy
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RAM = ROOT / 'development/perrier-ramenv'
BASE = RAM / 'native-keypad-newqt'
DEST = RAM / 'native-thermal'
HERE = Path(__file__).resolve().parent
fdt_nodes = runpy.run_path(str(ROOT / 'development/perrier-simpledrm/audit.py'))['fdt_nodes']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def phandle(props):
    return struct.unpack('>I', props['phandle'])[0]


def audit_fdt(before, after):
    bandgap = '/bandgap@4a002260'
    gpio_target = '/target-module@48057000'
    gpio = gpio_target + '/gpio@0'
    tmp102 = '/target-module@48060000/i2c@0/temperature-sensor@48'
    assert set(after) - set(before) == {bandgap, gpio_target, gpio, tmp102}
    assert set(before) - set(after) == {
        '/thermal-zones/cpu_thermal/cooling-maps',
        '/thermal-zones/cpu_thermal/cooling-maps/map0'}
    handles = {phandle(props): phandle(after[path])
               for path, props in before.items()
               if 'phandle' in props and 'phandle' in after[path]}
    for path in sorted(set(before) & set(after)):
        old, new = before[path], after[path]
        removed = set(old) - set(new)
        added = set(new) - set(old)
        assert not added, (path, added)
        unreferenced = {'/ocp/bandgap@4a002260', '/cpus/cpu@0',
                        '/thermal-zones/cpu_thermal/trips/cpu_alert'}
        assert removed == ({'phandle'} if path in unreferenced else set()), (path, removed)
        for key in set(old) & set(new):
            a, b = old[key], new[key]
            if path == '/thermal-zones' and key == 'status':
                assert (a, b) == (b'disabled\0', b'okay\0')
            elif path == '/thermal-zones/cpu_thermal' and key == 'thermal-sensors':
                assert b == after[bandgap]['phandle']
            elif a != b:
                assert len(a) == len(b) and len(a) % 4 == 0, (path, key)
                old_cells = struct.unpack('>' + 'I' * (len(a) // 4), a)
                new_cells = struct.unpack('>' + 'I' * (len(b) // 4), b)
                assert all(x == y or handles.get(x) == y
                           for x, y in zip(old_cells, new_cells)), (path, key)

    assert after[tmp102]['compatible'] == b'ti,tmp102\0'
    assert after[tmp102]['reg'] == struct.pack('>I', 0x48)
    assert after[tmp102]['label'] == b'Board\0'
    assert set(after[tmp102]) == {'compatible', 'reg', 'label'}
    assert 'ti,no-reset-on-init' in after[gpio_target]
    assert after[gpio_target]['ranges'] == struct.pack('>III', 0, 0x48057000, 0x1000)
    assert after[gpio]['compatible'] == b'ti,omap4-gpio\0'
    assert after[gpio]['reg'] == struct.pack('>II', 0, 0x200)
    assert after[bandgap]['compatible'] == b'ti,omap4460-bandgap\0'
    assert after[bandgap]['reg'] == struct.pack('>IIIIII',
                                              0x4a002260, 4, 0x4a00232c, 4,
                                              0x4a002378, 0x18)
    assert after[bandgap]['gpios'] == struct.pack('>III', phandle(after[gpio]), 22, 0)
    assert after['/thermal-zones/cpu_thermal']['thermal-sensors'] == after[bandgap]['phandle']
    for path in (bandgap, gpio_target, gpio, tmp102):
        assert not any('pinctrl' in key or 'supply' in key or 'hog' in key
                       for key in after[path]), path
    assert after['/ocp']['status'] == b'disabled\0'
    assert after['/ocp/bandgap@4a002260']['status'] == b'disabled\0'


def main():
    manifest = json.loads((DEST / 'manifest.json').read_text())
    assert manifest['profile'] == 'native-thermal'
    assert manifest['kernel'] == '6.18.48-perrier-ram58'
    for info in manifest['artifacts'].values():
        path = Path(info['path'])
        assert sha(path) == info['sha256'] and path.stat().st_size == info['size'], path
    for key, path in {
        'initramfs_sha256': DEST / 'initramfs.cpio',
        'rootfs_manifest_sha256': DEST / 'rootfs-manifest.json',
        'kernel_config_sha256': DEST / 'kernel-build/.config',
        'guard_sha256': DEST / 'rootfs/usr/sbin/ram-guard',
        'thermal_dts_sha256': HERE / 'omap4-perrier-thermal.dts',
        'keypad_dts_sha256': ROOT / 'development/perrier-keypad/omap4-perrier-keypad.dts',
        'backlight_dts_sha256': ROOT / 'development/perrier-backlight/omap4-perrier-backlight.dts',
        'touch_dts_sha256': ROOT / 'development/perrier-touch/omap4-perrier-touch.dts',
        'base_dts_sha256': ROOT / 'development/perrier-native/omap4-perrier-ram.dts',
    }.items():
        assert sha(path) == manifest[key], key
    proof = json.loads((RAM / 'watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['guard_sha256'] == manifest['guard_sha256']
    audit_fdt(fdt_nodes((BASE / 'board.dtb').read_bytes()),
              fdt_nodes((DEST / 'board.dtb').read_bytes()))
    old = config(BASE / 'kernel-build/.config')
    new = config(DEST / 'kernel-build/.config')
    changes = {key: (old.get(key), new.get(key)) for key in old.keys() | new.keys()
               if old.get(key) != new.get(key)}
    allowed = {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE', 'CONFIG_HWMON',
               'CONFIG_SENSORS_TMP102', 'CONFIG_THERMAL', 'CONFIG_THERMAL_OF',
               'CONFIG_THERMAL_DEFAULT_GOV_STEP_WISE', 'CONFIG_THERMAL_GOV_STEP_WISE',
               'CONFIG_THERMAL_EMERGENCY_POWEROFF_DELAY_MS', 'CONFIG_TI_SOC_THERMAL',
               'CONFIG_TI_THERMAL', 'CONFIG_OMAP4_THERMAL'}
    assert set(changes) == allowed, changes
    for key in ('CONFIG_HWMON', 'CONFIG_SENSORS_TMP102', 'CONFIG_THERMAL',
                'CONFIG_THERMAL_OF', 'CONFIG_TI_SOC_THERMAL', 'CONFIG_TI_THERMAL',
                'CONFIG_OMAP4_THERMAL'):
        assert new[key] == 'y', key
    for key in ('CONFIG_SMP', 'CONFIG_CPU_FREQ', 'CONFIG_WATCHDOG',
                'CONFIG_PINCTRL_SINGLE', 'CONFIG_MODULES'):
        assert new.get(key) != 'y', key
    assert new['CONFIG_LOCALVERSION'] == '"-perrier-ram58"'
    assert new['CONFIG_INITRAMFS_SOURCE'] == '"' + str(DEST / 'initramfs.cpio') + '"'
    before_fs = json.loads((BASE / 'rootfs-manifest.json').read_text())
    after_fs = json.loads((DEST / 'rootfs-manifest.json').read_text())
    changed_fs = {key for key in before_fs.keys() | after_fs.keys()
                  if before_fs.get(key) != after_fs.get(key)}
    assert changed_fs == {'etc/init.d/rcS', 'qt/bin/perrier-touch-grid'}, changed_fs
    assert 'perrier-interactive-ram58' in (DEST / 'rootfs/etc/init.d/rcS').read_text()
    subprocess.run(['sh', '-n', DEST / 'rootfs/etc/init.d/rcS'], check=True)
    subprocess.run(['sh', '-n', DEST / 'rootfs/usr/bin/qt-run'], check=True)
    image_end = next(int(line.split()[0], 16) for line in
                     (DEST / 'kernel-build/System.map').read_text().splitlines()
                     if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    report = dict(manifest, passed=True, kernel_span_bytes=image_end - 0xc0000000,
                  config_changes=changes, rootfs_changes=sorted(changed_fs),
                  purpose='TMP102 and OMAP4460 CPU thermal sensors in watchdog-recovered RAM image')
    (DEST / 'reviewed-image.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'kernel': report['kernel'],
                      'kernel_span_bytes': report['kernel_span_bytes'],
                      'config_changes': sorted(changes)}, indent=2))


if __name__ == '__main__':
    main()
