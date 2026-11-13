#!/usr/bin/env python3
"""Reject unsafe mutations to the combined peripheral DT before live testing."""
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
    report = audit_rtc_gpio(candidate)
    tree = Tree(candidate)
    pmic = report['pmic_node']
    sensor = next(p for p in tree.nodes if p.endswith('/power-sensor@40'))
    eeprom = next(p for p in tree.nodes if p.endswith('/eeprom@54'))
    pins = next(p for p in tree.nodes if p.endswith('/monitor-i2c-pins'))
    pwm = cells(tree.nodes['/led-controller/led-0']['pwms'])
    cases = [
        ('EEPROM writable', eeprom, 'read-only', None),
        ('EEPROM wrong address', eeprom, 'reg', [0x50]),
        ('incorrect shunt', sensor + '/input@0', 'shunt-resistor-micro-ohms', [1000]),
        ('summation enabled', sensor + '/input@1', 'ti,summation-disable', None),
        ('power controller enabled', pmic, 'system-power-controller', b''),
        ('PMIC clock initialization', pmic, 'clock-names', b'fck\0'),
        ('unused PWM channel selected', '/led-controller/led-0', 'pwms', [pwm[0], 0, pwm[2]]),
        ('wrong PWM period', '/led-controller/led-0', 'pwms', [pwm[0], 1, 50000]),
        ('white LED on at boot', '/led-controller/led-0', 'default-state', b'on\0'),
        ('changed bus pullup', pins, 'pinctrl-single,pins', [0x12e - 0x40, 0x118, 0x130 - 0x40, 0x118]),
        ('changed display timing', '/panel/panel-timing', 'hfront-porch', [79]),
        ('changed supply voltage', '/regulator-panel-3v3', 'regulator-min-microvolt', [1800000]),
        ('CPU1 accidentally enabled', '/cpus/cpu@1', 'status', b'okay\0'),
    ]
    with tempfile.TemporaryDirectory(prefix='peripheral-negative-', dir=HERE / 'out') as folder:
        path = Path(folder) / 'changed.dtb'
        for label, node, prop, value in cases:
            fdt = libfdt.Fdt(candidate.read_bytes())
            fdt.resize(fdt.totalsize() + 1024)
            offset = fdt.path_offset(node)
            if value is None:
                fdt.delprop(offset, prop)
            else:
                payload = struct.pack('>' + 'I' * len(value), *value) if isinstance(value, list) else value
                fdt.setprop(offset, prop, payload)
            fdt.pack()
            path.write_bytes(bytes(fdt.as_bytearray()[:fdt.totalsize()]))
            try:
                audit_rtc_gpio(path)
            except AssertionError:
                continue
            raise AssertionError('Unsafe mutation accepted: ' + label)
    result = {'passed': True, 'unsafe_mutations_rejected': [c[0] for c in cases]}
    (HERE / 'out/peripheral-audit-tests.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: thirteen unsafe peripheral / existing-hardware mutations rejected')


if __name__ == '__main__':
    main()
