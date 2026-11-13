#!/usr/bin/env python3
"""Compare physical wiring and the enabled target set across the bus migration."""
import json
from pathlib import Path

from common import HERE, ROOT, sha
from dt_layout import Tree, cells, parent, strings


def audit_bus(reference, candidate):
    policy = json.loads((HERE / 'configs/bus-layout.json').read_text())
    old, new = Tree(reference), Tree(candidate)
    roots = policy['legacy_to_mainline']

    def remap(path):
        for source in sorted(roots, key=len, reverse=True):
            if path == source or path.startswith(source + '/'):
                return roots[source] + path[len(source):]
        return path

    mapping = {p: remap(p) for p in old.nodes}
    assert new.available('/ocp')
    targets = {p for p in new.nodes if p.rsplit('/', 1)[-1].startswith('target-module@')
               and new.available(p)}
    assert targets == set(policy['allowed_targets']), (
        'Target set changed', sorted(targets - set(policy['allowed_targets'])),
        sorted(set(policy['allowed_targets']) - targets))
    assert all(p.startswith('/ocp/') for p in targets)
    for path in ['/ocp', '/ocp/interconnect@4a000000', '/ocp/interconnect@48000000',
                 '/ocp/interconnect@4a300000', '/ocp/target-module@58000000']:
        assert 'power-domains' not in new.nodes[path], ('RAM power policy changed', path)
    assert not new.available('/cpus/cpu@1')
    assert 'operating-points' not in new.nodes['/cpus/cpu@0']
    timer1 = '/ocp/interconnect@4a300000/segment@10000/target-module@8000'
    assert 'ti,no-reset-on-init' in new.nodes[timer1] and 'ti,no-idle' in new.nodes[timer1]

    def irq(tree, path):
        props = tree.nodes[path]
        if 'interrupts-extended' in props:
            refs = tree.refs(props['interrupts-extended'], '#interrupt-cells')
        elif 'interrupts' in props:
            node = path
            while 'interrupt-parent' not in tree.nodes[node]:
                node = parent(node)
            provider = tree.handles[cells(tree.nodes[node]['interrupt-parent'])[0]]
            count = tree.count(provider, '#interrupt-cells', 0)
            data = cells(props['interrupts'])
            assert count and len(data) % count == 0
            refs = [(provider, tuple(data[i:i + count])) for i in range(0, len(data), count)]
        else:
            return []
        resolved = []
        for node, args in refs:
            # Wugen passes the same interrupt specifier to the GIC.
            if b'ti,omap4-wugen-mpu\0' in tree.nodes[node].get('compatible', b''):
                node = tree.handles[cells(tree.nodes[node]['interrupt-parent'])[0]]
            resolved.append((remap(node) if tree is old else node, args))
        return resolved

    providers = {'clocks': '#clock-cells', 'assigned-clocks': '#clock-cells',
                 'assigned-clock-parents': '#clock-cells', 'dmas': '#dma-cells',
                 'pwms': '#pwm-cells', 'phys': '#phy-cells',
                 'gpios': '#gpio-cells', 'gpio': '#gpio-cells',
                 'thermal-sensors': '#thermal-sensor-cells'}
    single = {'backlight', 'remote-endpoint', 'ti,timers', 'syscon'}
    structural = {'phandle', 'status', 'ranges', 'interrupts', 'interrupts-extended',
                  'interrupt-parent'}
    checked, resources, moved, corrections = 0, 0, [], []
    for path, props in old.nodes.items():
        if not old.available(path) or path.startswith('/__'):
            continue
        target = remap(path)
        assert target in new.nodes and new.available(target), ('Missing active device', path, target)
        after = new.nodes[target]
        if path != target:
            moved.append([path, target])
        if 'reg' in props:
            try:
                before_regs = old.resources(path)
            except ValueError:
                before_regs = []
            if before_regs:
                assert before_regs == new.resources(target), ('MMIO changed', path, target)
                resources += len(before_regs)
        assert irq(old, path) == irq(new, target), ('IRQ changed', path)
        for name, value in props.items():
            if name in structural or name == 'reg' and before_regs:
                continue
            assert name in after, ('Property removed', path, name)
            if path == '/aliases':
                assert remap(strings(value)[0]) == strings(after[name])[0], (path, name)
            elif name == 'compatible' and path == '/pinctrl@4a100040':
                assert strings(after[name]) == ['ti,omap4-padconf', 'pinctrl-single']
            elif name == 'compatible' and path == '/target-module@4a31c000':
                assert strings(after[name]) == ['ti,sysc-omap2', 'ti,sysc']
                corrections.append('Keypad parent uses the upstream OMAP2 SYSC layout')
            elif name == 'gpios' and 'gpio-hog' in props:
                assert value == after[name], (path, name)
            elif name in providers or name.endswith('-gpios'):
                kind = providers.get(name, '#gpio-cells')
                assert old.refs(value, kind, mapping) == new.refs(after[name], kind), (path, name)
            elif (name in single or name.endswith('-supply') or
                  name.startswith('pinctrl-') and name.removeprefix('pinctrl-').isdigit()):
                assert old.refs(value, remap=mapping) == new.refs(after[name]), (path, name)
            else:
                assert value == after[name], ('Hardware property changed', path, name)
            checked += 1
    for path in roots.values():
        assert new.available(path), path
    # No newly enabled board voltage control is permitted during this migration.
    for path, props in new.nodes.items():
        if new.available(path) and any(c in props.get('compatible', b'') for c in
                                      (b'ti,pbias-', b'ti,abb-', b'ti,twl603')):
            raise AssertionError('Unreviewed regulator enabled: ' + path)
    return {'passed': True, 'properties_compared': checked,
            'physical_register_ranges_compared': resources,
            'enabled_upstream_targets': sorted(targets), 'moved_nodes': moved,
            'documented_soc_corrections': corrections,
            'gpio_regulator_pad_pwm_timing_properties_unchanged': True,
            'ram_power_domain_policy_preserved': True,
            'reference_dtb_sha256': sha(reference), 'candidate_dtb_sha256': sha(candidate)}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    result = audit_bus(ROOT / 'development/perrier-ramenv/mainline-ram/board.dtb', args.candidate)
    (HERE / 'out/bus-migration/audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS:', result['properties_compared'], 'properties and',
          result['physical_register_ranges_compared'], 'physical MMIO ranges;',
          len(result['enabled_upstream_targets']), 'upstream targets')
