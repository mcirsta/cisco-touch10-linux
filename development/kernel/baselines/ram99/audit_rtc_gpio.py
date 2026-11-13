#!/usr/bin/env python3
"""Allow only RTC, an as-is GPIO provider and two unused PMIC clock providers."""
from common import ROOT, sha
from dt_layout import Tree, cells
from audit_peripherals import audit_peripherals


def audit_rtc_gpio(candidate):
    reference = ROOT / 'development/perrier-ramenv/peripherals/board.dtb'
    parent = audit_peripherals(reference)
    old, new = Tree(reference), Tree(candidate)
    pmic = parent['pmic_node']
    bus4 = next(p.rsplit('/', 1)[0] for p in old.nodes if p.endswith('/eeprom@54'))
    gpio = bus4 + '/gpio@24'
    rtc = pmic + '/rtc'
    assert set(new.nodes) - set(old.nodes) == {rtc, gpio}
    assert not set(old.nodes) - set(new.nodes)
    count = 0
    for node, before in old.nodes.items():
        after = dict(new.nodes[node])
        if node == pmic:
            assert cells(after.pop('#clock-cells')) == [1]
        assert after == before, ('Unrelated DT properties changed', node)
        count += len(before)
    def u(*items):
        return b''.join(n.to_bytes(4, 'big') for n in items)
    assert new.nodes[rtc] == {'compatible': b'ti,twl4030-rtc\0', 'interrupts': u(11)}
    assert new.nodes[gpio] == {'compatible': b'nxp,pcf8574\0', 'reg': u(0x24),
                               'gpio-controller': b'', '#gpio-cells': u(2),
                               'retain-state-shutdown': b''}
    return {'passed': True, 'pmic_node': pmic, 'rtc_node': rtc, 'gpio_node': gpio,
            'reference_dtb_sha256': sha(reference), 'candidate_dtb_sha256': sha(candidate),
            'existing_properties_identical': count, 'display_unchanged': True,
            'gpio_consumers_reset_irq_and_initial_output_changes_absent': True,
            'gpio_state_retained_at_shutdown': True, 'clock_consumers_absent': True}
