#!/usr/bin/env python3
"""Run the real ARM ALSA chain under QEMU; replace only its hardware sink."""
import array
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'development/kernel/out/application-audio/conversion'
RUNTIME = ROOT / 'development/perrier-qt/runtime'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = {'mono': (1, (1,), 1), 'stereo': (2, (1, 1), 1),
             'left': (2, (1, 0), .5), 'right': (2, (0, 1), .5),
             'antiphase': (2, (1, -1), 0), 'full-scale': (2, (1, 1), 1)}
    records = {}
    for name, (channels, scales, expected) in cases.items():
        amplitude = 32767 if name == 'full-scale' else 12000
        signal = [amplitude if name == 'full-scale' else
                  int(amplitude * math.sin(2 * math.pi * 1000 * i / 48000)) for i in range(4800)]
        source = OUT / (name + '-input.raw')
        source.write_bytes(b''.join(struct.pack('<h', sample * scale)
                                   for sample in signal for scale in scales))
        sink = OUT / (name + '.raw')
        config = OUT / (name + '.conf')
        # Route/plug/default are production bytes. Only perrier_hw is replaced.
        config.write_text((HERE / 'asound.conf').read_text() + '\n'
            'pcm.!perrier_hw { type file slave.pcm { type null } '
            'file "' + str(sink) + '" format "raw" }\n')
        args = ['qemu-arm', '-cpu', 'cortex-a9', str(RUNTIME / 'lib/ld-musl-armhf.so.1'),
                '--library-path', str(RUNTIME / 'lib'),
                str(HERE / 'app-build/alsa-utils/aplay/aplay'), '-D', 'default', '-t', 'raw',
                '-f', 'S16_LE', '-c', str(channels), '-r', '48000', '-F', '10000',
                '-B', '40000', '-v', str(source)]
        result = subprocess.run(args, env=dict(os.environ, ALSA_CONFIG_PATH=str(config)),
                                capture_output=True, timeout=15)
        (OUT / (name + '.log')).write_bytes(result.stdout + result.stderr)
        assert result.returncode == 0, name
        samples = array.array('i', sink.read_bytes())
        assert samples.itemsize == 4 and len(samples) % 4 == 0
        assert all(value == 0 for slot in range(3) for value in samples[slot::4]), name
        hfr = samples[3::4]
        # aplay may append a period of silence; the signal portion doubles.
        assert 9600 <= len(hfr) <= 10560, (name, len(hfr))
        peak = max(abs(v) for v in hfr[200:9000])
        ratio = peak / (amplitude * 65536)
        assert abs(ratio - expected) < .002, (name, ratio, expected)
        assert peak <= 2147483647
        records[name] = {'input_channels': channels, 'input_rate': 48000, 'input_format': 'S16_LE',
                         'output_frames': len(hfr), 'output_rate': 96000,
                         'output_channels': 4, 'output_format': 'S32_LE',
                         'silent_slots': [0, 1, 2], 'hfr_peak_ratio': ratio,
                         'expected_ratio': expected, 'capture_sha256': sha(sink),
                         'input_sha256': sha(source), 'config_sha256': sha(config)}
    record = {'passed': True, 'runner': 'qemu-arm cortex-a9', 'only_hardware_sink_replaced': True,
              'asound_conf_sha256': sha(HERE / 'asound.conf'),
              'libasound_sha256': sha(RUNTIME / 'lib/libasound.so.2'),
              'aplay_sha256': sha(HERE / 'app-build/alsa-utils/aplay/aplay'), 'cases': records}
    (OUT.parent / 'conversion-checks.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
