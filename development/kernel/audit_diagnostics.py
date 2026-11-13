#!/usr/bin/env python3
"""Permit only the PMIC ADC child and upstream OMAP4460 PMU target."""
import json

from common import HERE, ROOT, sha
from audit_audio import audit_audio
from dt_layout import Tree, cells


def normalize(tree, props):
    providers = {'clocks': '#clock-cells', 'assigned-clocks': '#clock-cells',
                 'assigned-clock-parents': '#clock-cells', 'dmas': '#dma-cells',
                 'pwms': '#pwm-cells', 'phys': '#phy-cells', 'gpios': '#gpio-cells',
                 'gpio': '#gpio-cells', 'thermal-sensors': '#thermal-sensor-cells',
                 'power-domains': '#power-domain-cells', 'resets': '#reset-cells',
                 'iommus': '#iommu-cells', 'mboxes': '#mbox-cells'}
    single = {'backlight', 'remote-endpoint', 'ti,timers', 'syscon', 'ti,mcpdm',
              'ti,twl6040', 'interrupt-parent', 'sram', 'interrupt-affinity'}
    result = {}
    for name, value in props.items():
        if name == 'phandle':
            continue
        if name == 'gpios' and 'gpio-hog' in props:
            pass
        elif name == 'ti,bootreg':
            data = cells(value)
            value = [(tree.handles[data[0]], tuple(data[1:]))]
        elif name == 'mboxes':
            value = [(node, tuple(tree.handles[arg] for arg in args))
                     for node, args in tree.refs(value, '#mbox-cells')]
        elif name in providers or name.endswith('-gpios'):
            value = tree.refs(value, providers.get(name, '#gpio-cells'))
        elif name in single or name.endswith('-supply') or (
                name.startswith('pinctrl-') and name[8:].isdigit()):
            value = tree.refs(value)
        result[name] = value
    return result


def audit_diagnostics(candidate):
    policy = json.loads((HERE / 'configs/diagnostics-layout.json').read_text())
    reference = ROOT / 'development/perrier-ramenv' / policy['reference_profile'] / 'board.dtb'
    inherited = audit_audio(reference)
    old, new = Tree(reference), Tree(candidate)
    adc = inherited['pmic_node'] + '/gpadc'
    target = policy['pmu_target']
    pmu = target + '/pmu'
    assert set(new.nodes) - set(old.nodes) == {adc}
    assert not set(old.nodes) - set(new.nodes)
    for path, props in old.nodes.items():
        expected = normalize(old, props)
        if path == target:
            expected['status'] = b'okay\0'
            expected.pop('power-domains')
            expected['ti,no-idle-on-init'] = b''
        assert normalize(new, new.nodes[path]) == expected, ('Unreviewed DT change', path)
    assert normalize(new, new.nodes[adc]) == {
        'compatible': policy['adc_compatible'].encode() + b'\0',
        'interrupts': policy['adc_irq'].to_bytes(4, 'big'),
        '#io-channel-cells': (1).to_bytes(4, 'big')}
    assert new.available(pmu)
    assert new.nodes[pmu]['compatible'] == policy['pmu_compatible'].encode() + b'\0'
    assert cells(new.nodes[pmu]['interrupts']) == policy['pmu_irqs']
    before = {p for p in old.nodes if p.rsplit('/', 1)[-1].startswith('target-module@') and old.available(p)}
    after = {p for p in new.nodes if p.rsplit('/', 1)[-1].startswith('target-module@') and new.available(p)}
    assert after == before | {target}
    return dict(inherited, passed=True, reference_dtb_sha256=sha(reference),
                candidate_dtb_sha256=sha(candidate), pmic_adc_node=adc, pmu_node=pmu,
                only_added_target=target, inherited_properties_preserved=True,
                display_audio_gpio_regulator_properties_preserved=True,
                pmic_regulators_still_unmanaged=True)
