#!/usr/bin/env python3
"""Allow only the reviewed PMIC PWM, EEPROM and monitor DT additions to ram94."""
import json

from common import HERE, ROOT, sha
from dt_layout import Tree, cells


def audit_peripherals(candidate):
    reference = ROOT / 'development/perrier-ramenv/native-leds/board.dtb'
    old, new = Tree(reference), Tree(candidate)
    def controller(address):
        matches = [p for p in old.nodes if p.endswith('/i2c@0') and old.resources(p)[0][0] == address]
        assert len(matches) == 1
        return matches[0]
    i1, i4 = controller(0x48070000), controller(0x48350000)
    pmx = json.loads((HERE / 'configs/bus-layout.json').read_text())['legacy_to_mainline']['/pinctrl@4a100040']
    pmic, pwm = i1 + '/pmic@48', i1 + '/pmic@48/pwm'
    pin1, pin4 = pmx + '/pmic-i2c-pins', pmx + '/monitor-i2c-pins'
    added = {'/led-controller', '/led-controller/led-0', pmic, pwm, pin1, pin4, i4 + '/eeprom@54'}
    for address in ('40', '41'):
        sensor = i4 + '/power-sensor@' + address
        added.add(sensor)
        added.update(sensor + '/input@' + str(i) for i in range(3))
    assert set(new.nodes) - set(old.nodes) == added
    assert not set(old.nodes) - set(new.nodes)
    changes = {('/aliases', 'i2c0'): i1.encode() + b'\0', ('/aliases', 'i2c3'): i4.encode() + b'\0',
               (i1.rsplit('/', 1)[0], 'status'): None,
               (i4.rsplit('/', 2)[0], 'status'): None}
    for node, pin in ((i1, pin1), (i4, pin4)):
        changes[(node, 'status')] = b'okay\0'
        changes[(node, 'clock-frequency')] = (400000).to_bytes(4, 'big')
        changes[(node, 'pinctrl-names')] = b'default\0'
        changes[(node, 'pinctrl-0')] = ('ref', pin)
    providers = {'clocks': '#clock-cells', 'assigned-clocks': '#clock-cells',
                 'assigned-clock-parents': '#clock-cells', 'dmas': '#dma-cells',
                 'pwms': '#pwm-cells', 'phys': '#phy-cells', 'gpios': '#gpio-cells',
                 'gpio': '#gpio-cells', 'thermal-sensors': '#thermal-sensor-cells',
                 'interrupts-extended': '#interrupt-cells', 'power-domains': '#power-domain-cells',
                 'resets': '#reset-cells', 'iommus': '#iommu-cells', 'mboxes': '#mbox-cells'}
    single = {'backlight', 'remote-endpoint', 'ti,timers', 'syscon', 'interrupt-parent', 'sram'}
    count = 0
    for node, before in old.nodes.items():
        after = new.nodes[node]
        for name in before.keys() | after.keys():
            a, b = before.get(name), after.get(name)
            if (node, name) in changes:
                expected = changes[(node, name)]
                if isinstance(expected, tuple):
                    assert new.refs(b) == [(expected[1], ())]
                else:
                    assert b == expected, (node, name)
                continue
            assert a is not None and b is not None, ('Unreviewed property', node, name)
            count += 1
            if a == b:
                continue
            if name == 'phandle':
                assert old.handles[cells(a)[0]] == new.handles[cells(b)[0]]
            elif name == 'ti,bootreg':
                assert old.refs(a[:4]) == new.refs(b[:4]) and a[4:] == b[4:], (node, name)
            elif name == 'mboxes':
                # OMAP mailbox arguments are themselves sub-mailbox phandles.
                assert len(a) == len(b) == 8 and old.refs(a) == new.refs(b), (node, name)
            elif name in providers or name.endswith('-gpios'):
                kind = providers.get(name, '#gpio-cells')
                assert old.refs(a, kind) == new.refs(b, kind), (node, name)
            elif name in single or name.endswith('-supply') or name.startswith('pinctrl-') and name[8:].isdigit():
                assert old.refs(a) == new.refs(b), (node, name)
            else:
                raise AssertionError(('Existing hardware changed', node, name))
    def exact(node, expected):
        actual = {k: v for k, v in new.nodes[node].items() if k != 'phandle'}
        assert actual == expected, (node, actual, expected)
    def u(*v):
        return b''.join(n.to_bytes(4, 'big') for n in v)
    exact(pin1, {'pinctrl-single,pins': u(0x122 - 0x40, 0x118, 0x124 - 0x40, 0x118)})
    exact(pin4, {'pinctrl-single,pins': u(0x12e - 0x40, 0x100, 0x130 - 0x40, 0x100)})
    exact(pmic, {'compatible': b'ti,twl6032\0', 'reg': u(0x48), 'interrupts': u(0, 7, 4),
                 'interrupt-controller': b'', '#interrupt-cells': u(1), '#address-cells': u(0)})
    exact(pwm, {'compatible': b'ti,twl6030-pwm\0', '#pwm-cells': u(2)})
    exact('/led-controller', {'compatible': b'pwm-leds\0'})
    led = dict(new.nodes['/led-controller/led-0'])
    assert new.refs(led.pop('pwms'), '#pwm-cells') == [(pwm, (1, 3906250))]
    assert led == {'color': u(0), 'function': b'status\0', 'max-brightness': u(255), 'default-state': b'off\0'}
    exact(i4 + '/eeprom@54', {'compatible': b'atmel,24c02\0', 'reg': u(0x54), 'read-only': b''})
    for address in (0x40, 0x41):
        sensor = i4 + f'/power-sensor@{address:x}'
        exact(sensor, {'compatible': b'ti,ina3221\0', 'reg': u(address), '#address-cells': u(1), '#size-cells': u(0)})
        for channel in range(3):
            exact(sensor + f'/input@{channel}', {'reg': u(channel), 'shunt-resistor-micro-ohms': u(10000), 'ti,summation-disable': b''})
    assert new.available(i1) and new.available(i4)
    return {'passed': True, 'pmic_node': pmic, 'added_nodes': sorted(added),
            'existing_properties_preserved': count, 'reference_dtb_sha256': sha(reference),
            'candidate_dtb_sha256': sha(candidate), 'display_unchanged': True,
            'no_regulator_or_power_controller_children': True, 'eeprom_read_only': True}
