#!/usr/bin/env python3
"""Verify and unpack the Touch 10's Qt 6.12 and ARMv7 toolchain archives."""
import hashlib
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
SOURCES = HERE / 'sources'
ARCHIVES = {
    'qtbase-everywhere-src-6.12.0.tar.xz':
        'a951bd163c7b80fc6b8c88d7668fb56abf91c152373e13c10666763238131307',
    'qtdeclarative-everywhere-src-6.12.0.tar.xz':
        '311f3a2603e1973bb59baef9dfa740a376de713157d4782ee043681e889c9260',
    'armv7-eabihf--musl--stable-2026.08-1.tar.xz':
        '9147bafae4aa272321a3c6440d04d83b7e23411b2d344f875541d84c4444ba9b',
}

def digest(path):
    with path.open('rb') as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def main():
    SOURCES.mkdir(exist_ok=True)
    for name, expected in ARCHIVES.items():
        path = HERE / 'downloads' / name
        assert digest(path) == expected, path
        destination = SOURCES / name.removesuffix('.tar.xz')
        if not destination.exists():
            subprocess.run(['tar', '-xJf', path, '-C', SOURCES], check=True)
        assert destination.is_dir(), destination
        print('Prepared', destination, flush=True)
    base = SOURCES / 'qtbase-everywhere-src-6.12.0'
    patch = HERE / 'patches/qtbase-6.12.0-futex-time64.patch'
    assert digest(patch) == '2dc5ada725dfad23f2cb53373d5dde38e3e0b7c6c7981cbc324880a0f27328d2'
    forward = subprocess.run(['patch', '--batch', '--forward', '--dry-run',
                              '-d', base, '-p1', '-i', patch],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if forward.returncode == 0:
        subprocess.run(['patch', '--batch', '--forward', '-d', base, '-p1',
                        '-i', patch], check=True)
    else:
        reverse = subprocess.run(['patch', '--batch', '--reverse', '--dry-run',
                                  '-d', base, '-p1', '-i', patch],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert reverse.returncode == 0, 'unexpected Qt source contents'
    print('Qt futex patch verified', flush=True)

if __name__ == '__main__':
    main()
