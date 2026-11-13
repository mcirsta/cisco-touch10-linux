#!/usr/bin/env python3
"""Read back the relevant stock state after ram96 watchdog recovery."""
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
    current = json.loads((ROOT / 'development/perrier-ramenv/current-session.json').read_text())
    assert current['profile'] == 'rtc-gpio' and current['stock_recovered']
    run = Path(current['directory'])
    panel = dev.Panel(run)
    state = panel.snapshot()
    assert state['kernel'] == '3.4.113+' and state['factory_app'] == 'running'
    assert state['boot_id'] == current['after']['boot_id']
    helper = ROOT / 'development/kernel/out/rtc-expander-audio/rtc-gpio-check'
    data = helper.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == 'b57a9a7c8c7c5e01693d4260e415cb3c1b2f37adbf272815cd12a17ce00ace6d'
    shutil.copy2(__file__, run / 'check-aux-stock-executed.py')
    directory = '/tmp/touch10-aux-read-' + uuid.uuid4().hex
    panel.run('set -eu\n'
              '[ "$(awk \'$2 == "/tmp" {print $3}\' /proc/mounts)" = tmpfs ]\n'
              f'umask 077\nmkdir {directory}\n').check_returncode()
    try:
        subprocess.run(panel.ssh + [f'cat > {directory}/rtc-gpio-check'],
                       input=data, capture_output=True, timeout=20, check=True)
        readback = subprocess.run(panel.ssh + [f'cat {directory}/rtc-gpio-check'],
                                  capture_output=True, timeout=20, check=True)
        assert readback.stdout == data
        result = panel.run(f'set -eu\nchmod 700 {directory}/rtc-gpio-check\n'
                           f'{directory}/rtc-gpio-check stock\n'
                           'uname -r\npidof phoenix\ndf -k /mnt/base\n', timeout=15)
        (run / 'stock-after-aux.log').write_text(result.stdout + result.stderr)
        result.check_returncode()
        text = result.stdout
        assert 'GPIO_RAW 11' in text
        assert re.search(r'advance=[2-4] alarm_enabled=0', text)
        def clocks(text):
            return dict(re.findall(r'^CLOCK_REG ([0-9a-f]+) ([0-9a-f]+)', text, re.M))
        stock = (helper.parent / 'stock-rtc-gpio-clocks.log').read_text()
        assert clocks(text) == clocks(stock)
    finally:
        panel.run(f'rm -f {directory}/rtc-gpio-check\nrmdir {directory}\n').check_returncode()
    proof = {'passed': True, 'stock': state, 'gpio_value_matches_stock_before_test': '0x11',
             'all_sampled_pmic_clock_registers_match_stock_before_test': True,
             'rtc_advances_and_alarm_disabled': True, 'tmpfs_helper_removed': True,
             'helper_sha256': digest,
             'executed_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (run / 'stock-after-aux-checks.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
