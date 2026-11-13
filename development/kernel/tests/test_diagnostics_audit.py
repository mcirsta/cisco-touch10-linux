#!/usr/bin/env python3
"""Reject unsafe PMIC/PMU wiring changes and changes to existing peripherals."""
import json
from pathlib import Path
import struct
import sys
import tempfile

import libfdt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_diagnostics import audit_diagnostics
from common import HERE, IMAGE


def main():
    candidate = IMAGE / 'board.dtb'
    report = audit_diagnostics(candidate)
    adc, pmu = report['pmic_adc_node'], report['pmu_node']
    cases = [
        ('wrong PMIC variant', adc, 'compatible', b'ti,twl6030-gpadc\0'),
        ('wrong PMIC interrupt', adc, 'interrupts', [4]),
        ('wrong ADC cell count', adc, '#io-channel-cells', [0]),
        ('invented ADC supply', adc, 'vdd-supply', [1]),
        ('invented ADC GPIO', adc, 'reset-gpios', [1, 1, 0]),
        ('wrong PMU IRQ', pmu, 'interrupts', [0, 53, 4, 0, 55, 4]),
        ('wrong PMU family', pmu, 'compatible', b'arm,cortex-a15-pmu\0'),
        ('unreviewed PMU secure access', pmu, 'secure-reg-access', b''),
        ('CPU1 enabled', '/cpus/cpu@1', 'status', b'okay\0'),
        ('display clock changed', '/sound', 'ti,mclk-freq', [38400000]),
        ('other SoC target enabled', '/ocp/target-module@52000000', 'status', b'okay\0'),
        ('regulator policy changed', '/regulator-backlight-5v', 'regulator-max-microvolt', [6000000]),
    ]
    with tempfile.TemporaryDirectory(prefix='diagnostics-negative-', dir=HERE / 'out') as folder:
        path = Path(folder) / 'changed.dtb'
        for name, node, prop, value in cases:
            fdt = libfdt.Fdt(candidate.read_bytes())
            fdt.resize(fdt.totalsize() + 1024)
            data = struct.pack('>' + 'I' * len(value), *value) if isinstance(value, list) else value
            fdt.setprop(fdt.path_offset(node), prop, data)
            fdt.pack()
            path.write_bytes(bytes(fdt.as_bytearray()[:fdt.totalsize()]))
            try:
                audit_diagnostics(path)
            except (AssertionError, KeyError, ValueError):
                continue
            raise AssertionError('Unsafe diagnostics configuration accepted: ' + name)
    result = {'passed': True, 'unsafe_mutations_rejected': [c[0] for c in cases]}
    (HERE / 'out/diagnostics-audit-tests.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: rejected ' + str(len(cases)) + ' unsafe changes')


if __name__ == '__main__':
    main()
