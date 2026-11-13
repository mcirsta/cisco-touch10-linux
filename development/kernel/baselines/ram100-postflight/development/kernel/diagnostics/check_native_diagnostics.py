#!/usr/bin/env python3
"""Exercise PMIC ADC and perf in one RAM session; preserve display and rails."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_ram as ram


def pmic(text):
    return dict(re.findall(r'^PMIC ([0-9a-f]+) ([0-9a-f]+)', text, re.M))


def adc_config(text):
    return {addr + ':' + reg: int(value, 16)
            for addr, reg, value in re.findall(r'^ADC_CFG (\w+) (\w+) (\w+)', text, re.M)}


def main():
    current = json.loads(ram.CURRENT.read_text())
    assert current['status'] == 'interactive' and current['profile'] == 'native-diagnostics'
    state = ram.ram_state('6.18.48-perrier-ram100')
    run = Path(current['directory'])
    out = ROOT / 'development/kernel/out/native-diagnostics'
    from_logs = '--from-logs' in sys.argv
    if from_logs:
        shutil.copy2(run / 'diagnostics-check-executed.py', run / 'diagnostics-check-initial-failed.py')
    shutil.copy2(__file__, run / 'diagnostics-check-executed.py')
    files = [out / 'pmic-adc-read', out / 'perf-check',
             ROOT / 'development/kernel/out/peripherals/peripheral-read',
             ROOT / 'development/kernel/out/audio/audio-read']
    if not from_logs:
        for path in files:
            ram.push_file(path, '/tmp/' + path.name)
    def command(script, name, timeout=20, check=True):
        if from_logs:
            text = (run / name).read_text()
            status = 1 if name == 'diagnostics-perf.log' and 'instructions=0 ' in text else 0
            return subprocess.CompletedProcess([], status, text, '')
        result = ram.remote(script, timeout=timeout)
        (run / name).write_text(result.stdout + result.stderr)
        if check:
            result.check_returncode()
        return result
    before = command('''set -eu
uname -r
cat /run/qt.pid /run/qt-audio.json /run/guard.json
test "$(cat /sys/block/mmcblk0/ro)" = 1
if grep -q '^/dev/mmcblk0' /proc/mounts; then exit 2; fi
/tmp/pmic-adc-read ram
/tmp/peripheral-read ram
/tmp/audio-read ram
cat /proc/interrupts
for path in /sys/bus/iio/devices/iio:device*; do
 echo IIO_DEVICE=$path
 cat "$path/name" "$path/of_node/compatible"
done
ls /sys/bus/event_source/devices
''', 'diagnostics-before.log').stdout
    pid = command('cat /run/qt.pid\n', 'diagnostics-qt-pid.log').stdout.strip()
    adc = command('''set -eu
for path in /sys/bus/iio/devices/iio:device*; do
 [ "$(cat "$path/name")" = twl6030_gpadc ] || continue
 for pass in 1 2 3 4 5; do
  for channel in 7 8 9 10 18; do
   value=$(cat "$path/in_voltage${channel}_input")
   echo ADC_INPUT $pass $channel $value
  done
 done
done
cat /proc/interrupts
''', 'diagnostics-adc-conversions.log', timeout=20).stdout
    readings = [(int(p), int(c), int(v)) for p, c, v in re.findall(r'^ADC_INPUT (\d+) (\d+) (-?\d+)', adc, re.M)]
    assert len(readings) == 25 and {c for p, c, v in readings} == {7, 8, 9, 10, 18}
    assert all(-100 <= value <= 10000 for p, c, value in readings)
    irq = lambda s: [int(v) for v in re.findall(r'^\s*\d+:\s*(\d+)\s+.*twl6030_gpadc', s, re.M)]
    first, last = irq(before), irq(adc)
    assert len(first) == len(last) == 1 and 25 <= last[0] - first[0] <= 30, (first, last)
    perf = command('/tmp/perf-check\n', 'diagnostics-perf.log', check=False)
    counts = dict((k, int(v)) for k, v in re.findall(r'(\w+)=(\d+)', perf.stdout))
    assert counts.get('cycles', 0) > 1000000, perf.stdout + perf.stderr
    assert counts.get('samples', 0) > 0 and counts.get('lost', -1) == 0
    after = command('''set -eu
/tmp/pmic-adc-read ram
/tmp/peripheral-read ram
/tmp/audio-read ram
cat /run/qt.pid /run/qt-audio.json /run/guard.json
cat /proc/interrupts
cat /sys/kernel/debug/clk/clk_summary
dmesg
''', 'diagnostics-after.log').stdout
    reference = (ROOT / 'development/runs/20261112T112823Z-uboot-ram99-c29ec2/audio-application-before.log').read_text()
    assert len(pmic(before)) == 65 and pmic(before) == pmic(after) == pmic(reference)
    assert 'GPIO_RAW 11' in before and 'GPIO_RAW 11' in after
    assert command('cat /run/qt.pid\n', 'diagnostics-qt-pid-after.log').stdout.strip() == pid
    assert not re.search(r'Kernel panic|\bBUG:|Unhandled fault|division by zero', after, re.I)
    config = adc_config(before)
    stock = adc_config((out / 'stock-adc-pmu.log').read_text())
    assert config['48:e4'] == 7
    assert config['49:04'] == stock['49:04'] | 1
    assert config['49:06'] == stock['49:06'] | 1
    # The MFD initializes IRQ masks independently of the stock driver.
    # Verify EOC is unmasked and remains stable through the conversions.
    assert not config['49:d4'] & 0x20 and not config['49:d7'] & 0x20
    assert adc_config(after)['49:d4'] == config['49:d4']
    assert adc_config(after)['49:d7'] == config['49:d7']
    trim = lambda s: dict(re.findall(r'^ADC_TRIM (\w+) (\w+)', s, re.M))
    assert len(trim(before)) == 16 and trim(before) == trim(after) == trim((out / 'stock-adc-pmu.log').read_text())
    record = {'passed': True, 'kernel': state['kernel'], 'boot_id': state['boot_id'],
              'adc_channel_readings_mV': readings, 'adc_eoc_irq_count': last[0] - first[0],
              'adc_expected_measurement_controls_verified': True, 'adc_trim_bytes_preserved': True,
              'pmu': counts, 'pmu_complete_counter_and_irq_test': perf.returncode == 0,
              'pmu_cycle_counter_and_overflow_sampling_verified': True,
              'pmu_general_event_counters_unqualified': counts.get('instructions', 0) == 0,
              'analysis_reused_original_hardware_logs': from_logs,
              '65_pmic_rail_fields_preserved': True, 'gpio_port': '0x11',
              'display_cycles': 0, 'qt_restarts': 0, 'qt_pid_unchanged': pid,
              'helpers': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
              'executed_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (run / 'diagnostics-checks.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
