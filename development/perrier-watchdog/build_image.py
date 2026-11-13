#!/usr/bin/env python3
"""Build a separate ram59 image with mainline OMAP watchdog ownership."""
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
BASE = RAM / 'native-thermal'
DEST = RAM / 'native-watchdog'
FS = DEST / 'rootfs'
OUT = DEST / 'kernel-build'
SRC = ROOT / 'development/sources/linux-6.18.48'
NATIVE = ROOT / 'development/perrier-native'
PREFIX = str(ROOT / 'development/perrier-qt/sources/'
             'armv7-eabihf--musl--stable-2026.08-1/bin/arm-buildroot-linux-musleabihf-')
VERSION = '6.18.48-perrier-ram59'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def main() -> None:
    os.umask(0o077)
    review_path = BASE / 'reviewed-image.json'
    review = json.loads(review_path.read_text())
    if not review['passed'] or review['kernel'] != '6.18.48-perrier-ram58':
        raise ValueError('The ram58 baseline is not audited')
    for item in review['artifacts'].values():
        if sha(Path(item['path'])) != item['sha256']:
            raise ValueError('A ram58 artifact changed')
    if sha(BASE / 'kernel-build/.config') != review['kernel_config_sha256'] or \
       sha(BASE / 'rootfs-manifest.json') != review['rootfs_manifest_sha256']:
        raise ValueError('The ram58 config or filesystem manifest changed')
    for name, item in json.loads((BASE / 'rootfs-manifest.json').read_text()).items():
        path = BASE / 'rootfs' / name
        if 'symlink' in item:
            if not path.is_symlink() or str(path.readlink()) != item['symlink']:
                raise ValueError('A baseline symlink changed: ' + name)
        elif sha(path) != item['sha256']:
            raise ValueError('A baseline rootfs file changed: ' + name)

    spec = importlib.util.spec_from_file_location('native_build', NATIVE / 'build.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    native.apply_kernel_patches()
    native.apply_kernel_patches(ROOT / 'development/perrier-touch/kernel-patches')
    DEST.mkdir(exist_ok=True)
    if FS.exists():
        shutil.rmtree(FS)
    shutil.copytree(BASE / 'rootfs', FS, symlinks=True)
    run([PREFIX + 'gcc', '-O2', '-g', '-Wall', '-Wextra', '-Werror', '-static',
         '-mcpu=cortex-a9', '-mfpu=neon', '-mfloat-abi=hard',
         HERE / 'ram_guard_device.c', '-o', DEST / 'ram-guard'])
    shutil.copy2(DEST / 'ram-guard', FS / 'usr/sbin/ram-guard')
    run([PREFIX + 'strip', '--strip-unneeded', FS / 'usr/sbin/ram-guard'])
    startup = (FS / 'etc/init.d/rcS').read_text()
    if startup.count('ram58') != 2:
        raise ValueError('Unexpected baseline startup script')
    startup = startup.replace('ram58', 'ram59')
    guard_start = '/usr/sbin/ram-guard daemon > /run/guard.log 2>&1 &\necho $! > /run/guard.pid\n'
    if startup.count(guard_start) != 1:
        raise ValueError('Unexpected baseline guard startup')
    startup = startup.replace(guard_start, guard_start + '''guard_wait=0
while ! grep -q '"state":"feeding"' /run/guard.json 2>/dev/null; do
    if [ "$guard_wait" -ge 5 ] || ! kill -0 "$(cat /run/guard.pid)" 2>/dev/null; then
        echo PERRIER_GUARD_START_FAILED
        cat /run/guard.log
        reboot -f
        while :; do sleep 1; done
    fi
    sleep 1
    guard_wait=$((guard_wait+1))
done
''')
    (FS / 'etc/init.d/rcS').write_text(startup)
    root_manifest = {}
    archive = b''
    for path in sorted(FS.rglob('*')):
        name = str(path.relative_to(FS))
        if path.is_symlink():
            target = str(path.readlink())
            archive += native.cpio_entry(name, stat.S_IFLNK | 0o777, target.encode())
            root_manifest[name] = {'symlink': target}
        elif path.is_dir():
            archive += native.cpio_entry(name, stat.S_IFDIR | stat.S_IMODE(path.stat().st_mode))
        else:
            archive += native.cpio_entry(name, stat.S_IFREG | stat.S_IMODE(path.stat().st_mode),
                                         path.read_bytes())
            root_manifest[name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    archive += native.cpio_entry('dev/console', stat.S_IFCHR | 0o600, major=5, minor=1)
    archive += native.cpio_entry('dev/null', stat.S_IFCHR | 0o666, major=1, minor=3)
    archive += native.cpio_entry('TRAILER!!!', 0)
    (DEST / 'initramfs.cpio').write_bytes(archive)
    (DEST / 'rootfs-manifest.json').write_text(json.dumps(root_manifest, indent=2) + '\n')

    OUT.mkdir(exist_ok=True)
    shutil.copy2(BASE / 'kernel-build/.config', OUT / '.config')
    old_cmdline = next(line.split('=', 1)[1][1:-1] for line in
                       (OUT / '.config').read_text().splitlines()
                       if line.startswith('CONFIG_CMDLINE='))
    run([SRC / 'scripts/config', '--file', OUT / '.config',
         '--set-str', 'LOCALVERSION', '-perrier-ram59',
         '--set-str', 'INITRAMFS_SOURCE', DEST / 'initramfs.cpio',
         '--set-str', 'CMDLINE', old_cmdline + ' omap_wdt.early_enable=1 omap_wdt.timer_margin=120',
         '--enable', 'WATCHDOG', '--enable', 'OMAP_WATCHDOG',
         '--enable', 'WATCHDOG_NOWAYOUT', '--enable', 'WATCHDOG_SYSFS',
         '--enable', 'WATCHDOG_HANDLE_BOOT_ENABLED', '--set-val', 'WATCHDOG_OPEN_TIMEOUT', '60'])
    env = dict(os.environ, KBUILD_BUILD_USER='touch10', KBUILD_BUILD_HOST='perrier-dev',
               KBUILD_BUILD_TIMESTAMP='2026-11-10 00:00:00 UTC')
    make = ['make', '-C', SRC, f'O={OUT}', 'ARCH=arm', 'LLVM=1']
    run(make + ['olddefconfig'], env=env)
    shutil.copy2(OUT / '.config', DEST / 'kernel.config')
    run(make + ['-j' + str(os.cpu_count() or 1), 'zImage'], env=env)
    with (DEST / 'preprocessed.dts').open('wb') as stream:
        run(['clang', '-E', '-P', '-x', 'assembler-with-cpp', '-nostdinc', '-undef', '-D__DTS__',
             '-I', SRC / 'arch/arm/boot/dts/ti/omap', '-I', SRC / 'scripts/dtc/include-prefixes',
             HERE / 'omap4-perrier-watchdog.dts'], stdout=stream)
    run([OUT / 'scripts/dtc/dtc', '-i', SRC / 'arch/arm/boot/dts/ti/omap',
         '-I', 'dts', '-O', 'dtb', '-o', DEST / 'board.dtb', DEST / 'preprocessed.dts'])
    files = {'zImage': OUT / 'arch/arm/boot/zImage', 'board.dtb': DEST / 'board.dtb',
             'kexec': ROOT / 'development/perrier/kexec-legacy-fdt'}
    inputs = {'baseline_review': review_path, 'guard_source': HERE / 'ram_guard_device.c',
              'watchdog_dts': HERE / 'omap4-perrier-watchdog.dts',
              'omap_wdt_source': SRC / 'drivers/watchdog/omap_wdt.c',
              'watchdog_core_source': SRC / 'drivers/watchdog/watchdog_dev.c',
              'ti_sysc_source': SRC / 'drivers/bus/ti-sysc.c',
              'native_patch_manifest': NATIVE / 'kernel-patches/manifest.json',
              'touch_patch_manifest': ROOT / 'development/perrier-touch/kernel-patches/manifest.json'}
    manifest = {'kernel': VERSION, 'profile': 'native-watchdog',
                'artifacts': {name: {'path': str(path), 'sha256': sha(path),
                                     'size': path.stat().st_size} for name, path in files.items()},
                'inputs': {name: {'path': str(path), 'sha256': sha(path)} for name, path in inputs.items()},
                'initramfs_sha256': sha(DEST / 'initramfs.cpio'),
                'rootfs_manifest_sha256': sha(DEST / 'rootfs-manifest.json'),
                'kernel_config_sha256': sha(OUT / '.config'),
                'guard_sha256': sha(FS / 'usr/sbin/ram-guard')}
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
