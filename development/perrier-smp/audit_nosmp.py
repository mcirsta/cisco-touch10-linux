#!/usr/bin/env python3
"""Audit no-SMP-activation isolation against the failed ram54."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RAM = ROOT/'development/perrier-ramenv'
BASE = RAM/'native-smp-onecpu'
DEST = RAM/'native-smp-nosmp'
HERE = Path(__file__).resolve().parent
fdt_nodes = runpy.run_path(str(ROOT/'development/perrier-simpledrm/audit.py'))['fdt_nodes']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)

def audit():
    manifest = json.loads((DEST/'manifest.json').read_text())
    assert manifest['profile'] == 'smp-nosmp'
    assert manifest['kernel'] == '6.18.48-perrier-ram56'
    for info in manifest['artifacts'].values():
        path = Path(info['path'])
        assert sha(path) == info['sha256'] and path.stat().st_size == info['size'], path
    assert sha(DEST/'initramfs.cpio') == manifest['initramfs_sha256']
    assert sha(DEST/'rootfs-manifest.json') == manifest['rootfs_manifest_sha256']
    assert sha(DEST/'kernel-build/.config') == manifest['kernel_config_sha256']
    assert sha(HERE/'omap4-perrier-smp.dts') == manifest['smp_dts_sha256']
    assert sha(DEST/'rootfs/usr/sbin/ram-guard') == manifest['guard_sha256']
    proof = json.loads((RAM/'watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['guard_sha256'] == manifest['guard_sha256']
    assert fdt_nodes((BASE/'board.dtb').read_bytes()) == fdt_nodes((DEST/'board.dtb').read_bytes())

    previous = config(BASE/'kernel-build/.config')
    current = config(DEST/'kernel-build/.config')
    changes = {k:{'before':previous.get(k,'n'),'after':current.get(k,'n')}
               for k in sorted(set(previous)|set(current))
               if previous.get(k) != current.get(k)}
    assert set(changes) == {'CONFIG_LOCALVERSION','CONFIG_INITRAMFS_SOURCE','CONFIG_CMDLINE'}, changes
    assert current['CONFIG_SMP'] == 'y' and current['CONFIG_NR_CPUS'] == '2'
    assert current['CONFIG_CMDLINE_FORCE'] == 'y'
    assert current['CONFIG_CMDLINE'] == previous['CONFIG_CMDLINE'].removesuffix(' maxcpus=1"') + ' nosmp"'
    assert current['CONFIG_LOCALVERSION'] == '"-perrier-ram56"'
    assert current['CONFIG_INITRAMFS_SOURCE'] == '"'+str(DEST/'initramfs.cpio')+'"'
    for key in ('CONFIG_CPU_FREQ','CONFIG_CPU_IDLE','CONFIG_SUSPEND',
                'CONFIG_PINCTRL_SINGLE','CONFIG_WATCHDOG'):
        assert current.get(key) != 'y', key
    startup = (DEST/'rootfs/etc/init.d/rcS').read_text()
    assert 'perrier-interactive-ram56' in startup
    subprocess.run(['sh','-n',DEST/'rootfs/etc/init.d/rcS'],check=True)
    image_end=next(int(line.split()[0],16) for line in
                   (DEST/'kernel-build/System.map').read_text().splitlines()
                   if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    report=dict(manifest,passed=True,kernel_span_bytes=image_end-0xc0000000,
                config_changes=changes,purpose='SMP build with nosmp to skip OMAP SCU and CPU1 preparation')
    (DEST/'reviewed-image.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'kernel':report['kernel'],
                      'config_changes':changes},indent=2))

if __name__ == '__main__':
    audit()
