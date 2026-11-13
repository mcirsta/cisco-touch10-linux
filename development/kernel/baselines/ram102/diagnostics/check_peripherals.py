#!/usr/bin/env python3
"""Check only ram95's new peripherals; never blank or restart the display."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_ram as ram
from check_display import png

EVIDENCE = ROOT / 'development/kernel/out/peripherals'
HELPER = EVIDENCE / 'peripheral-read'
HELPER_SHA = 'c80c922bb12f3c4390f066a61f9c754d06e90863e059e7b7bd049d267e615e9a'


def registers(text, kind):
    return {tuple(parts[1:-1]): int(parts[-1], 16)
            for line in text.splitlines() if (parts := line.split()) and parts[0] == kind}


def main():
    current = json.loads(ram.CURRENT.read_text())
    assert current['status'] == 'interactive' and current['profile'] == 'peripherals'
    state = ram.ram_state('6.18.48-perrier-ram95')
    directory = Path(current['directory'])
    shutil.copy2(__file__, directory / 'check-peripherals-executed.py')
    assert hashlib.sha256(HELPER.read_bytes()).hexdigest() == HELPER_SHA
    ram.push_file(HELPER, '/tmp/peripheral-read')

    def command(script, name, binary=False):
        result = ram.remote(script, binary=binary, timeout=30)
        result.check_returncode()
        if binary:
            (directory / name).write_bytes(result.stdout)
        else:
            (directory / name).write_text(result.stdout + result.stderr)
        return result.stdout

    before = command('chmod 700 /tmp/peripheral-read\n/tmp/peripheral-read ram\n', 'peripherals-before.log')
    stock = (EVIDENCE / 'stock-registers.log').read_text()
    pmic_before = registers(before, 'PMIC')
    pmic_stock = registers(stock, 'PMIC')
    delta = {str(k): {'stock': pmic_stock[k], 'ram': v}
             for k, v in pmic_before.items() if pmic_stock[k] != v}
    (directory / 'pmic-stock-comparison.json').write_text(json.dumps(delta, indent=2) + '\n')
    # Bootloader transitions can be distinguished from changes during PWM use.
    # Record all differences rather than hiding them or writing stock values back.
    sensors = registers(before, 'INA')
    for addr in ('40', '41'):
        assert sensors[(addr, '00')] == 0x7127
        assert sensors[(addr, '0e')] == 0x7ffe
        assert sensors[(addr, '0f')] & 0xfffc == 0
        assert all(sensors[(addr, f'{r:02x}')] == 0x7ff8 for r in range(7, 13))
    raw = command('cat /sys/bus/i2c/devices/3-0054/eeprom\n', 'board-eeprom.bin', True)
    eeprom = json.loads((EVIDENCE / 'stock-board-eeprom.json').read_text())
    assert len(raw) == 256 and hashlib.sha256(raw).hexdigest() == eeprom['sha256']
    info = command('''set -eu
uname -r
cat /run/guard.json
cat /sys/block/mmcblk0/ro
cat /proc/mounts
stat -c '%a %n' /sys/bus/i2c/devices/3-0054/eeprom
for addr in 40 41; do
    device=/sys/bus/i2c/devices/3-00$addr
    echo "$device"
    readlink -f "$device/driver"
    for path in "$device"/hwmon/hwmon*/in[123]_input "$device"/hwmon/hwmon*/curr[123]_input; do
        printf '%s=' "$path"; cat "$path"
    done
done
readlink -f /sys/bus/i2c/devices/0-0048/driver
for path in /sys/class/leds/white:status/brightness /sys/class/leds/white:status/max_brightness; do
    printf '%s=' "$path"; cat "$path"
done
cat /sys/kernel/debug/gpio
cat /tmp/qt-active.log
dmesg
''', 'peripherals-native.log')
    values = re.findall(r'/(in[123]|curr[123])_input=(-?\d+)', info)
    assert len(values) == 12
    permission = re.search(r'^([0-7]+) .*eeprom$', info, re.M)
    assert permission and not int(permission[1], 8) & 0o222
    assert '/max_brightness=255' in info and '/brightness=0' in info
    assert not re.search(r'^\[.*(?:HS_TX_TIMEOUT|DSI error|Kernel panic|BUG:)', info, re.M)
    command('''set -eu
led=/sys/class/leds/white:status/brightness
initial=$(cat "$led")
[ "$initial" = 0 ]
trap 'echo "$initial" > "$led"' EXIT HUP INT TERM
echo 10 > "$led"
[ "$(cat "$led")" = 10 ]
sleep 2
/tmp/peripheral-read ram
echo 0 > "$led"
[ "$(cat "$led")" = 0 ]
''', 'white-led-on.log')
    after = command('/tmp/peripheral-read ram\n', 'peripherals-after.log')
    lit = (directory / 'white-led-on.log').read_text()
    assert registers(lit, 'PMIC') == pmic_before == registers(after, 'PMIC')
    pwm0, pwm_on, pwm_after = (registers(t, 'PWM') for t in (before, lit, after))
    for key in [('ba',), ('bb',)]:
        assert pwm0[key] == pwm_on[key] == pwm_after[key]
    assert pwm_on[('92',)] & 7 == pwm_after[('92',)] & 7 == pwm0[('92',)] & 7
    frame = command('dd if=/dev/fb0 bs=4096 count=1000\n', 'peripherals-framebuffer.raw', True)
    (directory / 'peripherals-framebuffer.png').write_bytes(png(frame))
    (directory / 'peripherals-framebuffer.raw').unlink()
    result = {'passed': True, 'kernel': state['kernel'], 'boot_id': state['boot_id'],
              'eeprom': eeprom, 'hwmon_values': values, 'power_channels': 6,
              'eeprom_sysfs_read_only': True,
              'ina_config_matches_stock': True, 'alert_policy_preserved': True,
              'pmic_stock_differences': delta, 'pmic_rails_unchanged_during_pwm_use': True,
              'other_pwm_channel_preserved': True, 'white_led_low_off_verified': True,
              'display_cycles': 0, 'qt_restarts': 0, 'helper_sha256': HELPER_SHA,
              'executed_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (directory / 'peripheral-checks.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
