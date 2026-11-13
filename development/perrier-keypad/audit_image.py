#!/usr/bin/env python3
"""Audit the ram52 keypad image against the tested ram51 baseline."""
import hashlib
import json
from pathlib import Path
import runpy
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RAM = ROOT / 'development/perrier-ramenv'
DEST = RAM / 'native-keypad'
BASE = RAM / 'native-backlight'
HERE = Path(__file__).resolve().parent
fdt_nodes = runpy.run_path(str(ROOT/'development/perrier-simpledrm/audit.py'))['fdt_nodes']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)

def audit():
    manifest = json.loads((DEST/'manifest.json').read_text())
    assert manifest['profile'] == 'native-keypad'
    assert manifest['kernel'] == '6.18.48-perrier-ram52'
    for info in manifest['artifacts'].values():
        path = Path(info['path'])
        assert sha(path) == info['sha256'] and path.stat().st_size == info['size'], path
    assert sha(DEST/'initramfs.cpio') == manifest['initramfs_sha256']
    assert sha(DEST/'rootfs-manifest.json') == manifest['rootfs_manifest_sha256']
    assert sha(DEST/'kernel-build/.config') == manifest['kernel_config_sha256']
    assert sha(HERE/'omap4-perrier-keypad.dts') == manifest['keypad_dts_sha256']
    assert sha(ROOT/'development/perrier-backlight/omap4-perrier-backlight.dts') == manifest['backlight_dts_sha256']
    assert sha(ROOT/'development/perrier-touch/omap4-perrier-touch.dts') == manifest['touch_dts_sha256']
    assert sha(ROOT/'development/perrier-native/omap4-perrier-ram.dts') == manifest['base_dts_sha256']
    assert manifest['guard_sha256'] == sha(DEST/'rootfs/usr/sbin/ram-guard')
    proof = json.loads((RAM/'watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['guard_sha256'] == manifest['guard_sha256']

    before = fdt_nodes((BASE/'board.dtb').read_bytes())
    after = fdt_nodes((DEST/'board.dtb').read_bytes())
    target_path = '/target-module@4a31c000'
    key_path = target_path+'/keypad@0'
    assert set(after)-set(before) == {target_path, key_path}, set(after)-set(before)
    assert set(before) <= set(after)
    handles = {struct.unpack('>I', props['phandle'])[0]:
               struct.unpack('>I', after[path]['phandle'])[0]
               for path, props in before.items() if 'phandle' in props}
    for path, props in before.items():
        assert set(props) == set(after[path]), (path, set(after[path])-set(props))
        for name, value in props.items():
            new = after[path][name]
            if value == new:
                continue
            assert len(value) == len(new) and len(value) % 4 == 0, (path, name)
            old_cells = struct.unpack('>'+str(len(value)//4)+'I', value)
            new_cells = struct.unpack('>'+str(len(new)//4)+'I', new)
            assert all(a == b or handles.get(a) == b for a,b in zip(old_cells,new_cells)), (path,name)
    target = after[target_path]
    key = after[key_path]
    assert target['compatible'] == b'ti,sysc-omap4\0ti,sysc\0'
    assert 'ti,no-reset-on-init' in target
    assert struct.unpack('>III', target['ranges']) == (0,0x4a31c000,0x1000)
    assert key['compatible'] == b'ti,omap4-keypad\0'
    assert key['reg'] == struct.pack('>II', 0,0x80)
    assert key['keypad,num-rows'] == struct.pack('>I',2)
    assert key['keypad,num-columns'] == struct.pack('>I',6)
    assert struct.unpack('>III',key['linux,keymap']) == (0x00040072,0x01040071,0x01050073)
    assert 'linux,input-no-autorepeat' not in key
    for path in (target_path,key_path):
        assert not any('gpio' in p or 'pinctrl' in p or 'supply' in p for p in after[path]), path

    cfg=config(DEST/'kernel-build/.config')
    base=config(BASE/'kernel-build/.config')
    changes={k:{'before':base.get(k,'n'),'after':cfg.get(k,'n')}
             for k in sorted(set(base)|set(cfg)) if base.get(k)!=cfg.get(k)}
    assert set(changes) <= {'CONFIG_LOCALVERSION','CONFIG_INITRAMFS_SOURCE',
                            'CONFIG_INPUT_KEYBOARD','CONFIG_KEYBOARD_OMAP4',
                            'CONFIG_INPUT_MATRIXKMAP'}, changes
    for k in ('CONFIG_INPUT_KEYBOARD','CONFIG_KEYBOARD_OMAP4','CONFIG_INPUT_MATRIXKMAP'):
        assert cfg[k] == 'y', k
    for k in ('CONFIG_WATCHDOG','CONFIG_SMP','CONFIG_CPU_FREQ','CONFIG_PINCTRL_SINGLE'):
        assert cfg.get(k) != 'y', k
    assert cfg['CONFIG_LOCALVERSION'] == '"-perrier-ram52"'
    startup = (DEST/'rootfs/etc/init.d/rcS').read_text()
    assert 'perrier-interactive-ram52' in startup
    assert 'native-cyttsp4' in startup
    subprocess.run(['sh','-n',DEST/'rootfs/etc/init.d/rcS'],check=True)
    image_end = next(int(line.split()[0],16) for line in
                     (DEST/'kernel-build/System.map').read_text().splitlines()
                     if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    report=dict(manifest,passed=True,kernel_span_bytes=image_end-0xc0000000,
                config_changes=changes,purpose='OMAP4 three-button matrix keypad RAM image')
    (DEST/'reviewed-image.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'kernel':report['kernel'],
                      'config_changes':changes},indent=2))

if __name__ == '__main__':
    audit()
