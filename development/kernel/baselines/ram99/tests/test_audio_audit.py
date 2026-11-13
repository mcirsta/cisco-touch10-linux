#!/usr/bin/env python3
"""Reject incorrect audio power wiring and unconnected endpoint activation."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import libfdt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_audio import audit_audio
from common import HERE, IMAGE
from dt_layout import Tree, cells


def main():
    candidate = IMAGE / 'board.dtb'
    report = audit_audio(candidate)
    tree = Tree(candidate)
    codec, mcpdm = report['codec_node'], report['mcpdm_node']
    gpio = cells(tree.nodes[codec]['ti,audpwron-gpios'])
    clock = cells(tree.nodes[codec]['clocks'])
    cases = [
        ('wrong power GPIO', codec, 'ti,audpwron-gpios', [gpio[0], 30, 0]),
        ('inverted power GPIO', codec, 'ti,audpwron-gpios', [gpio[0], 31, 1]),
        ('wrong codec IRQ', codec, 'interrupts', [0, 118, 4]),
        ('wrong codec address', codec, 'reg', [0x4a]),
        ('wrong reference clock', codec, 'clocks', [clock[0], 0]),
        ('unreviewed supply control', codec, 'v2v1-supply', [clock[0]]),
        ('unconnected left speaker', '/sound', 'ti,audio-routing', b'Ext Spk\0HFL\0'),
        ('unconnected microphone', '/sound', 'ti,audio-routing', b'MAINMIC\0Main Handset Mic\0'),
        ('nonexistent jack', '/sound', 'ti,jack-detection', b''),
        ('wrong MCLK', '/sound', 'ti,mclk-freq', [38400000]),
        ('wrong McPDM pad', report['mcpdm_pins'], 'pinctrl-single,pins', [0xce, 3]),
        ('wrong codec power pad', report['audio_control_pins'], 'pinctrl-single,pins', [0xe0, 0x103]),
        ('wrong DMA request', mcpdm, 'dmas', [cells(tree.nodes[mcpdm]['dmas'])[0], 64]),
        ('wrong MMIO', mcpdm, 'reg', [4, 0x7f, 0x49032000, 0x7f]),
    ]
    with tempfile.TemporaryDirectory(prefix='audio-negative-', dir=HERE / 'out') as folder:
        path = Path(folder) / 'changed.dtb'
        for name, node, prop, value in cases:
            fdt = libfdt.Fdt(candidate.read_bytes())
            fdt.resize(fdt.totalsize() + 1024)
            data = struct.pack('>' + 'I' * len(value), *value) if isinstance(value, list) else value
            fdt.setprop(fdt.path_offset(node), prop, data)
            fdt.pack()
            path.write_bytes(bytes(fdt.as_bytearray()[:fdt.totalsize()]))
            try:
                audit_audio(path)
            except (AssertionError, KeyError, ValueError):
                continue
            raise AssertionError('Unsafe audio configuration accepted: ' + name)
    result = {'passed': True, 'unsafe_mutations_rejected': [c[0] for c in cases]}
    (HERE / 'out/audio-audit-tests.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'PASS: {len(cases)} unsafe audio power/routing/clock/DMA mutations rejected')


if __name__ == '__main__':
    main()
