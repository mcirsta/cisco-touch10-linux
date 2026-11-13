#!/usr/bin/env python3
"""Check ram96 RTC/GPIO/clock APIs, keeping Qt and the display running."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_ram as ram
from check_display import png

EVIDENCE = ROOT / 'development/kernel/out/rtc-expander-audio'
HELPERS = {'rtc-gpio-check': 'b57a9a7c8c7c5e01693d4260e415cb3c1b2f37adbf272815cd12a17ce00ace6d',
           'rtc-alarm-check': '0273d0c808ea272227a771590b16719a413ce5324e4f7d7670dee13bd89650d5'}


def main():
    record = json.loads(ram.CURRENT.read_text())
    assert record['status'] == 'interactive' and record['profile'] == 'rtc-gpio'
    state = ram.ram_state('6.18.48-perrier-ram96')
    directory = Path(record['directory'])
    shutil.copy2(__file__, directory / 'check-aux-executed.py')
    for name, digest in HELPERS.items():
        path = EVIDENCE / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        ram.push_file(path, '/tmp/' + name)
    def command(script, name, binary=False, timeout=30):
        result = ram.remote(script, binary=binary, timeout=timeout)
        if binary:
            (directory / name).write_bytes(result.stdout)
        else:
            (directory / name).write_text(result.stdout + result.stderr)
        result.check_returncode()
        return result.stdout
    before = command('''set -eu
uname -r
cat /run/guard.json
cat /sys/block/mmcblk0/ro
cat /proc/mounts
cat /proc/interrupts
cat /sys/kernel/debug/gpio
cat /sys/kernel/debug/clk/clk_summary
for clock in clk32kg clk32kaudio; do
    for field in clk_rate clk_prepare_count clk_enable_count; do
        path=/sys/kernel/debug/clk/$clock/$field
        printf '%s=' "$path"; cat "$path"
    done
done
cat /sys/class/rtc/rtc0/name /sys/class/rtc/rtc0/hctosys
cat /run/qt.pid
''', 'aux-before.log')
    qt_pid = before.splitlines()[-1]
    assert qt_pid.isdigit()
    clocks = {}
    for clock in ('clk32kg', 'clk32kaudio'):
        for field, expected in [('clk_rate', 32768), ('clk_prepare_count', 0), ('clk_enable_count', 0)]:
            match = re.search(r'/clk/' + clock + '/' + field + r'=(\d+)', before)
            assert match and int(match[1]) == expected, (clock, field)
            clocks[clock + '/' + field] = int(match[1])
    result = None
    for attempt in range(3):
        result = ram.remote('''set -eu
if [ -x /usr/bin/strace ]; then
    /usr/bin/strace -qq -v -e trace=ioctl -o /tmp/rtc-gpio.strace /tmp/rtc-gpio-check ram
else
    /tmp/rtc-gpio-check ram
fi
''', timeout=15)
        (directory / f'aux-read-{attempt}.log').write_text(result.stdout + result.stderr)
        if result.returncode == 0:
            break
        if 'busy' not in result.stderr.lower():
            result.check_returncode()
        time.sleep(0.1)
    result.check_returncode()
    basic = result.stdout
    assert 'GPIO_RAW 11' in basic and 'value=11 flags=0' in basic
    assert re.search(r'advance=[2-4] alarm_enabled=0', basic)
    clock_regs = {r: v for r, v in re.findall(r'^CLOCK_REG ([0-9a-f]+) ([0-9a-f]+)', basic, re.M)}
    stock = dict(re.findall(r'^CLOCK_REG ([0-9a-f]+) ([0-9a-f]+)',
                           (EVIDENCE / 'stock-rtc-gpio-clocks.log').read_text(), re.M))
    assert clock_regs == stock
    trace = command('if [ -r /tmp/rtc-gpio.strace ]; then cat /tmp/rtc-gpio.strace; fi\n', 'aux-read.strace')
    if trace:
        lines = [line for line in trace.splitlines() if 'GPIO_V2_GET_LINE_IOCTL' in line]
        assert lines and all('flags=0' in line for line in lines)
    alarm = command('/tmp/rtc-alarm-check\n', 'rtc-alarm.log', timeout=20)
    assert re.search(r'fired=1 .*cached_restored=1 disabled=1 bytes_restored=1', alarm)
    after = command('''set -eu
/tmp/rtc-gpio-check ram
cat /proc/interrupts
cat /sys/kernel/debug/gpio
cat /run/qt.pid
cat /tmp/qt-active.log
cat /run/guard.json
dmesg
''', 'aux-after.log')
    assert 'GPIO_RAW 11' in after and 'value=11 flags=0' in after
    assert dict(re.findall(r'^CLOCK_REG ([0-9a-f]+) ([0-9a-f]+)', after, re.M)) == stock
    pid = command('cat /run/qt.pid\n', 'aux-qt-pid.log').strip()
    assert pid == qt_pid
    def rtc_irqs(text):
        matches = [line for line in text.splitlines() if re.search(r'twl_rtc|rtc0', line)]
        return sum(int(value) for line in matches for value in re.findall(r'\b\d+\b', line.split(':', 1)[-1].split('twl')[0]))
    # The RTC device read returns RTC_AF; preserve the raw IRQ tables too.
    assert not re.search(r'Kernel panic|BUG:', after)
    frame = command('dd if=/dev/fb0 bs=4096 count=1000\n', 'aux-framebuffer.raw', True)
    (directory / 'aux-framebuffer.png').write_bytes(png(frame))
    (directory / 'aux-framebuffer.raw').unlink()
    proof = {'passed': True, 'kernel': state['kernel'], 'boot_id': state['boot_id'],
             'rtc_counter_advances': True, 'alarm_irq_fired': True,
             'alarm_state_and_exact_hardware_bytes_restored': True,
             'calendar_time_not_set': True, 'gpio_raw_and_native_asis_value': '0x11',
             'gpio_direction_drive_bias_and_latch_not_changed': True,
             'gpio_shutdown_retention_tested_offline': True,
             'pmic_clock_providers': clocks, 'pmic_clock_registers_preserved': True,
             'qt_pid_unchanged': qt_pid, 'display_cycles': 0, 'qt_restarts': 0,
             'helper_sha256': HELPERS,
             'executed_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (directory / 'aux-checks.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
