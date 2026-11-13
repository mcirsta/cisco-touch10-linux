#!/usr/bin/env python3
"""Build ram99 with 48 kHz ALSA application playback and native Qt mixer control."""
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
RAM = ROOT / 'development/perrier-ramenv'
BASE = RAM / 'native-audio'
DEST = RAM / 'speaker-audio'
FS = DEST / 'rootfs'
OUT = DEST / 'kernel-build'
SRC = HERE / 'work/linux-6.18.48'
from common import SOURCE, cpio_entry, audit_archive


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def main():
    os.umask(0o077)
    run(['python3', HERE / 'export_patches.py'])
    run(['python3', HERE / 'prepare_source.py'])
    baseline_path = BASE / 'reviewed-image.json'
    baseline = json.loads(baseline_path.read_text())
    proof_path = RAM / 'native-watchdog/watchdog-proof.json'
    proof = json.loads(proof_path.read_text())
    assert baseline['passed'] and baseline['kernel'] == '6.18.48-perrier-ram97'
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
    DEST.mkdir(exist_ok=True)
    if FS.exists():
        shutil.rmtree(FS)
    shutil.copytree(BASE / 'rootfs', FS, symlinks=True)
    startup = (FS / 'etc/init.d/rcS').read_text()
    assert startup.count('ram97') == 2
    (FS / 'etc/init.d/rcS').write_text(startup.replace('ram97', 'ram99'))
    qt = ROOT / 'development/perrier-qt'
    qt_manifest = json.loads((qt / 'runtime-manifest.json').read_text())
    qt_app = qt / 'runtime/bin/perrier-touch-grid'
    assert sha(qt_app) == qt_manifest['files']['bin/perrier-touch-grid']['sha256']
    changed = {'etc/init.d/rcS', 'qt/bin/perrier-touch-grid',
               'qt/lib/libasound.so.2', 'qt/licenses/ALSA.txt',
               'etc/asound.conf', 'usr/bin/aplay', 'usr/share/licenses/alsa-utils.txt'}
    for name, item in qt_manifest['files'].items():
        target = FS / 'qt' / name
        if 'qt/' + name not in changed:
            assert sha(target) == item['sha256'], name
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            assert sha(qt / 'runtime' / name) == item['sha256']
            shutil.copy2(qt / 'runtime' / name, target)
    audio = ROOT / 'development/audio'
    app_manifest = json.loads((audio / 'application-manifest.json').read_text())
    for name, item in app_manifest['files'].items():
        assert sha(audio / name) == item['sha256'], name
    shutil.copytree(audio / 'app-install/etc/alsa', FS / 'etc/alsa')
    changed |= {str(p.relative_to(FS)) for p in (FS / 'etc/alsa').rglob('*') if p.is_file()}
    shutil.copy2(audio / 'asound.conf', FS / 'etc/asound.conf')
    shutil.copy2(audio / 'app-build/alsa-utils/aplay/aplay', FS / 'usr/bin/aplay')
    run([qt / 'sources/armv7-eabihf--musl--stable-2026.08-1/bin/arm-buildroot-linux-musleabihf-strip',
         '--strip-unneeded', FS / 'usr/bin/aplay'])
    (FS / 'usr/share/licenses').mkdir(parents=True, exist_ok=True)
    shutil.copy2(audio / 'alsa-utils/COPYING', FS / 'usr/share/licenses/alsa-utils.txt')
    root_manifest, chunks = {}, []
    for path in sorted(FS.rglob('*')):
        name = str(path.relative_to(FS))
        if path.is_symlink():
            target = str(path.readlink())
            chunks.append(cpio_entry(name, stat.S_IFLNK | 0o777, target.encode()))
            root_manifest[name] = {'symlink': target}
        elif path.is_dir():
            chunks.append(cpio_entry(name, stat.S_IFDIR | stat.S_IMODE(path.stat().st_mode)))
        else:
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            assert payload == path.read_bytes(), 'Unstable payload read: ' + name
            if name not in changed:
                assert digest == entries[name]['sha256'], name
            chunks.append(cpio_entry(name, stat.S_IFREG | stat.S_IMODE(path.stat().st_mode), payload))
            root_manifest[name] = {'sha256': digest, 'bytes': len(payload)}
    chunks.append(cpio_entry('dev/console', stat.S_IFCHR | 0o600, major=5, minor=1))
    chunks.append(cpio_entry('dev/null', stat.S_IFCHR | 0o666, major=1, minor=3))
    chunks.append(cpio_entry('TRAILER!!!', 0))
    temporary = DEST / 'initramfs.cpio.new'
    expected_archive = hashlib.sha256()
    with temporary.open('wb') as stream:
        for chunk in chunks:
            expected_archive.update(chunk)
            assert stream.write(chunk) == len(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    assert sha(temporary) == expected_archive.hexdigest(), 'Archive differs after writing'
    audit_archive(temporary, root_manifest)
    temporary.replace(DEST / 'initramfs.cpio')
    (DEST / 'rootfs-manifest.json').write_text(json.dumps(root_manifest, indent=2) + '\n')
    archive_digest = sha(DEST / 'initramfs.cpio')
    audit_archive(DEST / 'initramfs.cpio', root_manifest)
    print('Verified packed archive before compilation: ' + archive_digest, flush=True)
    OUT.mkdir(exist_ok=True)
    shutil.copy2(HERE / 'configs/perrier-ram.config', OUT / '.config')
    run([SRC / 'scripts/config', '--file', OUT / '.config',
         '--set-str', 'LOCALVERSION', '-perrier-ram99',
         '--set-str', 'INITRAMFS_SOURCE', DEST / 'initramfs.cpio', '--enable', 'PINCTRL_SINGLE'])
    make = ['make', '-C', SRC, f'O={OUT}', 'ARCH=arm', 'LLVM=1']
    env = dict(os.environ, KBUILD_BUILD_USER='touch10', KBUILD_BUILD_HOST='perrier-dev',
               KBUILD_BUILD_TIMESTAMP='2026-11-12 00:00:00 UTC')
    run(make + ['olddefconfig'], env=env)
    shutil.copy2(OUT / '.config', DEST / 'kernel.config')
    run(make + ['-j' + str(os.cpu_count() or 1), 'zImage'], env=env)
    assert sha(DEST / 'initramfs.cpio') == archive_digest, 'Archive changed during compilation'
    run(make + ['ti/omap/omap4-cisco-perrier-ram.dtb'], env=env)
    shutil.copy2(OUT / 'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier-ram.dtb',
                 DEST / 'board.dtb')
    files = {'zImage': OUT / 'arch/arm/boot/zImage', 'board.dtb': DEST / 'board.dtb',
             'kexec': ROOT / 'development/perrier/kexec-legacy-fdt'}
    inputs = {'baseline_review': baseline_path, 'watchdog_proof': proof_path,
              'confirmed_baseline': HERE / 'validation-ram97.json',
              'qt_app_source': qt / 'app/main.cpp',
              'qt_ui_source': qt / 'app/Main.qml',
              'qt_audio_source': qt / 'app/audio_backend.cpp',
              'qt_audio_header': qt / 'app/audio_backend.h',
              'qt_pcm_setup': qt / 'app/pcm_setup.h',
              'alsa_manifest': audio / 'application-manifest.json',
              'alsa_config': audio / 'asound.conf',
              'alsa_build_script': audio / 'build_application_audio.py',
              'conversion_test': audio / 'test_conversion.py',
              'conversion_checks': HERE / 'out/application-audio/conversion-checks.json',
              'qt_runtime_manifest': qt / 'runtime-manifest.json',
              'source_manifest': HERE / 'patches/manifest.json',
              'ram_config': HERE / 'configs/perrier-ram.config',
              'bus_policy': HERE / 'configs/bus-layout.json',
              'hardware_dtsi': SOURCE / 'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier.dtsi',
              'ram_dts': SOURCE / 'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier-ram.dts'}
    manifest = {'kernel': '6.18.48-perrier-ram99', 'profile': 'speaker-audio',
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
