#!/usr/bin/env python3
"""Test application-rate PCM and unchanged peripherals; leave Qt running."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import wave

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_ram as ram


def main():
    current = json.loads(ram.CURRENT.read_text())
    assert current['status'] == 'interactive' and current['profile'] in ('application-audio', 'speaker-audio')
    version = 'ram99' if current['profile'] == 'speaker-audio' else 'ram98'
    state = ram.ram_state('6.18.48-perrier-' + version)
    directory = Path(current['directory'])
    shutil.copy2(__file__, directory / 'audio-application-check-executed.py')
    files = [ROOT / 'development/audio/build/tinymix',
             ROOT / 'development/kernel/out/peripherals/peripheral-read',
             ROOT / 'development/kernel/out/audio/audio-read']
    for path in files:
        ram.push_file(path, '/tmp/' + path.name)
    def command(script, name, timeout=20):
        result = ram.remote(script, timeout=timeout)
        (directory / name).write_text(result.stdout + result.stderr)
        result.check_returncode()
        return result.stdout
    before = command('''set -eu
uname -r
cat /run/qt.pid /run/qt-audio.json
cat /run/guard.json
cat /sys/block/mmcblk0/ro /proc/mounts
/tmp/peripheral-read ram
/tmp/audio-read ram
/tmp/tinymix contents
cat /proc/asound/cards /proc/asound/pcm
''', 'audio-application-before.log')
    status = json.loads(command('cat /run/qt-audio.json\n', 'audio-qt-initial.json'))
    assert status['available'] and not status['error'] and status['gain'] == 12 and status['route'] == 1
    pid = command('cat /run/qt.pid\n', 'audio-qt-pid-before.log').strip()
    pcms = {}
    for channels in (1, 2):
        source = directory / f'audio-silence48-{channels}ch.wav'
        with wave.open(str(source), 'wb') as stream:
            stream.setnchannels(channels); stream.setsampwidth(2); stream.setframerate(48000)
            stream.writeframes(bytes(48000 * channels * 2 * 3))
        ram.push_file(source, '/tmp/' + source.name)
        text = command(f'''set -eu
aplay -D default -v /tmp/{source.name} > /tmp/application-pcm.log 2>&1 &
player=$!
sleep 0.6
echo STATUS_ONE
cat /proc/asound/card0/pcm0p/sub0/status
cat /proc/asound/card0/pcm0p/sub0/hw_params
sleep 0.6
echo STATUS_TWO
cat /proc/asound/card0/pcm0p/sub0/status
wait "$player"
cat /tmp/application-pcm.log
''', f'audio-application-{channels}ch.log', timeout=12)
        assert text.count('state: RUNNING') == 2
        assert 'format: S32_LE' in text and 'channels: 4' in text and 'rate: 96000' in text
        assert 'rate         : 48000' in text and 'linear-interpolation' in text
        assert 'underrun' not in text.lower()
        pointers = [int(v) for v in re.findall(r'^hw_ptr\s*:\s*(\d+)', text, re.M)]
        assert len(pointers) == 2 and pointers[1] > pointers[0]
        pcms[str(channels)] = {'application_rate': 48000, 'application_format': 'S16_LE',
            'application_channels': channels, 'hardware_rate': 96000,
            'hardware_format': 'S32_LE', 'hardware_channels': 4, 'dma_pointers': pointers}
    after = command('''set -eu
/tmp/peripheral-read ram
/tmp/audio-read ram
/tmp/tinymix contents
cat /run/qt.pid /run/guard.json
dmesg
''', 'audio-application-after.log')
    pmic = lambda s: dict(re.findall(r'^PMIC ([0-9a-f]+) ([0-9a-f]+)', s, re.M))
    previous = (ROOT / 'development/runs/20261112T102852Z-uboot-ram97-4a52f1/audio-before.log').read_text()
    assert len(pmic(before)) == 65 and pmic(before) == pmic(after) == pmic(previous)
    assert 'GPIO_RAW 11' in before and 'GPIO_RAW 11' in after
    final_pid = command('cat /run/qt.pid\n', 'audio-qt-pid-after.log').strip()
    assert pid == final_pid
    assert not re.search(r'Kernel panic|BUG:|FIFO (?:under|over)|DMA.*error', after)
    result = {'passed': True, 'kernel': state['kernel'], 'boot_id': state['boot_id'],
              'pcm_cases': pcms, 'qt_native_alsa_ready': True,
              'qt_pid_unchanged': pid, 'display_cycles': 0, 'qt_restarts': 0,
              'all_65_pmic_fields_match_ram97_before_and_after': True,
              'gpio_port': '0x11',
              'helpers': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
              'executed_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (directory / 'audio-application-checks.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
