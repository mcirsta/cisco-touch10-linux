#!/usr/bin/env python3
"""Exercise only the two DT LED class devices and compare other GPIO outputs."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_ram as ram


def run(script, destination):
    result = ram.remote(script, timeout=20)
    destination.write_text(result.stdout + result.stderr)
    result.check_returncode()
    return result.stdout


def gpios(text):
    records = {}
    for number, label, direction, value in re.findall(
            r'gpio-(\d+)\s+\(([^)]*)\)\s+(in|out)\s+(hi|lo)', text):
        # Input samples may change asynchronously; direction and ownership may not.
        records[int(number)] = (label.strip(), direction, value if direction == 'out' else '')
    assert records, 'No GPIO debug records captured'
    return records


def main():
    record = json.loads(ram.CURRENT.read_text())
    assert record['status'] == 'interactive' and record['profile'] == 'native-leds'
    ram.ram_state('6.18.48-perrier-ram94')
    directory = Path(record['directory'])
    run('''set -eu
pid=$(cat /run/qt.pid)
case "$pid" in ''|*[!0-9]*) exit 2;; esac
exe=$(readlink /proc/$pid/exe)
case "$exe" in /qt/bin/perrier-touch-grid|/tmp/grid-*) ;; *) exit 3;; esac
kill -TERM "$pid"
i=0
while [ -e /proc/$pid/exe ] && [ "$i" -lt 50 ]; do sleep 0.1; i=$((i+1)); done
[ ! -e /proc/$pid/exe ]
cat /tmp/qt-active.log
for color in red green; do
    led=/sys/class/leds/$color:micmute
    [ "$(cat "$led/max_brightness")" = 1 ]
    [ "$(cat "$led/brightness")" = 0 ]
done
''', directory / 'leds-qt-exit.log')
    before = gpios(run('cat /sys/kernel/debug/gpio\n', directory / 'leds-before.log'))
    ids = {color: [n for n, data in before.items() if color + ':micmute' in data[0]]
           for color in ('red', 'green')}
    assert all(len(v) == 1 for v in ids.values()), ids
    red, green = ids['red'][0], ids['green'][0]
    assert before[red][1:] == before[green][1:] == ('out', 'lo')
    unrelated = {n: v for n, v in before.items() if n not in (red, green)}
    checks = []
    try:
        for label, r, g in [('red', 1, 0), ('off', 0, 0), ('green', 0, 1), ('final-off', 0, 0)]:
            output = run(f'''set -eu
echo 0 > /sys/class/leds/red:micmute/brightness
echo 0 > /sys/class/leds/green:micmute/brightness
echo {r} > /sys/class/leds/red:micmute/brightness
echo {g} > /sys/class/leds/green:micmute/brightness
[ "$(cat /sys/class/leds/red:micmute/brightness)" = {r} ]
[ "$(cat /sys/class/leds/green:micmute/brightness)" = {g} ]
cat /sys/kernel/debug/gpio
''', directory / f'leds-{label}.log')
            actual = gpios(output)
            assert {n: v for n, v in actual.items() if n not in (red, green)} == unrelated
            assert actual[red][1:] == ('out', 'hi' if r else 'lo')
            assert actual[green][1:] == ('out', 'hi' if g else 'lo')
            checks.append({'state': label, 'red': r, 'green': g, 'other_gpio_outputs_unchanged': True})
    finally:
        run('echo 0 > /sys/class/leds/red:micmute/brightness\n'
            'echo 0 > /sys/class/leds/green:micmute/brightness\n', directory / 'leds-cleanup.log')
        ram.restart_qt(ROOT / 'development/perrier-qt/build-arm-a9-local/perrier-touch-grid')
    result = {'passed': True, 'kernel': record['ram']['kernel'], 'states': checks,
              'qt_exit_restored_off': True, 'qt_restarted': True,
              'gpio_debug_ids': {'red': red, 'green': green},
              'non_led_gpio_lines_compared': len(unrelated)}
    (directory / 'leds-checks.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
