#!/usr/bin/env python3
"""Stage the Touch 10's own Cortex-A9 Qt 6.12 build for RAM trials."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'qt-arm'
TOOLCHAIN = HERE / 'sources/armv7-eabihf--musl--stable-2026.08-1'
SYSROOT = TOOLCHAIN / 'arm-buildroot-linux-musleabihf/sysroot'
STRIP = TOOLCHAIN / 'bin/arm-buildroot-linux-musleabihf-strip'
RUNTIME = HERE / 'runtime'

def copy(source, destination, strip=False):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if strip:
        subprocess.run([STRIP, '--strip-unneeded', destination], check=True)

def main():
    assert (SOURCE / 'lib/libQt6Core.so.6.12.0').is_file()
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    for module in ('Core', 'Gui', 'Qml', 'QmlMeta', 'QmlModels',
                   'QmlWorkerScript', 'Quick'):
        name = f'libQt6{module}.so.6'
        copy(SOURCE / 'lib' / f'{name}.12.0', RUNTIME / 'lib' / name, strip=True)
    for name in ('libstdc++.so.6', 'libgcc_s.so.1', 'libatomic.so.1'):
        source = SYSROOT / 'lib' / name
        if not source.exists():
            source = SYSROOT / 'usr/lib' / name
        copy(source, RUNTIME / 'lib' / name, strip=True)
    copy(SYSROOT / 'lib/libc.so', RUNTIME / 'lib/ld-musl-armhf.so.1', strip=True)
    (RUNTIME / 'lib/libc.so').symlink_to('ld-musl-armhf.so.1')
    copy(HERE.parent / 'audio/app-install/usr/lib/libasound.so.2.0.0',
         RUNTIME / 'lib/libasound.so.2', strip=True)
    copy(HERE.parent / 'audio/alsa-lib/COPYING', RUNTIME / 'licenses/ALSA.txt')
    copy(SOURCE / 'plugins/platforms/libqlinuxfb.so',
         RUNTIME / 'plugins/platforms/libqlinuxfb.so', strip=True)
    copy(SOURCE / 'plugins/platforms/libqoffscreen.so',
         RUNTIME / 'plugins/platforms/libqoffscreen.so', strip=True)
    for module in ('QML', 'QtQml', 'QtQml/Models', 'QtQml/WorkerScript',
                   'QtQuick', 'QtQuick/Window'):
        source_dir = SOURCE / 'qml' / module
        destination = RUNTIME / 'qml' / module
        destination.mkdir(parents=True, exist_ok=True)
        for path in source_dir.iterdir():
            if path.name == 'qmldir':
                copy(path, destination / path.name)
            elif path.suffix == '.so':
                copy(path, destination / path.name, strip=True)
    font_candidates = [Path(os.environ['PERRIER_FONT'])] if 'PERRIER_FONT' in os.environ else [
        Path('/usr/share/fonts/TTF/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
    ]
    font = next((path for path in font_candidates if path.is_file()), None)
    if font is None:
        raise SystemExit('Install DejaVu Sans or set PERRIER_FONT to its .ttf file')
    license_candidates = [Path(os.environ['PERRIER_FONT_LICENSE'])] \
        if 'PERRIER_FONT_LICENSE' in os.environ else [
            Path('/usr/share/licenses/ttf-dejavu/LICENSE'),
            Path('/usr/share/doc/fonts-dejavu-core/copyright'),
            Path('/usr/share/doc/ttf-dejavu/copyright'),
        ]
    license_file = next((path for path in license_candidates if path.is_file()), None)
    if license_file is None:
        raise SystemExit('Set PERRIER_FONT_LICENSE to the DejaVu license text')
    copy(font, RUNTIME / 'lib/fonts/DejaVuSans.ttf')
    copy(license_file, RUNTIME / 'licenses/DejaVu.txt')
    copy(HERE / 'build-arm-a9-local/perrier-touch-grid',
         RUNTIME / 'bin/perrier-touch-grid', strip=True)
    records = {}
    for path in sorted(RUNTIME.rglob('*')):
        if path.is_file() and not path.is_symlink():
            records[str(path.relative_to(RUNTIME))] = {
                'size': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    manifest = {'qt': '6.12.0', 'cpu': 'cortex-a9', 'fpu': 'neon-vfpv3',
                'source': str(SOURCE),
                'files': records}
    (HERE / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Staged {len(records)} Qt files, '
          f'{sum(item["size"] for item in records.values())} bytes')

if __name__ == '__main__':
    main()
