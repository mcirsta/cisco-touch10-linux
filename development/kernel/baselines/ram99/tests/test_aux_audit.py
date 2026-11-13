#!/usr/bin/env python3
"""Reject output-driving, RTC IRQ and clock-policy mistakes in the actual DTB."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import libfdt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_audio import audit_audio as audit_rtc_gpio
from common import HERE, IMAGE


def main():
    candidate = IMAGE / 'board.dtb'
    report = audit_rtc_gpio(candidate)
    rtc, gpio, pmic = (report[k] for k in ('rtc_node', 'gpio_node', 'pmic_node'))
    cases = [
        ('wrong RTC IRQ', rtc, 'interrupts', [12]),
        ('wrong RTC type', rtc, 'compatible', b'ti,pcf8563\0'),
        ('GPIO shutdown release', gpio, 'retain-state-shutdown', None),
        ('GPIO output initialization', gpio, 'lines-initial-states', [0xaa]),
        ('unmapped GPIO reset', gpio, 'reset-gpios', [1, 1, 0]),
        ('wrong GPIO cell count', gpio, '#gpio-cells', [3]),
        ('wrong GPIO address', gpio, 'reg', [0x25]),
        ('wrong clock provider', pmic, '#clock-cells', [2]),
        ('PMIC clock reinit', pmic, 'clock-names', b'fck\0'),
        ('display timing altered', '/panel/panel-timing', 'hactive', [1279]),
        ('rail voltage altered', '/regulator-touch-3v3', 'regulator-min-microvolt', [1800000]),
        ('CPU1 enabled', '/cpus/cpu@1', 'status', b'okay\0'),
    ]
    with tempfile.TemporaryDirectory(prefix='aux-negative-', dir=HERE / 'out') as folder:
        target = Path(folder) / 'changed.dtb'
        for label, node, prop, value in cases:
            fdt = libfdt.Fdt(candidate.read_bytes())
            fdt.resize(fdt.totalsize() + 1024)
            offset = fdt.path_offset(node)
            if value is None:
                fdt.delprop(offset, prop)
            else:
                data = struct.pack('>' + 'I' * len(value), *value) if isinstance(value, list) else value
                fdt.setprop(offset, prop, data)
            fdt.pack()
            target.write_bytes(bytes(fdt.as_bytearray()[:fdt.totalsize()]))
            try:
                audit_rtc_gpio(target)
            except AssertionError:
                continue
            raise AssertionError('Unsafe DT accepted: ' + label)
    result = {'passed': True, 'unsafe_mutations_rejected': [c[0] for c in cases]}
    (HERE / 'out/aux-audit-tests.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: twelve unsafe RTC/GPIO/clock/old-hardware mutations rejected')


if __name__ == '__main__':
    main()
