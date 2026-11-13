#!/usr/bin/env python3
"""Audit a current-rootfs image against the known-working single-core ram52."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RAM = ROOT / 'development/perrier-ramenv'
BASE = RAM / 'native-keypad'
DEST = RAM / 'native-keypad-newqt'
fdt_nodes = runpy.run_path(str(ROOT / 'development/perrier-simpledrm/audit.py'))['fdt_nodes']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)

def audit():
    manifest = json.loads((DEST / 'manifest.json').read_text())
    assert manifest['profile'] == 'keypad-newqt'
    assert manifest['kernel'] == '6.18.48-perrier-ram57'
    for info in manifest['artifacts'].values():
        path = Path(info['path'])
        assert sha(path) == info['sha256'] and path.stat().st_size == info['size'], path
    assert sha(DEST / 'initramfs.cpio') == manifest['initramfs_sha256']
    assert sha(DEST / 'rootfs-manifest.json') == manifest['rootfs_manifest_sha256']
    assert sha(DEST / 'kernel-build/.config') == manifest['kernel_config_sha256']
    assert sha(DEST / 'rootfs/usr/sbin/ram-guard') == manifest['guard_sha256']
    assert fdt_nodes((BASE / 'board.dtb').read_bytes()) == fdt_nodes((DEST / 'board.dtb').read_bytes())

    old = config(BASE / 'kernel-build/.config')
    new = config(DEST / 'kernel-build/.config')
    changes = {key: (old.get(key), new.get(key)) for key in old.keys() | new.keys()
               if old.get(key) != new.get(key)}
    assert set(changes) == {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE'}, changes
    assert new['CONFIG_LOCALVERSION'] == '"-perrier-ram57"'
    assert new['CONFIG_INITRAMFS_SOURCE'] == '"' + str(DEST / 'initramfs.cpio') + '"'
    assert new.get('CONFIG_SMP') != 'y'
    prior = json.loads((BASE / 'rootfs-manifest.json').read_text())
    current = json.loads((DEST / 'rootfs-manifest.json').read_text())
    changed = {key for key in prior.keys() | current.keys() if prior.get(key) != current.get(key)}
    assert changed == {'etc/init.d/rcS', 'qt/bin/perrier-touch-grid'}, changed
    assert 'perrier-interactive-ram57' in (DEST / 'rootfs/etc/init.d/rcS').read_text()
    subprocess.run(['sh', '-n', DEST / 'rootfs/etc/init.d/rcS'], check=True)
    proof = json.loads((RAM / 'watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['guard_sha256'] == manifest['guard_sha256']
    report = dict(manifest, passed=True, config_changes=changes,
                  rootfs_changes=sorted(changed),
                  purpose='Current Qt binary and initramfs with known-working non-SMP config')
    (DEST / 'reviewed-image.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'kernel': report['kernel'],
                      'rootfs_changes': report['rootfs_changes']}, indent=2))

if __name__ == '__main__':
    audit()
