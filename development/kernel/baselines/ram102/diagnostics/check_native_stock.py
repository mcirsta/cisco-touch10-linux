#!/usr/bin/env python3
"""Read stock ADC measurement state after watchdog recovery; remove RAM helper."""
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
    current = json.load(open(ROOT / 'development/perrier-ramenv/current-session.json'))
    assert current['profile'] in ('native-diagnostics', 'pmu-probe', 'pmu-selftest') and current['stock_recovered']
    run = Path(current['directory'])
    panel = dev.Panel(run)
    state = panel.snapshot()
    assert state['kernel'] == '3.4.113+' and state['factory_app'] == 'running'
    helper = ROOT / 'development/kernel/out/native-diagnostics/pmic-adc-read'
    target = '/tmp/perrier-adc-check-' + uuid.uuid4().hex[:8]
    shutil.copy2(__file__, run / 'diagnostics-stock-check-executed.py')
    try:
        subprocess.run(panel.ssh + ['cat > ' + target], input=helper.read_bytes(), capture_output=True, check=True, timeout=15)
        result = panel.run('chmod 700 ' + target + '\n' + target + ' stock\n', timeout=15)
        result.check_returncode()
        (run / 'diagnostics-stock-after.log').write_text(result.stdout + result.stderr)
    finally:
        panel.run('rm -f ' + target + '\n').check_returncode()
    baseline = (ROOT / 'development/kernel/out/native-diagnostics/stock-adc-pmu.log').read_text()
    config = lambda text: {addr + ':' + reg: val for addr, reg, val in
                          re.findall(r'^ADC_CFG (\w+) (\w+) (\w+)', text, re.M)}
    old, new = config(baseline), config(result.stdout)
    stable = ['48:e4', '49:04', '49:06', '49:2e', '49:90', '49:d4', '49:d7']
    differences = {k: {'before': old[k], 'after': new[k]} for k in stable if old[k] != new[k]}
    trim = lambda text: dict(re.findall(r'^ADC_TRIM (\w+) (\w+)', text, re.M))
    assert len(trim(baseline)) == 16 and trim(baseline) == trim(result.stdout)
    record = {'passed': not differences, 'stock': state, 'adc_stable_control_differences': differences,
              'adc_otp_trim_preserved': True, 'volatile_selector_and_conversion_status_excluded': True,
              'temporary_helper_removed': True, 'helper_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
              'executed_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (run / 'diagnostics-stock-checks.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
    if differences:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
