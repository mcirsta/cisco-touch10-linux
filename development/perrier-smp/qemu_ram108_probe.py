#!/usr/bin/env python3
"""Boot the ram108 built-in archive on generic Cortex-A9 QEMU.

This does not model the OMAP4460 board or its CPU1 release path. It only
tests whether an SMP ARM kernel can unpack and enter this exact archive.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'development/kernel/work/linux-6.18.48'
ARCHIVE = ROOT / 'development/perrier-ramenv/smp-uboot-nosmp/initramfs.cpio'
MANIFEST = ROOT / 'development/perrier-ramenv/smp-uboot-nosmp/manifest.json'
OUT = ROOT / 'development/perrier-smp/qemu-ram108-archive'
BUILD = OUT / 'kernel-build'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def command(args, log, env=None):
    with log.open('w') as stream:
        subprocess.run([str(x) for x in args], cwd=ROOT, env=env,
                       stdout=stream, stderr=subprocess.STDOUT, check=True)


def main():
    OUT.mkdir(exist_ok=True)
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['kernel'] == '6.18.48-perrier-ram108'
    assert sha(ARCHIVE) == manifest['initramfs_sha256']
    env = dict(os.environ, KBUILD_BUILD_USER='touch10', KBUILD_BUILD_HOST='perrier-dev',
               KBUILD_BUILD_TIMESTAMP='2026-11-12 00:00:00 UTC')
    make = ['make', '-C', SOURCE, f'O={BUILD}', 'ARCH=arm', 'LLVM=1']
    command(make + ['vexpress_defconfig'], OUT / 'defconfig.log', env)
    command([SOURCE / 'scripts/config', '--file', BUILD / '.config',
             '--enable', 'SMP', '--set-val', 'NR_CPUS', '2',
             '--enable', 'BLK_DEV_INITRD', '--enable', 'INITRAMFS_COMPRESSION_GZIP',
             '--set-str', 'INITRAMFS_SOURCE', ARCHIVE,
             '--set-str', 'LOCALVERSION', '-qemu-ram108-archive'],
            OUT / 'config.log', env)
    command(make + ['olddefconfig'], OUT / 'olddefconfig.log', env)
    config = (BUILD / '.config').read_text()
    for expected in ('CONFIG_SMP=y', 'CONFIG_NR_CPUS=2',
                     f'CONFIG_INITRAMFS_SOURCE="{ARCHIVE}"',
                     'CONFIG_INITRAMFS_COMPRESSION_GZIP=y'):
        assert expected in config, expected
    command(make + ['-j8', 'zImage', 'arm/vexpress-v2p-ca9.dtb'], OUT / 'build.log', env)
    kernel = BUILD / 'arch/arm/boot/zImage'
    dtb = BUILD / 'arch/arm/boot/dts/arm/vexpress-v2p-ca9.dtb'
    assert kernel.is_file() and dtb.is_file()
    qemu = ['qemu-system-arm', '-M', 'vexpress-a9', '-cpu', 'cortex-a9',
            '-smp', '2', '-m', '512M', '-display', 'none', '-monitor', 'none',
            '-serial', 'stdio', '-nic', 'none', '-no-reboot', '-kernel', str(kernel),
            '-dtb', str(dtb),
            '-append', 'console=ttyAMA0 loglevel=7 rdinit=/bin/sh']
    timed_out = False
    with (OUT / 'serial.log').open('wb') as stream:
        process = subprocess.Popen(qemu, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT)
        try:
            process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait(timeout=5)
    serial = (OUT / 'serial.log').read_text(errors='replace')
    markers = {
        'two_cpus_online': 'Brought up 1 node, 2 CPUs' in serial,
        'initramfs_unpacked': 'Unpacking initramfs' in serial or
                              'Freeing unused kernel image (initmem)' in serial,
        'shell_entered': 'Run /bin/sh as init process' in serial,
        'archive_panic': 'broken padding' in serial or
                         'junk within compressed archive' in serial,
    }
    passed = (markers['two_cpus_online'] and markers['initramfs_unpacked']
              and markers['shell_entered'] and not markers['archive_panic'])
    report = {
        'passed': passed, 'scope': 'generic Cortex-A9 built-in archive parser only',
        'board_emulation': False, 'archive_sha256': sha(ARCHIVE),
        'kernel_zimage_sha256': sha(kernel), 'dtb_sha256': sha(dtb),
        'kernel_config_sha256': sha(BUILD / '.config'),
        'qemu_timeout': timed_out, 'qemu_exit_code': process.returncode,
        'markers': markers, 'serial_log': str(OUT / 'serial.log'),
    }
    (OUT / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
