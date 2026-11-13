#!/usr/bin/env python3
"""Permit only the stock Perrier audio wiring on top of qualified ram96."""
from common import ROOT, sha
from dt_layout import Tree, cells
from audit_rtc_gpio import audit_rtc_gpio


def audit_audio(candidate):
    try:
        return _audit_audio(candidate)
    except (KeyError, ValueError, IndexError) as exc:
        raise AssertionError('Malformed audio DT reference: ' + str(exc)) from exc


def _audit_audio(candidate):
    reference = ROOT / 'development/perrier-ramenv/rtc-gpio/board.dtb'
    inherited = audit_rtc_gpio(reference)
    old, new = Tree(reference), Tree(candidate)
    pmic = inherited['pmic_node']
    codec = pmic.rsplit('/', 1)[0] + '/audio-codec@4b'
    pinmux = next(p.rsplit('/', 1)[0] for p in old.nodes if p.endswith('/mute-led-pins'))
    control, pads = pinmux + '/audio-control-pins', pinmux + '/mcpdm-pins'
    abe = '/ocp/interconnect@40100000'
    module = abe + '/segment@0/target-module@32000'
    mcpdm = module + '/mcpdm@0'
    gpio4 = next(p for p in old.nodes if p.endswith('/target-module@59000/gpio@0'))
    assert set(new.nodes) - set(old.nodes) == {'/sound', codec, control, pads}
    assert not set(old.nodes) - set(new.nodes)

    def u(*values):
        return b''.join(v.to_bytes(4, 'big') for v in values)

    providers = {'clocks': '#clock-cells', 'assigned-clocks': '#clock-cells',
                 'assigned-clock-parents': '#clock-cells', 'dmas': '#dma-cells',
                 'pwms': '#pwm-cells', 'phys': '#phy-cells', 'gpios': '#gpio-cells',
                 'gpio': '#gpio-cells', 'thermal-sensors': '#thermal-sensor-cells',
                 'power-domains': '#power-domain-cells', 'resets': '#reset-cells',
                 'iommus': '#iommu-cells', 'mboxes': '#mbox-cells'}
    single = {'backlight', 'remote-endpoint', 'ti,timers', 'syscon',
              'ti,mcpdm', 'ti,twl6040', 'interrupt-parent', 'sram'}

    def normalize(tree, props):
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
                # OMAP mailbox arguments are phandles to channel children.
                value = [(node, tuple(tree.handles[arg] for arg in args))
                         for node, args in tree.refs(value, '#mbox-cells')]
            elif name in providers or name.endswith('-gpios'):
                value = tree.refs(value, providers.get(name, '#gpio-cells'))
            elif name in single or name.endswith('-supply') or (
                    name.startswith('pinctrl-') and name[8:].isdigit()):
                value = tree.refs(value)
            result[name] = value
        return result

    for path, before in old.nodes.items():
        expected = normalize(old, before)
        if path == abe:
            expected['status'] = b'okay\0'
            del expected['power-domains']
        elif path.startswith(abe + '/') and path.rsplit('/', 1)[-1].startswith('target-module@'):
            expected['status'] = b'disabled\0'
            if path == module:
                expected.update({'status': b'okay\0', 'pinctrl-names': b'default\0',
                                 'pinctrl-0': [(pads, ())]})
        elif path == mcpdm:
            expected.update({'clocks': [(codec, ())], 'clock-names': b'pdmclk\0'})
        assert normalize(new, new.nodes[path]) == expected, ('Unreviewed DT change', path)

    assert normalize(new, new.nodes['/sound']) == {
        'compatible': b'ti,abe-twl6040\0', 'ti,model': b'Cisco Touch 10 Perrier\0',
        'ti,mclk-freq': u(19200000), 'ti,mcpdm': [(mcpdm, ())],
        'ti,twl6040': [(codec, ())],
        'ti,audio-routing': b'Ext Spk\0HFR\0Earphone Spk\0EP\0'}
    assert normalize(new, new.nodes[codec]) == {
        'compatible': b'ti,twl6040\0', 'reg': u(0x4b), '#clock-cells': u(0),
        'pinctrl-names': b'default\0', 'pinctrl-0': [(control, ())],
        'interrupts': u(0, 119, 4), 'ti,audpwron-gpios': [(gpio4, (31, 0))],
        'clocks': [(pmic, (1,))], 'clock-names': b'clk32k\0'}
    assert normalize(new, new.nodes[control]) == {
        'pinctrl-single,pins': u(0xe0, 3, 0x160, 0xc118)}
    assert normalize(new, new.nodes[pads]) == {
        'pinctrl-single,pins': u(0xc6, 0x100, 0xc8, 0x108, 0xca, 0x118,
                               0xcc, 0x108, 0xce, 0x108)}
    assert new.resources(mcpdm) == [(0x40132000, 0x7f), (0x49032000, 0x7f)]
    assert cells(new.nodes[mcpdm]['interrupts']) == [0, 112, 4]
    assert new.refs(new.nodes[mcpdm]['dmas'], '#dma-cells') == [
        (next(p for p in new.nodes if p.endswith('/dma-controller@0')), (65,)),
        (next(p for p in new.nodes if p.endswith('/dma-controller@0')), (66,))]
    return dict(inherited, passed=True, codec_node=codec, mcpdm_node=mcpdm,
                audio_control_pins=control, mcpdm_pins=pads,
                reference_dtb_sha256=sha(reference), candidate_dtb_sha256=sha(candidate),
                display_and_non_audio_wiring_preserved=True,
                only_right_handsfree_and_earpiece_routed=True,
                physical_supplies_unmanaged_as_stock=True,
                clock_consumers_absent=False, audio_clock_consumers_exact=True)
