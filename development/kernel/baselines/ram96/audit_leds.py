#!/usr/bin/env python3
"""Permit only the two stock mute LEDs on top of the qualified ram93 DT."""
import json

from common import HERE, ROOT, sha
from dt_layout import Tree, cells


def audit_leds(candidate):
    reference = ROOT / 'development/perrier-ramenv/display-stop-fix/board.dtb'
    old, new = Tree(reference), Tree(candidate)
    layout = json.loads((HERE / 'configs/bus-layout.json').read_text())['legacy_to_mainline']
    pin = layout['/pinctrl@4a100040'] + '/mute-led-pins'
    gpio4 = layout['/target-module@48059000'] + '/gpio@0'
    added = {'/leds', '/leds/led-0', '/leds/led-1', pin}
    assert set(new.nodes) - set(old.nodes) == added
    assert not set(old.nodes) - set(new.nodes)
    providers = {'clocks': '#clock-cells', 'assigned-clocks': '#clock-cells',
                 'assigned-clock-parents': '#clock-cells', 'dmas': '#dma-cells',
                 'pwms': '#pwm-cells', 'phys': '#phy-cells', 'gpios': '#gpio-cells',
                 'gpio': '#gpio-cells', 'thermal-sensors': '#thermal-sensor-cells',
                 'interrupts-extended': '#interrupt-cells', 'power-domains': '#power-domain-cells'}
    single = {'backlight', 'remote-endpoint', 'ti,timers', 'syscon', 'interrupt-parent'}
    compared = 0
    for node, before in old.nodes.items():
        after = new.nodes[node]
        if node == '/__symbols__':
            assert set(after) - set(before) == {'perrier_mute_led_pins'}
            assert after['perrier_mute_led_pins'] == pin.encode() + b'\0'
            assert all(after[k] == v for k, v in before.items())
            continue
        assert before.keys() == after.keys(), node
        for name, value in before.items():
            compared += 1
            if value == after[name]:
                continue
            if name == 'phandle':
                assert old.handles[cells(value)[0]] == new.handles[cells(after[name])[0]]
            elif name in providers or name.endswith('-gpios'):
                kind = providers.get(name, '#gpio-cells')
                assert old.refs(value, kind) == new.refs(after[name], kind), (node, name)
            elif (name in single or name.endswith('-supply') or
                  name.startswith('pinctrl-') and name[8:].isdigit()):
                assert old.refs(value) == new.refs(after[name]), (node, name)
            else:
                raise AssertionError(('Unrelated DT property changed', node, name))
    root = new.nodes['/leds']
    assert set(root) == {'compatible', 'pinctrl-names', 'pinctrl-0'}
    assert root['compatible'] == b'gpio-leds\0' and root['pinctrl-names'] == b'default\0'
    assert new.refs(root['pinctrl-0']) == [(pin, ())]
    assert set(new.nodes[pin]) == {'pinctrl-single,pins', 'phandle'}
    assert cells(new.nodes[pin]['pinctrl-single,pins']) == [0x110 - 0x40, 0xb, 0x116 - 0x40, 0xb]
    for index, gpio, color in [(0, 26, 1), (1, 23, 2)]:
        led = new.nodes[f'/leds/led-{index}']
        assert set(led) == {'color', 'function', 'gpios', 'default-state'}
        assert cells(led['color']) == [color]
        assert led['function'] == b'micmute\0' and led['default-state'] == b'off\0'
        assert new.refs(led['gpios'], '#gpio-cells') == [(gpio4, (gpio, 0))]
    return {'passed': True, 'reference_dtb_sha256': sha(reference),
            'candidate_dtb_sha256': sha(candidate), 'added_nodes': sorted(added),
            'unchanged_existing_properties': compared, 'stock_gpios': [119, 122],
            'stock_pad_values': [11, 11], 'other_hardware_unchanged': True}
