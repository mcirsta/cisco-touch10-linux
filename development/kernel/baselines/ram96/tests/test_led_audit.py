#!/usr/bin/env python3
"""Reject hazardous GPIO, polarity, startup and unrelated board changes."""
import json
from pathlib import Path
import struct
import sys
import tempfile

import libfdt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_rtc_gpio import audit_rtc_gpio
from common import HERE, IMAGE
from dt_layout import Tree, cells


def main():
    candidate = IMAGE / 'board.dtb'
    audit_rtc_gpio(candidate)
    tree = Tree(candidate)
    gpios = cells(tree.nodes['/leds/led-0']['gpios'])
    layout = json.loads((HERE / 'configs/bus-layout.json').read_text())['legacy_to_mainline']
    pin = layout['/pinctrl@4a100040'] + '/mute-led-pins'
    gpio5 = layout['/target-module@4805b000'] + '/gpio@0'
    cases = [
        ('wrong GPIO bank', '/leds/led-0', 'gpios',
         [cells(tree.nodes[gpio5]['phandle'])[0], *gpios[1:]]),
        ('wrong GPIO offset', '/leds/led-0', 'gpios', [gpios[0], 24, 0]),
        ('inverted LED polarity', '/leds/led-0', 'gpios', [gpios[0], 26, 1]),
        ('LED enabled at startup', '/leds/led-0', 'default-state', b'on\0'),
        ('unreviewed LED trigger', '/leds/led-1', 'linux,default-trigger', b'heartbeat\0'),
        ('wrong LED pad', pin, 'pinctrl-single,pins', [0x112 - 0x40, 11, 0x116 - 0x40, 11]),
        ('changed LED pull', pin, 'pinctrl-single,pins', [0x110 - 0x40, 3, 0x116 - 0x40, 11]),
        ('changed existing rail', '/regulator-touch-3v3', 'regulator-min-microvolt', [1800000]),
        ('new existing-device property', '/panel', 'unreviewed-property', [1]),
    ]
    with tempfile.TemporaryDirectory(prefix='led-negative-', dir=HERE / 'out') as directory:
        path = Path(directory) / 'modified.dtb'
        for name, node, prop, value in cases:
            fdt = libfdt.Fdt(candidate.read_bytes())
            fdt.resize(fdt.totalsize() + 512)
            payload = struct.pack('>' + 'I' * len(value), *value) if isinstance(value, list) else value
            fdt.setprop(fdt.path_offset(node), prop, payload)
            fdt.pack()
            path.write_bytes(bytes(fdt.as_bytearray()[:fdt.totalsize()]))
            try:
                audit_rtc_gpio(path)
            except AssertionError:
                continue
            raise AssertionError('Unsafe change accepted: ' + name)
    report = {'passed': True, 'unsafe_changes_rejected': [c[0] for c in cases]}
    (HERE / 'out/led-audit-tests.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: LED DT accepted; nine unsafe LED/board mutations rejected')


if __name__ == '__main__':
    main()
