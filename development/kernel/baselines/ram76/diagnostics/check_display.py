#!/usr/bin/env python3
"""Capture RAM display state and repeat the established blank/Qt cycle."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_ram as ram

HELPER = ROOT / 'development/kernel/out/display-reduction/tc358765-read'
HELPER_SHA = '9d25e65d0d1e42dd6a50397ed769f3ba02255054808381a0ccc9f1e816c85630'
SNAPSHOT = '''set -eu
uname -r
cat /proc/uptime
cat /run/guard.json
/tmp/tc358765-read
cat /sys/kernel/debug/omapdss/dsi1_clks
cat /sys/kernel/debug/omapdss/dsi1_regs
cat /sys/kernel/debug/omapdss/dispc
cat /sys/kernel/debug/omapdss/dss
cat /sys/kernel/debug/dri/0/state
cat /sys/class/backlight/backlight/brightness
cat /sys/class/backlight/backlight/actual_brightness
cat /sys/class/backlight/backlight/max_brightness
cat /tmp/qt-active.log
dmesg
'''


def command(script, path, timeout=25):
    result = ram.remote(script, timeout=timeout)
    path.write_text(result.stdout + result.stderr)
    result.check_returncode()


def png(raw):
    if len(raw) != 1280 * 800 * 4:
        raise ValueError('Unexpected framebuffer length')
    rgb = bytearray(1280 * 800 * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = raw[2::4], raw[1::4], raw[0::4]
    rows = b''.join(b'\0' + rgb[y * 3840:(y + 1) * 3840] for y in range(800))
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', 1280, 800, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--cycles', type=int, choices=range(4), default=0)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.label):
        parser.error('Use a plain filename label')
    record = json.loads(ram.CURRENT.read_text())
    if record['status'] != 'interactive':
        raise RuntimeError('No interactive RAM session')
    ram.ram_state(record['ram']['kernel'])
    directory = Path(record['directory'])
    if hashlib.sha256(HELPER.read_bytes()).hexdigest() != HELPER_SHA:
        raise RuntimeError('The reviewed read-only bridge helper changed')
    ram.push_file(HELPER, '/tmp/tc358765-read')
    command('chmod 700 /tmp/tc358765-read\n' + SNAPSHOT,
            directory / (args.label + '-before.log'))
    for index in range(1, args.cycles + 1):
        command('''set -eu
echo 4 > /sys/class/graphics/fb0/blank
sleep 2
echo 0 > /sys/class/graphics/fb0/blank
sleep 3
''' + SNAPSHOT, directory / f'{args.label}-cycle-{index}.log')
        source = ROOT / 'development/perrier-qt/build-arm-a9-local/perrier-touch-grid'
        ram.restart_qt(source, False, 0)
    command(SNAPSHOT, directory / (args.label + '-after.log'))
    result = ram.remote('dd if=/dev/fb0 bs=4096 count=1000', binary=True)
    result.check_returncode()
    screenshot = directory / (args.label + '-framebuffer.png')
    screenshot.write_bytes(png(result.stdout))
    print(json.dumps({'kernel': record['ram']['kernel'], 'cycles': args.cycles,
                      'directory': str(directory), 'screenshot': str(screenshot)}, indent=2))


if __name__ == '__main__':
    main()
