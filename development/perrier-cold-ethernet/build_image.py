#!/usr/bin/env python3
"""Build ram60 with stock-evidenced Ethernet pinmux, clock and reset control."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RAM = ROOT / 'development/perrier-ramenv'
BASE = RAM / 'native-watchdog'
DEST = RAM / 'cold-ethernet'
FS = DEST / 'rootfs'
OUT = DEST / 'kernel-build'
SRC = ROOT / 'development/sources/linux-6.18.48'
NATIVE = ROOT / 'development/perrier-native'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def main():
    os.umask(0o077)
    baseline_path = BASE / 'reviewed-image.json'
    baseline = json.loads(baseline_path.read_text())
    proof_path = BASE / 'watchdog-proof.json'
    proof = json.loads(proof_path.read_text())
    assert baseline['passed'] and baseline['kernel'] == '6.18.48-perrier-ram59'
    assert proof['status'] == 'passed' and proof['guard_sha256'] == baseline['guard_sha256']
    for item in baseline['artifacts'].values():
        assert sha(Path(item['path'])) == item['sha256']
    assert sha(BASE / 'rootfs-manifest.json') == baseline['rootfs_manifest_sha256']
    assert sha(BASE / 'kernel-build/.config') == baseline['kernel_config_sha256']
    entries = json.loads((BASE / 'rootfs-manifest.json').read_text())
    for name, item in entries.items():
        path = BASE / 'rootfs' / name
        if 'symlink' in item:
            assert path.is_symlink() and str(path.readlink()) == item['symlink'], name
        else:
            assert sha(path) == item['sha256'], name
    spec = importlib.util.spec_from_file_location('native_build', NATIVE / 'build.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    native.apply_kernel_patches()
    native.apply_kernel_patches(ROOT / 'development/perrier-touch/kernel-patches')
    DEST.mkdir(exist_ok=True)
    if FS.exists():
        shutil.rmtree(FS)
    shutil.copytree(BASE / 'rootfs', FS, symlinks=True)
    startup = (FS / 'etc/init.d/rcS').read_text()
    assert startup.count('ram59') == 2
    (FS / 'etc/init.d/rcS').write_text(startup.replace('ram59', 'ram60'))
    root_manifest, archive = {}, b''
    for path in sorted(FS.rglob('*')):
        name = str(path.relative_to(FS))
        if path.is_symlink():
            target = str(path.readlink())
            archive += native.cpio_entry(name, stat.S_IFLNK | 0o777, target.encode())
            root_manifest[name] = {'symlink': target}
        elif path.is_dir():
            archive += native.cpio_entry(name, stat.S_IFDIR | stat.S_IMODE(path.stat().st_mode))
        else:
            archive += native.cpio_entry(name, stat.S_IFREG | stat.S_IMODE(path.stat().st_mode), path.read_bytes())
            root_manifest[name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    archive += native.cpio_entry('dev/console', stat.S_IFCHR | 0o600, major=5, minor=1)
    archive += native.cpio_entry('dev/null', stat.S_IFCHR | 0o666, major=1, minor=3)
    archive += native.cpio_entry('TRAILER!!!', 0)
    (DEST / 'initramfs.cpio').write_bytes(archive)
    (DEST / 'rootfs-manifest.json').write_text(json.dumps(root_manifest, indent=2) + '\n')
    OUT.mkdir(exist_ok=True)
    shutil.copy2(BASE / 'kernel-build/.config', OUT / '.config')
    run([SRC / 'scripts/config', '--file', OUT / '.config',
         '--set-str', 'LOCALVERSION', '-perrier-ram60',
         '--set-str', 'INITRAMFS_SOURCE', DEST / 'initramfs.cpio', '--enable', 'PINCTRL_SINGLE'])
    make = ['make', '-C', SRC, f'O={OUT}', 'ARCH=arm', 'LLVM=1']
    env = dict(os.environ, KBUILD_BUILD_USER='touch10', KBUILD_BUILD_HOST='perrier-dev',
               KBUILD_BUILD_TIMESTAMP='2026-11-10 00:00:00 UTC')
    run(make + ['olddefconfig'], env=env)
    shutil.copy2(OUT / '.config', DEST / 'kernel.config')
    run(make + ['-j' + str(os.cpu_count() or 1), 'zImage'], env=env)
    with (DEST / 'preprocessed.dts').open('wb') as stream:
        run(['clang', '-E', '-P', '-x', 'assembler-with-cpp', '-nostdinc', '-undef', '-D__DTS__',
             '-I', SRC / 'arch/arm/boot/dts/ti/omap', '-I', SRC / 'scripts/dtc/include-prefixes',
             HERE / 'omap4-perrier-cold-ethernet.dts'], stdout=stream)
    run([OUT / 'scripts/dtc/dtc', '-i', SRC / 'arch/arm/boot/dts/ti/omap',
         '-I', 'dts', '-O', 'dtb', '-o', DEST / 'board.dtb', DEST / 'preprocessed.dts'])
    files = {'zImage': OUT / 'arch/arm/boot/zImage', 'board.dtb': DEST / 'board.dtb',
             'kexec': ROOT / 'development/perrier/kexec-legacy-fdt'}
    inputs = {'baseline_review': baseline_path, 'watchdog_proof': proof_path,
              'ethernet_dts': HERE / 'omap4-perrier-cold-ethernet.dts',
              'stock_gpio_pad_clock': ROOT / 'evidence/perrier-stock-coldinit-gpio-clock-2026-11-10.txt',
              'generic_phy_source': SRC / 'drivers/usb/phy/phy-generic.c',
              'ehci_source': SRC / 'drivers/usb/host/ehci-omap.c',
              'pinctrl_source': SRC / 'drivers/pinctrl/pinctrl-single.c'}
    manifest = {'kernel': '6.18.48-perrier-ram60', 'profile': 'cold-ethernet',
                'artifacts': {name: {'path': str(path), 'size': path.stat().st_size, 'sha256': sha(path)}
                              for name, path in files.items()},
                'inputs': {name: {'path': str(path), 'sha256': sha(path)} for name, path in inputs.items()},
                'rootfs_manifest_sha256': sha(DEST / 'rootfs-manifest.json'),
                'initramfs_sha256': sha(DEST / 'initramfs.cpio'),
                'kernel_config_sha256': sha(OUT / '.config'),
                'guard_sha256': sha(FS / 'usr/sbin/ram-guard'),
                'watchdog_backend': 'linux-watchdog'}
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
