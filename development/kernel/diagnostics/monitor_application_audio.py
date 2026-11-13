#!/usr/bin/env python3
"""Bounded read-only Qt/mixer/PCM observation during the owner's audio test."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_ram as ram


def main():
    current = json.loads(ram.CURRENT.read_text())
    assert current['profile'] == 'application-audio' and current['status'] == 'interactive'
    run = Path(current['directory'])
    suffix = '-fixed' if (run / 'audio-monitor-executed.py').exists() else ''
    shutil.copy2(__file__, run / ('audio-monitor' + suffix + '-executed.py'))
    with (run / ('audio-observations' + suffix + '.jsonl')).open('w', buffering=1) as stream:
        for _ in range(1800):
            if (run / 'audio-monitor.stop').exists(): break
            result = ram.remote('''set -eu
cat /run/qt-audio.json; echo
/tmp/tinymix get "Handsfree Playback Volume"
/tmp/tinymix get "Handsfree Right Playback"
/tmp/tinymix get "Earphone Playback Switch"
/tmp/tinymix get "Handsfree Left Playback"
cat /run/qt-audio.json; echo
echo PCM
cat /proc/asound/card0/pcm0p/sub0/hw_params /proc/asound/card0/pcm0p/sub0/status
''')
            result.check_returncode()
            lines = result.stdout.splitlines()
            before, after = json.loads(lines[0]), json.loads(lines[5])
            # Frame counters can change while controls remain stable.
            stable = all(before[k] == after[k] for k in ('volume', 'muted', 'gain', 'route'))
            gain = [int(v) for v in re.match(r'(\d+), (\d+)', lines[1]).groups()]
            right = 1 if '> HF DAC' in lines[2] else 0 if '> Off' in lines[2] else -1
            matches = gain[1] == after['gain'] and right == after['route']
            expected = int(not after['muted'] and after['volume'] != 0)
            valid = matches and right == expected and gain[0] == 0 and lines[3] == 'Off' and lines[4].startswith('> Off')
            record = {'time': datetime.now(timezone.utc).isoformat(), 'qt': after,
                      'stable_controls': stable, 'mixer_matches_qt': matches,
                      'hfr_gain': gain, 'hfr_route': right,
                      'expected_mute_and_unrelated_outputs_off': valid,
                      'pcm': '\n'.join(lines[7:])}
            stream.write(json.dumps(record) + '\n')
            if stable and not valid: raise RuntimeError('Qt/mixer mismatch: ' + str(record))
            time.sleep(1)


if __name__ == '__main__':
    main()
