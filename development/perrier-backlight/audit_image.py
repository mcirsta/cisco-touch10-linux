#!/usr/bin/env python3
"""Audit the timer10 PWM RAM trial against the validated ram50 image."""
import hashlib
import json
from pathlib import Path
import runpy
import stat
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAM = ROOT / 'development/perrier-ramenv'
DEST = RAM / 'native-backlight'
TOUCH = ROOT / 'development/perrier-touch'
NATIVE = ROOT / 'development/perrier-native'
SRC = ROOT / 'development/sources/linux-6.18.48'
fdt_nodes = runpy.run_path(str(ROOT/'development/perrier-simpledrm/audit.py'))['fdt_nodes']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)

def audit_fdt(old, new):
    added = {'/target-module@48086000', '/target-module@48086000/timer@0',
             '/pwm-backlight-timer', '/backlight'}
    assert set(new) - set(old) == added, set(new) - set(old)
    assert set(old) <= set(new)
    handles = {struct.unpack('>I', props['phandle'])[0]:
               struct.unpack('>I', new[path]['phandle'])[0]
               for path, props in old.items() if 'phandle' in props}
    for path, props in old.items():
        extra = set(new[path]) - set(props)
        assert extra == ({'backlight'} if path == '/panel' else set()), (path, extra)
        assert set(props) <= set(new[path]), path
        for key, previous in props.items():
            current = new[path][key]
            if previous == current:
                continue
            assert len(previous) == len(current) and len(previous) % 4 == 0, (path, key)
            before = struct.unpack('>' + str(len(previous)//4) + 'I', previous)
            after = struct.unpack('>' + str(len(current)//4) + 'I', current)
            assert all(a == b or handles.get(a) == b for a, b in zip(before, after)), (path, key)
    timer = new['/target-module@48086000/timer@0']
    assert timer['compatible'] == b'ti,omap3430-timer\0'
    assert timer['reg'] == struct.pack('>II', 0, 0x80)
    assert 'ti,timer-pwm' in timer
    target = new['/target-module@48086000']
    assert 'ti,no-reset-on-init' in target
    assert struct.unpack('>III', target['ranges']) == (0, 0x48086000, 0x1000)
    pwm = new['/pwm-backlight-timer']
    assert pwm['compatible'] == b'ti,omap-dmtimer-pwm\0'
    assert pwm['ti,timers'] == timer['phandle']
    backlight = new['/backlight']
    assert backlight['compatible'] == b'pwm-backlight\0'
    assert struct.unpack('>IIII', backlight['pwms']) == (
        struct.unpack('>I', pwm['phandle'])[0], 0, 50000, 0)
    assert struct.unpack('>IIIII', backlight['brightness-levels']) == (0, 64, 128, 192, 255)
    assert backlight['default-brightness-level'] == struct.pack('>I', 4)
    assert new['/panel']['backlight'] == backlight['phandle']
    for path in added:
        assert not any('gpio' in key or 'pinctrl' in key or 'supply' in key
                       for key in new[path]), path

def audit():
    manifest = json.loads((DEST/'manifest.json').read_text())
    assert manifest['profile'] == 'native-backlight'
    assert manifest['kernel'] == '6.18.48-perrier-ram51'
    for info in manifest['artifacts'].values():
        path = Path(info['path'])
        assert sha(path) == info['sha256'] and path.stat().st_size == info['size'], path
    assert sha(DEST/'initramfs.cpio') == manifest['initramfs_sha256']
    assert sha(DEST/'rootfs-manifest.json') == manifest['rootfs_manifest_sha256']
    assert sha(DEST/'kernel-build/.config') == manifest['kernel_config_sha256']
    assert sha(HERE/'omap4-perrier-backlight.dts') == manifest['backlight_dts_sha256']
    assert sha(TOUCH/'omap4-perrier-touch.dts') == manifest['touch_dts_sha256']
    assert sha(NATIVE/'omap4-perrier-ram.dts') == manifest['base_dts_sha256']
    for directory, key in ((NATIVE/'kernel-patches', 'patch_manifest_sha256'),
                           (TOUCH/'kernel-patches', 'touch_patch_manifest_sha256')):
        assert sha(directory/'manifest.json') == manifest[key]
        for entry in json.loads((directory/'manifest.json').read_text())['patches']:
            assert sha(directory/entry['patch']) == entry['patch_sha256']
            assert sha(SRC/entry['path']) == entry['patched_sha256']
    cfg = config(DEST/'kernel-build/.config')
    baseline = config(RAM/'native-touch/kernel-build/.config')
    changes = {key:{'before':baseline.get(key, 'n'), 'after':cfg.get(key, 'n')}
               for key in sorted(set(baseline)|set(cfg)) if baseline.get(key) != cfg.get(key)}
    assert set(changes) <= {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE',
                            'CONFIG_PWM', 'CONFIG_PWM_OMAP_DMTIMER', 'CONFIG_BACKLIGHT_PWM'}, changes
    for key in ('CONFIG_PWM', 'CONFIG_PWM_OMAP_DMTIMER', 'CONFIG_BACKLIGHT_PWM',
                'CONFIG_TOUCHSCREEN_CYTTSP4'):
        assert cfg[key] == 'y', key
    for key in ('CONFIG_WATCHDOG', 'CONFIG_SMP', 'CONFIG_CPU_IDLE', 'CONFIG_CPU_FREQ',
                'CONFIG_SUSPEND', 'CONFIG_PINCTRL_SINGLE', 'CONFIG_MODULES'):
        assert cfg.get(key) != 'y', key
    assert cfg['CONFIG_LOCALVERSION'] == '"-perrier-ram51"'
    assert cfg['CONFIG_INITRAMFS_SOURCE'] == '"'+str(DEST/'initramfs.cpio')+'"'
    image_end = next(int(line.split()[0], 16) for line in
                     (DEST/'kernel-build/System.map').read_text().splitlines()
                     if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    old = fdt_nodes((RAM/'native-touch/board.dtb').read_bytes())
    new = fdt_nodes((DEST/'board.dtb').read_bytes())
    audit_fdt(old, new)
    entries = json.loads((DEST/'rootfs-manifest.json').read_text())
    rootfs = DEST/'rootfs'
    assert 'usr/bin/touch-uinput' not in entries
    startup = (rootfs/'etc/init.d/rcS').read_text()
    assert 'perrier-interactive-ram51' in startup
    assert 'native-cyttsp4' in startup
    assert 'touch-uinput' not in startup
    for name, info in entries.items():
        path = rootfs/name
        if 'symlink' in info:
            assert path.is_symlink() and str(path.readlink()) == info['symlink'], name
        else:
            assert sha(path) == info['sha256'] and path.stat().st_size == info['bytes'], name
    for name in ('etc/shadow', 'etc/dropbear/ram_host_key', 'root/.ssh/authorized_keys'):
        assert stat.S_IMODE((rootfs/name).stat().st_mode) == 0o600
    assert manifest['guard_sha256'] == sha(rootfs/'usr/sbin/ram-guard')
    proof = json.loads((RAM/'watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['guard_sha256'] == manifest['guard_sha256']
    subprocess.run(['sh', '-n', rootfs/'etc/init.d/rcS'], check=True)
    subprocess.run(['sh', '-n', rootfs/'usr/bin/qt-run'], check=True)
    report = dict(manifest, passed=True, kernel_span_bytes=image_end-0xc0000000,
                  config_changes=changes,
                  purpose='Timer10 mainline PWM/backlight RAM image with inherited GPIO157 and watchdog')
    (DEST/'reviewed-image.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'passed':True, 'kernel':report['kernel'],
                      'kernel_span_bytes':report['kernel_span_bytes'],
                      'config_changes':changes}, indent=2))

if __name__ == '__main__':
    audit()
