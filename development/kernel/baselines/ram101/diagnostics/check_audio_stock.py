#!/usr/bin/env python3
"""Verify stock audio and rail state after a qualified audio RAM watchdog test."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_dev as dev


def main():
    record = json.loads((ROOT / 'development/perrier-ramenv/current-session.json').read_text())
    assert record['profile'] in ('native-audio', 'application-audio', 'speaker-audio', 'native-diagnostics') and record['stock_recovered']
    run = Path(record['directory'])
    panel = dev.Panel(run)
    state = panel.snapshot()
    assert state['kernel'] == '3.4.113+' and state['factory_app'] == 'running'
    assert state['boot_id'] == record['after']['boot_id']
    helpers = {
        'audio-read': ROOT / 'development/kernel/out/audio/audio-read',
        'peripheral-read': ROOT / 'development/kernel/out/peripherals/peripheral-read',
        'alsa-controls-read': ROOT / 'development/kernel/out/rtc-expander-audio/alsa-controls-read',
    }
    shutil.copy2(__file__, run / 'stock-audio-check-executed.py')
    directory = '/tmp/touch10-audio-read-' + uuid.uuid4().hex
    panel.run('set -eu\n'
              '[ "$(awk \'$2 == "/tmp" {print $3}\' /proc/mounts)" = tmpfs ]\n'
              f'umask 077\nmkdir {directory}\n').check_returncode()
    hashes = {}
    try:
        for name, path in helpers.items():
            data = path.read_bytes()
            hashes[name] = hashlib.sha256(data).hexdigest()
            subprocess.run(panel.ssh + [f'cat > {directory}/{name}'], input=data,
                           capture_output=True, timeout=20, check=True)
            result = subprocess.run(panel.ssh + [f'cat {directory}/{name}'],
                                    capture_output=True, timeout=20, check=True)
            assert result.stdout == data
        result = panel.run(f'''set -eu
chmod 700 {directory}/*
{directory}/audio-read stock
{directory}/peripheral-read stock
{directory}/alsa-controls-read
uname -r
pidof phoenix
cat /proc/asound/cards /proc/asound/pcm
df -k /mnt/base
''', timeout=20)
        (run / 'stock-audio-after.log').write_text(result.stdout + result.stderr)
        result.check_returncode()
        text = result.stdout
        assert 'CODEC 01 4b' in text and 'CODEC 02 02' in text and 'GPIO_RAW 11' in text
        def pmic(text):
            return dict(re.findall(r'^PMIC ([0-9a-f]+) ([0-9a-f]+)', text, re.M))
        old = (ROOT / 'development/kernel/out/peripherals/stock-registers.log').read_text()
        assert pmic(text) == pmic(old)
        assert 'controls=83' in text
        # Stock actually selects HFR; its generic EP control remains disabled.
        assert re.search(r'CONTROL \d+ Handsfree Right Playback type=3 count=1 1', text)
        assert re.search(r'CONTROL \d+ Earphone Playback Switch type=1 count=1 0', text)
    finally:
        panel.run(f'rm -f {directory}/audio-read {directory}/peripheral-read '
                  f'{directory}/alsa-controls-read\nrmdir {directory}\n').check_returncode()
    proof = {'passed': True, 'stock': state, 'stock_audio_controls': 83,
             'stock_hfr_route_selected': True, 'stock_ep_route_disabled': True,
             'all_65_sampled_pmic_rail_fields_match_stock_baseline': True,
             'codec_id_and_revision': ['0x4b', '0x02'], 'gpio_port': '0x11',
             'temporary_helpers_removed': True, 'helper_sha256': hashes,
             'executed_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (run / 'stock-audio-checks.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
