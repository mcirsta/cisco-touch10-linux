#!/usr/bin/env python3
"""Audit the separate native-touch RAM image and its recovery path."""
import hashlib
import json
from pathlib import Path
import runpy
import stat
import struct
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
RAM=ROOT/'development/perrier-ramenv'
DEST=RAM/'native-touch'
NATIVE=ROOT/'development/perrier-native'
SRC=ROOT/'development/sources/linux-6.18.48'
fdt_nodes=runpy.run_path(str(ROOT/'development/perrier-simpledrm/audit.py'))['fdt_nodes']

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def config(p):
    return dict(line.split('=',1) for line in p.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)

def fdt_diff(base, new):
    assert set(new)-set(base)=={
        '/target-module@4805b000',
        '/target-module@4805b000/gpio@0',
        '/target-module@48072000/i2c@0/touchscreen@67'}
    assert set(base) <= set(new)
    handles={struct.unpack('>I',props['phandle'])[0]:
             struct.unpack('>I',new[path]['phandle'])[0]
             for path,props in base.items() if 'phandle' in props}
    for path,props in base.items():
        assert set(props)==set(new[path]), path
        for key,old in props.items():
            fresh=new[path][key]
            if old==fresh:
                continue
            assert len(old)==len(fresh) and len(old)%4==0,(path,key)
            before=struct.unpack('>'+str(len(old)//4)+'I',old)
            after=struct.unpack('>'+str(len(old)//4)+'I',fresh)
            for a,b in zip(before,after):
                assert a==b or handles.get(a)==b,(path,key,a,b)

def audit():
    manifest=json.loads((DEST/'manifest.json').read_text())
    assert manifest['profile']=='native-touch' and manifest['kernel']=='6.18.48-perrier-ram50'
    for info in manifest['artifacts'].values():
        p=Path(info['path'])
        assert sha(p)==info['sha256'] and p.stat().st_size==info['size'],p
    assert sha(DEST/'initramfs.cpio')==manifest['initramfs_sha256']
    assert sha(DEST/'rootfs-manifest.json')==manifest['rootfs_manifest_sha256']
    assert sha(DEST/'kernel-build/.config')==manifest['kernel_config_sha256']
    assert sha(NATIVE/'kernel-patches/manifest.json')==manifest['patch_manifest_sha256']
    assert sha(HERE/'kernel-patches/manifest.json')==manifest['touch_patch_manifest_sha256']
    assert sha(HERE/'omap4-perrier-touch.dts')==manifest['touch_dts_sha256']
    assert sha(NATIVE/'omap4-perrier-ram.dts')==manifest['base_dts_sha256']
    for directory in (NATIVE/'kernel-patches',HERE/'kernel-patches'):
        patches=json.loads((directory/'manifest.json').read_text())['patches']
        for entry in patches:
            assert sha(directory/entry['patch'])==entry['patch_sha256']
            assert sha(SRC/entry['path'])==entry['patched_sha256']
    cfg=config(DEST/'kernel-build/.config')
    base=config(RAM/'baselines/ram44-clockfix-clean-qt/kernel.config')
    permitted={'CONFIG_LOCALVERSION','CONFIG_INITRAMFS_SOURCE',
               'CONFIG_INPUT_UINPUT','CONFIG_INPUT_TOUCHSCREEN',
               'CONFIG_TOUCHSCREEN_CYTTSP4'}
    changes={key:{'before':base.get(key,'n'),'after':cfg.get(key,'n')}
             for key in sorted(set(base)|set(cfg)) if base.get(key)!=cfg.get(key)}
    assert set(changes)<=permitted,changes
    assert cfg['CONFIG_INPUT_TOUCHSCREEN']=='y'
    assert cfg['CONFIG_TOUCHSCREEN_CYTTSP4']=='y'
    assert cfg.get('CONFIG_INPUT_UINPUT')!='y'
    assert cfg['CONFIG_LOCALVERSION']=='"-perrier-ram50"'
    assert cfg['CONFIG_INITRAMFS_SOURCE']=='"'+str(DEST/'initramfs.cpio')+'"'
    for key in ('CONFIG_WATCHDOG','CONFIG_SMP','CONFIG_CPU_IDLE','CONFIG_CPU_FREQ',
                'CONFIG_SUSPEND','CONFIG_PINCTRL_SINGLE','CONFIG_MODULES'):
        assert cfg.get(key)!='y',key
    image_end=next(int(line.split()[0],16) for line in
                   (DEST/'kernel-build/System.map').read_text().splitlines()
                   if line.endswith(' _end'))
    assert image_end-0xc0000000<0x02000000
    baseline=fdt_nodes((RAM/'baselines/ram44-clockfix-clean-qt/board.dtb').read_bytes())
    nodes=fdt_nodes((DEST/'board.dtb').read_bytes())
    fdt_diff(baseline,nodes)
    gpio5=nodes['/target-module@4805b000']
    assert 'ti,no-reset-on-init' in gpio5
    assert gpio5['compatible']==b'ti,sysc-omap2\0ti,sysc\0'
    assert struct.unpack('>II',gpio5['ranges'][:8])==(0,0x4805b000)
    bank=nodes['/target-module@4805b000/gpio@0']
    assert bank['compatible']==b'ti,omap4-gpio\0'
    assert bank['interrupts']==struct.pack('>III',0,33,4)
    touch=nodes['/target-module@48072000/i2c@0/touchscreen@67']
    assert touch['compatible']==b'cisco,perrier-cyttsp4\0'
    assert touch['reg']==struct.pack('>I',0x67)
    assert touch['interrupt-parent']==bank['phandle']
    assert touch['interrupts']==struct.pack('>II',14,2)
    assert touch['touchscreen-size-x']==struct.pack('>I',1280)
    assert touch['touchscreen-size-y']==struct.pack('>I',800)
    assert not any('reset' in prop or 'supply' in prop or 'firmware' in prop
                   for prop in touch)
    fs=DEST/'rootfs'
    entries=json.loads((DEST/'rootfs-manifest.json').read_text())
    assert 'usr/bin/touch-uinput' not in entries
    assert 'usr/sbin/ram-guard' in entries
    startup=(fs/'etc/init.d/rcS').read_text()
    assert 'perrier-interactive-ram50' in startup
    assert 'touch-uinput' not in startup and 'touch.pid' not in startup
    assert 'native-cyttsp4' in startup
    for name,info in entries.items():
        p=fs/name
        if 'symlink' in info:
            assert p.is_symlink() and str(p.readlink())==info['symlink'],name
        else:
            assert sha(p)==info['sha256'] and p.stat().st_size==info['bytes'],name
    for name in ('etc/shadow','etc/dropbear/ram_host_key','root/.ssh/authorized_keys'):
        assert stat.S_IMODE((fs/name).stat().st_mode)==0o600
    assert manifest['guard_sha256']==sha(fs/'usr/sbin/ram-guard')
    proof=json.loads((RAM/'watchdog-proof.json').read_text())
    assert proof['status']=='passed' and proof['guard_sha256']==manifest['guard_sha256']
    subprocess.run(['sh','-n',fs/'etc/init.d/rcS'],check=True)
    subprocess.run(['sh','-n',fs/'usr/bin/qt-run'],check=True)
    # Check packed regular files and symlinks, including the SSH and guard files.
    data=(DEST/'initramfs.cpio').read_bytes()
    pos=0
    packed=set()
    while True:
        assert data[pos:pos+6]==b'070701'
        fields=[int(data[pos+6+i*8:pos+14+i*8],16) for i in range(13)]
        mode,size,namesize=fields[1],fields[6],fields[11]
        name=data[pos+110:pos+110+namesize-1].decode()
        start=(pos+110+namesize+3)&~3
        payload=data[start:start+size]
        pos=(start+size+3)&~3
        if name=='TRAILER!!!': break
        if stat.S_ISREG(mode):
            assert hashlib.sha256(payload).hexdigest()==entries[name]['sha256'],name
            packed.add(name)
        elif stat.S_ISLNK(mode):
            assert payload.decode()==entries[name]['symlink'],name
            packed.add(name)
    assert packed==set(entries)
    report=dict(manifest,passed=True,kernel_span_bytes=image_end-0xc0000000,
                config_changes=changes,
                purpose='Native Gen4 touch RAM image, key-only SSH, inherited WDT2 with host lease')
    (DEST/'reviewed-image.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'kernel':report['kernel'],
                      'kernel_span_bytes':report['kernel_span_bytes'],
                      'config_changes':changes},indent=2))

if __name__=='__main__': audit()
