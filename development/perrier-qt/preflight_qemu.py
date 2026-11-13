#!/usr/bin/env python3
"""Check the staged ARM Qt app on a Cortex-A9 model without a device reboot."""
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get('PERRIER_QT_RUNTIME', HERE / 'runtime')).resolve()
SYSROOT = Path(os.environ.get('PERRIER_QEMU_SYSROOT',
    HERE / 'sources/armv7-eabihf--musl--stable-2026.08-1/arm-buildroot-linux-musleabihf/sysroot')).resolve()

def main():
    env = dict(os.environ,
               QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
               QSG_RENDER_LOOP='basic', QML_DISABLE_DISK_CACHE='1',
               QT_PLUGIN_PATH=str(RUNTIME / 'plugins'),
               QML_IMPORT_PATH=str(RUNTIME / 'qml'),
               QML2_IMPORT_PATH=str(RUNTIME / 'qml'),
               QT_QPA_FONTDIR=str(RUNTIME / 'lib/fonts'),
               LD_LIBRARY_PATH=str(RUNTIME / 'lib'), XDG_RUNTIME_DIR='/tmp',
               PERRIER_QT_DURATION_MS='1500', PERRIER_QT_TEST_NO_TOUCH='1')
    args = ['qemu-arm', '-cpu', 'cortex-a9', '-L', str(SYSROOT),
            str(RUNTIME / 'lib/ld-musl-armhf.so.1'), '--library-path',
            str(RUNTIME / 'lib'), str(RUNTIME / 'bin/perrier-touch-grid')]
    try:
        result = subprocess.run(args, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=8)
        output = result.stdout
        status = f'exit={result.returncode}'
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or b''
        status = 'timed out after 8 s'
        result = None
    if (result is None or result.returncode != 0 or
            b'PERRIER_QT_READY touch-grid 1280x800' not in output or
            b'PERRIER_QT_EXIT status=0' not in output):
        raise SystemExit(f'QEMU Qt preflight failed ({status}):\n' +
                         output.decode(errors='replace'))
    print('QEMU Cortex-A9 Qt start and clean exit passed; ' + status)

if __name__ == '__main__':
    main()
