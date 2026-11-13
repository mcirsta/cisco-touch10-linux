#!/usr/bin/env python3
"""Reject unsafe wiring changes in the real migrated DTB before a live boot."""
import json
from pathlib import Path
import struct
import sys
import tempfile

import libfdt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_bus import audit_bus
from common import BASELINE, HERE, IMAGE
from dt_layout import Tree, cells


def main():
    candidate = IMAGE / 'board.dtb'
    audit_bus(BASELINE / 'board.dtb', candidate)
    tree = Tree(candidate)
    policy = json.loads((HERE / 'configs/bus-layout.json').read_text())
    mapping = policy['legacy_to_mainline']
    gpio5 = mapping['/target-module@4805b000'] + '/gpio@0'
    touch = mapping['/target-module@48072000'] + '/i2c@0/touchscreen@67'
    pins = mapping['/pinctrl@4a100040'] + '/backlight-enable-pin'
    gpio4 = mapping['/target-module@48059000'] + '/gpio@0'
    wdt = mapping['/target-module@4a314000']
    reset = cells(tree.nodes[touch]['reset-gpios'])
    cases = [
        ('wrong GPIO bank', touch, 'reset-gpios',
         [cells(tree.nodes[gpio4]['phandle'])[0], *reset[1:]]),
        ('wrong GPIO offset', touch, 'reset-gpios', [reset[0], 12, reset[2]]),
        ('wrong GPIO polarity', touch, 'reset-gpios', [reset[0], reset[1], 0]),
        ('wrong touch IRQ', touch, 'interrupts', [15, 2]),
        ('wrong pad mux', pins, 'pinctrl-single,pins', [0x154 - 0x40, 4]),
        ('changed voltage', '/regulator-backlight-5v', 'regulator-min-microvolt', [3300000]),
        ('changed panel timing', '/panel/panel-timing', 'hback-porch', [80]),
        ('changed watchdog timeout', wdt + '/wdt@0', 'timeout-sec', [30]),
        ('lost watchdog reset protection', wdt, 'ti,no-reset-on-init', None),
        ('new unused target enabled', '/ocp/target-module@50000000', 'status', b'okay\0'),
    ]
    with tempfile.TemporaryDirectory(prefix='bus-negative-', dir=HERE / 'out') as directory:
        path = Path(directory) / 'modified.dtb'
        for name, node, prop, value in cases:
            fdt = libfdt.Fdt(candidate.read_bytes())
            fdt.resize(fdt.totalsize() + 512)
            offset = fdt.path_offset(node)
            if value is None:
                fdt.delprop(offset, prop)
            else:
                payload = struct.pack('>' + 'I' * len(value), *value) if isinstance(value, list) else value
                fdt.setprop(offset, prop, payload)
            fdt.pack()
            path.write_bytes(bytes(fdt.as_bytearray()[:fdt.totalsize()]))
            try:
                audit_bus(BASELINE / 'board.dtb', path)
            except AssertionError:
                continue
            raise AssertionError('Unsafe change accepted: ' + name)
    report = {'passed': True, 'unchanged_candidate_accepted': True,
              'unsafe_changes_rejected': [case[0] for case in cases]}
    (HERE / 'out/bus-audit-tests.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: real migrated DT accepted; ten unsafe wiring/reset/target changes rejected')


if __name__ == '__main__':
    main()
