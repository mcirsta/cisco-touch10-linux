#!/usr/bin/env python3
"""Audit the Gen4 RAM candidate against the preserved cold-Ethernet image."""
import hashlib
import gzip
import importlib.util
import json
from pathlib import Path
import runpy
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = ROOT / 'development/perrier-ramenv/cold-ethernet'
DEST = ROOT / 'development/perrier-ramenv/gen4-touch'
SRC = HERE / 'linux-source'
fdt_nodes = runpy.run_path(str(ROOT / 'development/perrier-simpledrm/audit.py'))['fdt_nodes']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cells(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def audit_dt():
    old = fdt_nodes((BASE / 'board.dtb').read_bytes())
    new = fdt_nodes((DEST / 'board.dtb').read_bytes())
    ctl = '/pinctrl@4a100040'
    i2c = '/target-module@48072000/i2c@0'
    touch = i2c + '/touchscreen@67'
    gpio4, gpio5 = '/target-module@48059000/gpio@0', '/target-module@4805b000/gpio@0'
    pin_values = {'touch-5v-pin': [(0x112, 3)], 'touch-3v3-pin': [(0x114, 3)],
                  'touch-pins': [(0x140, 3), (0x142, 0x731b)],
                  'touch-i2c-pins': [(0x126, 0x100), (0x128, 0x100)],
                  'backlight-5v-pin': [(0x160, 3)], 'backlight-pwm-pin': [(0x1d2, 1)],
                  'backlight-enable-pin': [(0x154, 3)]}
    added = {ctl + '/' + name for name in pin_values} | {'/regulator-touch-5v', '/regulator-touch-3v3', '/regulator-backlight-5v'}
    assert set(new) - set(old) == added and not set(old) - set(new)
    handles = {struct.unpack('>I', p['phandle'])[0]: struct.unpack('>I', new[path]['phandle'])[0]
               for path, p in old.items() if 'phandle' in p}
    extra = {i2c: {'pinctrl-0', 'pinctrl-names'},
             '/backlight': {'pinctrl-0', 'pinctrl-names', 'power-supply', 'enable-gpios'},
             touch: {'pinctrl-0', 'pinctrl-names', 'reset-gpios', 'vdd-supply', 'vddio-supply'}}
    for path, props in old.items():
        after = new[path]
        assert not set(props) - set(after), path
        assert set(after) - set(props) - {'phandle'} == extra.get(path, set()), path
        for key, a in props.items():
            b = after[key]
            if a == b:
                continue
            assert len(a) == len(b) and len(a) % 4 == 0, (path, key)
            values_a = struct.unpack('>' + 'I' * (len(a) // 4), a)
            values_b = struct.unpack('>' + 'I' * (len(b) // 4), b)
            assert all(x == y or handles.get(x) == y for x, y in zip(values_a, values_b)), (path, key)
    for name, pairs in pin_values.items():
        props = new[ctl + '/' + name]
        assert set(props) <= {'phandle', 'pinctrl-single,pins'}
        assert props['pinctrl-single,pins'] == cells(*[v for offset, mode in pairs for v in (offset - 0x40, mode)])
    for suffix, voltage, line in [('5v', 5000000, 24), ('3v3', 3300000, 25)]:
        p = new['/regulator-touch-' + suffix]
        assert set(p) == {'compatible', 'regulator-name', 'regulator-min-microvolt',
                          'regulator-max-microvolt', 'pinctrl-names', 'pinctrl-0',
                          'gpio', 'enable-active-high', 'phandle'}
        assert p['compatible'] == b'regulator-fixed\0'
        assert p['regulator-name'] == ('perrier-touch-' + suffix).encode() + b'\0'
        assert p['regulator-min-microvolt'] == p['regulator-max-microvolt'] == cells(voltage)
        assert p['gpio'] == new[gpio4]['phandle'] + cells(line, 0)
        assert p['pinctrl-0'] == new[ctl + '/touch-' + suffix + '-pin']['phandle']
        assert p['pinctrl-names'] == b'default\0'
    assert new[i2c]['pinctrl-0'] == new[ctl + '/touch-i2c-pins']['phandle']
    assert new[touch]['pinctrl-0'] == new[ctl + '/touch-pins']['phandle']
    assert new[touch]['pinctrl-names'] == new[i2c]['pinctrl-names'] == b'default\0'
    assert new[touch]['reset-gpios'] == new[gpio5]['phandle'] + cells(13, 1)
    assert new[touch]['vdd-supply'] == new['/regulator-touch-5v']['phandle']
    assert new[touch]['vddio-supply'] == new['/regulator-touch-3v3']['phandle']
    assert new[touch]['interrupts'] == cells(14, 2)
    assert not any('inverted' in key or 'swapped' in key for key in new[touch])
    bl = new['/regulator-backlight-5v']
    assert set(bl) == {'compatible', 'regulator-name', 'regulator-min-microvolt',
                      'regulator-max-microvolt', 'pinctrl-names', 'pinctrl-0', 'gpio',
                      'enable-active-high', 'startup-delay-us', 'regulator-boot-on',
                      'regulator-always-on', 'phandle'}
    assert bl['compatible'] == b'regulator-fixed\0'
    assert bl['regulator-name'] == b'perrier-backlight-5v\0'
    assert bl['regulator-min-microvolt'] == bl['regulator-max-microvolt'] == cells(5000000)
    assert bl['gpio'] == new[gpio5]['phandle'] + cells(29, 0)
    assert bl['startup-delay-us'] == cells(11000)
    assert bl['pinctrl-0'] == new[ctl + '/backlight-5v-pin']['phandle']
    assert new['/backlight']['power-supply'] == bl['phandle']
    assert new['/backlight']['pinctrl-0'] == new[ctl + '/backlight-pwm-pin']['phandle'] + new[ctl + '/backlight-enable-pin']['phandle']
    assert new['/backlight']['enable-gpios'] == new[gpio5]['phandle'] + cells(23, 0)
    assert new['/backlight']['pinctrl-names'] == bl['pinctrl-names'] == b'default\0'
    return {'gpio_outputs': [120, 121, 141, 151, 157], 'irq_gpio': 142,
            'pad_values': pin_values, 'other_hardware_unchanged': True,
            'touch_axis_transforms': 'none; same 1280x800 ranges as the aligned handoff driver'}


def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def main():
    m = json.loads((DEST / 'manifest.json').read_text())
    assert m['profile'] == 'gen4-touch' and m['kernel'] == '6.18.48-perrier-ram64'
    for info in m['artifacts'].values():
        p = Path(info['path'])
        assert sha(p) == info['sha256'] and p.stat().st_size == info['size'], p
    for info in m['inputs'].values():
        assert sha(Path(info['path'])) == info['sha256'], info['path']
    for key, p in {'rootfs_manifest_sha256': DEST / 'rootfs-manifest.json',
                   'initramfs_sha256': DEST / 'initramfs.cpio',
                   'kernel_config_sha256': DEST / 'kernel-build/.config',
                   'guard_sha256': DEST / 'rootfs/usr/sbin/ram-guard'}.items():
        assert sha(p) == m[key], key
    proof = json.loads((ROOT / 'development/perrier-ramenv/native-watchdog/watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['guard_sha256'] == m['guard_sha256']
    a, b = config(BASE / 'kernel-build/.config'), config(DEST / 'kernel-build/.config')
    assert {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)} == {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE'}
    assert b['CONFIG_LOCALVERSION'] == '"-perrier-ram64"'
    assert b['CONFIG_INITRAMFS_SOURCE'] == '"' + str(DEST / 'initramfs.cpio') + '"'
    assert all(b[k] == 'y' for k in ('CONFIG_TOUCHSCREEN_CYTTSP4', 'CONFIG_GPIOLIB',
                                   'CONFIG_OF', 'CONFIG_REGULATOR', 'CONFIG_OMAP_WATCHDOG'))
    for name in ('cyttsp4_core.c', 'cyttsp4_core.h', 'cyttsp4_i2c.c'):
        assert sha(HERE / name) == sha(SRC / 'drivers/input/touchscreen' / name)
    compiled = (DEST / 'kernel-build/System.map').read_text()
    assert ' cyttsp4_startup' in compiled and ' cyttsp4_i2c_probe' in compiled and ' cy4_probe' not in compiled
    image_end = next(int(line.split()[0], 16) for line in compiled.splitlines() if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    before = json.loads((BASE / 'rootfs-manifest.json').read_text())
    after = json.loads((DEST / 'rootfs-manifest.json').read_text())
    assert {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)} == {'etc/init.d/rcS'}
    assert (DEST / 'rootfs/etc/init.d/rcS').read_bytes() == (BASE / 'rootfs/etc/init.d/rcS').read_bytes().replace(b'ram60', b'ram64')
    for name, info in after.items():
        p = DEST / 'rootfs' / name
        if 'symlink' in info:
            assert p.is_symlink() and str(p.readlink()) == info['symlink'], name
        else:
            assert sha(p) == info['sha256'] and p.stat().st_size == info['bytes'], name
    spec = importlib.util.spec_from_file_location('watchdog_audit', ROOT / 'development/perrier-watchdog/audit_image.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    checker.DEST = DEST
    checker.audit_archive(after)
    assert gzip.decompress((DEST / 'kernel-build/usr/initramfs_inc_data').read_bytes()) == (DEST / 'initramfs.cpio').read_bytes(), 'Embedded initramfs differs from the audited archive'
    dt = audit_dt()
    subprocess.run(['python3', HERE / 'test_core.py'], check=True)
    subprocess.run(['python3', HERE / 'test_i2c.py'], check=True)
    report = dict(m, passed=True, kernel_span_bytes=image_end - 0xc0000000,
                  dt_audit=dt, rootfs_changes=['etc/init.d/rcS'],
                  replay_test_log_sha256=sha(HERE / 'test-core.log'),
                  i2c_test_log_sha256=sha(HERE / 'test-i2c.log'),
                  cold_touch_hardware_verified=False)
    (DEST / 'reviewed-image.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'kernel': m['kernel'], 'dt': dt}, indent=2))


if __name__ == '__main__':
    main()
