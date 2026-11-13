#!/usr/bin/env python3
"""Build the smallest serial-only Perrier image for a U-Boot cold-boot proof."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SRC = ROOT / 'development/sources/linux-6.18.48'
BASE = ROOT / 'development/perrier/baselines/ram01'
OUT = HERE / 'kernel-build'
VERSION = '6.18.48-perrier-cold01'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cpio_entry(name: str, mode: int, content: bytes = b'', major=0, minor=0) -> bytes:
    filename = name.encode() + b'\0'
    fields = [1, mode, 0, 0, 1, 0, len(content), 0, 0, major, minor, len(filename), 0]
    header = b'070701' + b''.join(f'{value:08x}'.encode() for value in fields) + filename
    return header + bytes(-len(header) % 4) + content + bytes(-len(content) % 4)


def run(command, **kwargs):
    subprocess.run([str(x) for x in command], check=True, **kwargs)


def main() -> None:
    reviewed = json.loads((BASE / 'reviewed-trial.json').read_text())
    baseline_dtb = BASE / 'omap4-perrier-ram.dtb'
    if not reviewed['passed'] or reviewed['kernel'] != '6.18.48-perrier-ram01' or \
       sha(baseline_dtb) != reviewed['artifacts']['board.dtb']['sha256']:
        raise ValueError('The minimal Perrier DTB baseline changed')
    HERE.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    run([ROOT / 'development/toolchain/arm-cc', '-O2', '-static', '-Wall', '-Wextra',
         '-o', HERE / 'init', HERE / 'init.c'])
    content = b''
    for directory in ('dev', 'proc', 'sys'):
        content += cpio_entry(directory, stat.S_IFDIR | 0o755)
    content += cpio_entry('dev/console', stat.S_IFCHR | 0o600, major=5, minor=1)
    content += cpio_entry('dev/null', stat.S_IFCHR | 0o666, major=1, minor=3)
    content += cpio_entry('init', stat.S_IFREG | 0o755, (HERE / 'init').read_bytes())
    content += cpio_entry('TRAILER!!!', 0)
    (HERE / 'initramfs.cpio').write_bytes(content)
    config = (BASE / 'minimal.config').read_text()
    if config.count('CONFIG_LOCALVERSION="-perrier-ram01"') != 1:
        raise ValueError('Unexpected baseline config version')
    config = config.replace('CONFIG_LOCALVERSION="-perrier-ram01"',
                            'CONFIG_LOCALVERSION="-perrier-cold01"')
    if 'CONFIG_INITRAMFS_SOURCE=' in config:
        raise ValueError('Unexpected baseline initramfs source')
    config += f'CONFIG_INITRAMFS_SOURCE="{HERE / "initramfs.cpio"}"\n'
    (HERE / 'kernel.config').write_text(config)
    env = dict(os.environ, KCONFIG_ALLCONFIG=str(HERE / 'kernel.config'),
               KBUILD_BUILD_USER='touch10', KBUILD_BUILD_HOST='perrier-dev',
               KBUILD_BUILD_TIMESTAMP='2026-11-10 00:00:00 UTC')
    make = ['make', '-C', SRC, f'O={OUT}', 'ARCH=arm', 'LLVM=1']
    run(make + ['allnoconfig'], env=env)
    env.pop('KCONFIG_ALLCONFIG')
    run(make + ['olddefconfig'], env=env)
    run(make + ['-j' + str(os.cpu_count() or 1), 'zImage'], env=env)
    shutil.copy2(baseline_dtb, HERE / 'board.dtb')
    files = {'zImage': OUT / 'arch/arm/boot/zImage',
             'board.dtb': HERE / 'board.dtb',
             'init': HERE / 'init',
             'initramfs.cpio': HERE / 'initramfs.cpio',
             '.config': OUT / '.config'}
    manifest = {
        'kernel': VERSION,
        'source': str(SRC.relative_to(ROOT)),
        'baseline_dtb_sha256': sha(baseline_dtb),
        'artifacts': {name: {'path': str(path.relative_to(ROOT)),
                             'bytes': path.stat().st_size, 'sha256': sha(path)}
                      for name, path in files.items()},
    }
    (HERE / 'probe-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
