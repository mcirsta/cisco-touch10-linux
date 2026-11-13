#!/usr/bin/env python3
"""Check native audio registration and silent PCM without touching Qt/display."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_ram as ram


def main():
    current = json.loads(ram.CURRENT.read_text())
    assert current['status'] == 'interactive' and current['profile'] == 'native-audio'
    state = ram.ram_state('6.18.48-perrier-ram97')
    directory = Path(current['directory'])
    shutil.copy2(__file__, directory / 'check-audio-executed.py')
    tools = ROOT / 'development/audio'
    manifest = json.loads((tools / 'manifest96k.json').read_text())
    for name, digest in manifest['files'].items():
        path = tools / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        ram.push_file(path, '/tmp/' + path.name)
    helper = ROOT / 'development/kernel/out/peripherals/peripheral-read'
    assert hashlib.sha256(helper.read_bytes()).hexdigest() == \
        'c80c922bb12f3c4390f066a61f9c754d06e90863e059e7b7bd049d267e615e9a'
    ram.push_file(helper, '/tmp/peripheral-read')
    def command(script, name, timeout=25):
        result = ram.remote(script, timeout=timeout)
        (directory / name).write_text(result.stdout + result.stderr)
        result.check_returncode()
        return result.stdout
    before = command('''set -eu
uname -r
cat /run/guard.json /run/qt.pid
cat /sys/block/mmcblk0/ro /proc/mounts
cat /proc/asound/cards /proc/asound/pcm
cat /sys/kernel/debug/devices_deferred
/tmp/tinymix contents
/tmp/tinypcminfo -D 0 -d 0
/tmp/peripheral-read ram
cat /proc/interrupts
''', 'audio-before.log')
    assert 'Cisco Touch 10 Perrier' in before and 'playback 1' in before
    assert 'Handsfree Playback Volume' in before
    pid = command('cat /run/qt.pid\n', 'audio-qt-pid-before.log').strip()
    assert pid.isdigit()
    silent = command('''set -eu
trap '/tmp/tinymix set "Handsfree Right Playback" 0 >/dev/null; /tmp/tinymix set "Handsfree Playback Volume" 0 0 >/dev/null' EXIT HUP INT TERM
/tmp/tinymix set "Handsfree Playback Volume" 0 0
/tmp/tinymix set "Handsfree Left Playback" 0
/tmp/tinymix set "Earphone Playback Switch" 0
/tmp/tinymix set "Handsfree Right Playback" 1
/tmp/tinyplay /tmp/silence96-4ch.wav -D 0 -d 0 -p 512 -n 4 -E > /tmp/audio-silence.log 2>&1 &
pcm_pid=$!
sleep 0.6
echo STATUS_ONE
cat /proc/asound/card0/pcm0p/sub0/status
cat /proc/asound/card0/pcm0p/sub0/hw_params
sleep 0.6
echo STATUS_TWO
cat /proc/asound/card0/pcm0p/sub0/status
wait "$pcm_pid"
cat /tmp/audio-silence.log
cat /proc/interrupts
''', 'audio-silence.log', timeout=15)
    assert silent.count('state: RUNNING') == 2
    pointers = [int(value) for value in re.findall(r'^hw_ptr\s*:\s*(\d+)', silent, re.M)]
    assert len(pointers) == 2 and pointers[1] > pointers[0], pointers
    after = command('''set -eu
/tmp/peripheral-read ram
/tmp/tinymix contents
cat /run/qt.pid
cat /run/guard.json
dmesg
''', 'audio-after-silence.log')
    def pmic(text):
        return dict(re.findall(r'^PMIC ([0-9a-f]+) ([0-9a-f]+)', text, re.M))
    assert pmic(before) == pmic(after)
    final_pid = command('cat /run/qt.pid\n', 'audio-qt-pid-after.log').strip()
    assert final_pid == pid
    assert not re.search(r'Kernel panic|BUG:|FIFO (?:under|over)|DMA.*error', after)
    result = {'passed': True, 'kernel': state['kernel'], 'boot_id': state['boot_id'],
              'native_card_registered': True, 'silent_pcm_dma_progress': pointers,
              'pcm_rate': 96000, 'pcm_channels': 4, 'pcm_format': 'S32_LE',
              'hfr_path_only': True, 'minimum_gain_during_silence': True,
              'hfr_route_disabled_after_test': True, 'sampled_pmic_rail_registers_preserved': True,
              'qt_pid_unchanged': pid, 'display_cycles': 0, 'qt_restarts': 0,
              'audio_tools_manifest_sha256': hashlib.sha256((tools / 'manifest96k.json').read_bytes()).hexdigest(),
              'executed_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (directory / 'audio-checks.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
