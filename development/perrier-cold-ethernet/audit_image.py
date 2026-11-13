#!/usr/bin/env python3
"""Audit only the stock-evidenced cold Ethernet changes in ram60."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'development/perrier-ramenv/native-watchdog'
DEST = ROOT / 'development/perrier-ramenv/cold-ethernet'
fdt_nodes = runpy.run_path(str(ROOT / 'development/perrier-simpledrm/audit.py'))['fdt_nodes']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def cells(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def audit_dt():
    old = fdt_nodes((BASE / 'board.dtb').read_bytes())
    new = fdt_nodes((DEST / 'board.dtb').read_bytes())
    controller = '/pinctrl@4a100040'
    phy_pins, lan_pin = controller + '/ethernet-phy-pins', controller + '/lan-reset-pins'
    gpio5 = '/target-module@4805b000/gpio@0'
    phy = '/usb-phy'
    hog = gpio5 + '/lan-reset-hog'
    ehci = '/target-module@4a064000/usbhshost@0/usb@c00'
    assert set(new) - set(old) == {controller, phy_pins, lan_pin, phy, hog}
    assert not set(old) - set(new)
    handles = {struct.unpack('>I', props['phandle'])[0]: struct.unpack('>I', new[path]['phandle'])[0]
               for path, props in old.items() if 'phandle' in props and 'phandle' in new[path]}
    additions = {gpio5: {'pinctrl-names', 'pinctrl-0'}, ehci: {'phys'}}
    for path, before in old.items():
        after = new[path]
        assert not set(before) - set(after), path
        assert set(after) - set(before) - {'phandle'} == additions.get(path, set()), path
        for key, a in before.items():
            b = after[key]
            if a == b:
                continue
            assert len(a) == len(b) and len(a) % 4 == 0, (path, key)
            previous = struct.unpack('>' + 'I' * (len(a) // 4), a)
            current = struct.unpack('>' + 'I' * (len(b) // 4), b)
            assert all(x == y or handles.get(x) == y for x, y in zip(previous, current)), (path, key)
    assert new[controller]['compatible'] == b'pinctrl-single\0'
    assert new[controller]['reg'] == cells(0x4a100040, 0x196)
    assert new[controller]['pinctrl-single,register-width'] == cells(16)
    assert new[controller]['pinctrl-single,function-mask'] == cells(0x7fff)
    assert 'pinctrl-0' not in new[controller]
    pad_values = [(0xc2, 0x10c), (0xc4, 4)] + [(offset, 0x10c) for offset in range(0xc6, 0xda, 2)]
    pad_values += [(0xf6, 3), (0x19a, 0x118)]
    assert new[phy_pins]['pinctrl-single,pins'] == cells(*[value for offset, mode in pad_values
                                                                      for value in (offset - 0x40, mode)])
    assert new[lan_pin]['pinctrl-single,pins'] == cells(0x162 - 0x40, 3)
    assert new[gpio5]['pinctrl-0'] == new[lan_pin]['phandle']
    assert new[gpio5]['pinctrl-names'] == b'default\0'
    assert set(new[hog]) == {'gpio-hog', 'gpios', 'output-high', 'line-name'}
    assert new[hog]['gpios'] == cells(30, 0)
    assert new[hog]['line-name'] == b'lan-reset-released\0'
    assert new[phy]['compatible'] == b'usb-nop-xceiv\0'
    assert new[phy]['#phy-cells'] == cells(0)
    assert new[phy]['reset-gpios'] == new['/target-module@48059000/gpio@0']['phandle'] + cells(14, 1)
    assert new[phy]['pinctrl-0'] == new[phy_pins]['phandle']
    assert new[phy]['pinctrl-names'] == b'default\0'
    assert new[phy]['clock-names'] == b'main_clk\0'
    assert new[phy]['clock-frequency'] == cells(19200000)
    def clock(name):
        return next(props['phandle'] for props in new.values()
                    if props.get('clock-output-names') == name.encode() + b'\0')
    assert new[phy]['clocks'] == clock('auxclk1_ck')
    assert new[phy]['assigned-clocks'] == clock('auxclk1_src_ck')
    assert new[phy]['assigned-clock-parents'] == clock('sys_clkin_ck')
    assert new[ehci]['phys'] == new[phy]['phandle']
    assert new['/ocp']['status'] == b'disabled\0'
    # No new regulator or supply property; no touch/LCD/PMIC output is changed.
    for path in (controller, phy_pins, lan_pin, phy, hog):
        assert not any('supply' in key or 'regulator' in key for key in new[path]), path
    return {'physical_gpio_outputs': [110, 158], 'clock_hz': 19200000,
            'physical_pad_values': pad_values + [(0x162, 3)],
            'shared_pll_retuned': False, 'other_hardware_properties_unchanged': True}


def main():
    manifest = json.loads((DEST / 'manifest.json').read_text())
    assert manifest['kernel'] == '6.18.48-perrier-ram60' and manifest['profile'] == 'cold-ethernet'
    for info in manifest['artifacts'].values():
        path = Path(info['path'])
        assert sha(path) == info['sha256'] and path.stat().st_size == info['size'], path
    for info in manifest['inputs'].values():
        assert sha(Path(info['path'])) == info['sha256'], info['path']
    for key, path in {'rootfs_manifest_sha256': DEST / 'rootfs-manifest.json',
                      'initramfs_sha256': DEST / 'initramfs.cpio',
                      'kernel_config_sha256': DEST / 'kernel-build/.config',
                      'guard_sha256': DEST / 'rootfs/usr/sbin/ram-guard'}.items():
        assert sha(path) == manifest[key], key
    proof = json.loads((BASE / 'watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['guard_sha256'] == manifest['guard_sha256']
    before_cfg, after_cfg = config(BASE / 'kernel-build/.config'), config(DEST / 'kernel-build/.config')
    changes = {key: [before_cfg.get(key), after_cfg.get(key)] for key in before_cfg.keys() | after_cfg.keys()
               if before_cfg.get(key) != after_cfg.get(key)}
    options = {'CONFIG_PINCTRL_SINGLE', 'CONFIG_GENERIC_PINCTRL_GROUPS', 'CONFIG_PINMUX',
               'CONFIG_GENERIC_PINMUX_FUNCTIONS', 'CONFIG_PINCONF', 'CONFIG_GENERIC_PINCONF'}
    assert set(changes) == options | {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE'}, changes
    for key in options:
        assert after_cfg[key] == 'y', key
    assert after_cfg['CONFIG_LOCALVERSION'] == '"-perrier-ram60"'
    assert after_cfg['CONFIG_INITRAMFS_SOURCE'] == '"' + str(DEST / 'initramfs.cpio') + '"'
    dt = audit_dt()
    before_fs = json.loads((BASE / 'rootfs-manifest.json').read_text())
    after_fs = json.loads((DEST / 'rootfs-manifest.json').read_text())
    assert {name for name in before_fs.keys() | after_fs.keys()
            if before_fs.get(name) != after_fs.get(name)} == {'etc/init.d/rcS'}
    for name, info in after_fs.items():
        path = DEST / 'rootfs' / name
        if 'symlink' in info:
            assert path.is_symlink() and str(path.readlink()) == info['symlink'], name
        else:
            assert sha(path) == info['sha256'] and path.stat().st_size == info['bytes'], name
    subprocess.run(['sh', '-n', DEST / 'rootfs/etc/init.d/rcS'], check=True)
    # Reuse the archive validator with its image directory explicitly selected.
    spec = importlib.util.spec_from_file_location('watchdog_audit', ROOT / 'development/perrier-watchdog/audit_image.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    checker.DEST = DEST
    checker.audit_archive(after_fs)
    image_end = next(int(line.split()[0], 16) for line in
                     (DEST / 'kernel-build/System.map').read_text().splitlines() if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    report = dict(manifest, passed=True, kernel_span_bytes=image_end - 0xc0000000,
                  config_changes=changes, dt_audit=dt, rootfs_changes=['etc/init.d/rcS'],
                  cold_ethernet_hardware_verified=False)
    (DEST / 'reviewed-image.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'kernel': report['kernel'],
                      'kernel_span_bytes': report['kernel_span_bytes'], 'dt_audit': dt}, indent=2))


if __name__ == '__main__':
    main()
