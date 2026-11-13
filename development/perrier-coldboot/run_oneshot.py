#!/usr/bin/env python3
"""Run one audited U-Boot boot-path probe, then verify stock return."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_dev as dev  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remote_bytes(panel: dev.Panel, command: str, data: bytes | None = None,
                 timeout: float = 30) -> bytes:
    result = subprocess.run(panel.ssh + [command], input=data,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'SSH transfer failed: {result.stderr.decode(errors="replace")}')
    return result.stdout


def read_p8(panel: dev.Panel) -> bytes:
    data = remote_bytes(panel, 'dd if=/dev/mmcblk0p8 bs=262144 count=1', timeout=20)
    if len(data) != 262144:
        raise RuntimeError(f'Expected 262144 p8 bytes, read {len(data)}')
    return data


def write_p8(panel: dev.Panel, data: bytes) -> None:
    if len(data) != 262144:
        raise ValueError('Refusing a non-256-KiB p8 write')
    remote_bytes(panel, 'cat > /dev/mmcblk0p8 && sync', data, timeout=30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--power-cycle', action='store_true',
                        help='wait for one physical power cycle instead of requesting software reboot')
    parser.add_argument('--arm-timeout', type=int, default=900,
                        help='seconds to wait for a physical power cycle')
    args = parser.parse_args()
    if not 120 <= args.timeout <= 600:
        parser.error('timeout must be 120..600 seconds')
    if not 120 <= args.arm_timeout <= 3600:
        parser.error('arm-timeout must be 120..3600 seconds')
    manifest_path = HERE / 'oneshot-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    audit = json.loads((HERE / 'oneshot-audit.json').read_text())
    staged = json.loads((HERE / 'stage-result.json').read_text())
    candidate = (HERE / 'oneshot-p8.bin').read_bytes()
    original = (HERE / 'stock-p8-before.bin').read_bytes()
    if not audit['passed'] or audit['manifest_sha256'] != sha(manifest_path.read_bytes()) or \
       audit['candidate_p8_sha256'] != sha(candidate) or \
       staged['status'] != 'staged-and-readback-verified' or \
       staged['oneshot_manifest_sha256'] != sha(manifest_path.read_bytes()) or \
       sha(original) != dev.STOCK_ENV_SHA256:
        raise ValueError('The audited candidate, p8 snapshot, or staging report changed')
    directory = ROOT / 'development/runs' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') +
        '-coldboot-' + uuid.uuid4().hex[:6])
    directory.mkdir(parents=True)
    report = {'status': 'preflight', 'started': dev.now(),
              'profile': 'perrier-cold01', 'directory': str(directory),
              'reset_mode': 'physical-power-cycle' if args.power_cycle else 'software-reboot',
              'candidate_p8_sha256': sha(candidate),
              'original_p8_sha256': sha(original),
              'manifest_sha256': sha(manifest_path.read_bytes())}
    def save():
        dev.write_json(directory / 'result.json', report)
    save()
    with (ROOT / 'development/.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        dev.validate_host(dev.host_checks())
        panel = dev.Panel(directory)
        before = panel.snapshot()
        report['before'] = before
        if before['kernel'] != '3.4.113+' or before['factory_app'] != 'running' or \
           read_p8(panel) != original:
            raise RuntimeError('Factory system or exact p8 baseline changed')
        for name, item in manifest['test_files'].items():
            target = '/mnt/base' + item['target']
            data = (ROOT / item['source']).read_bytes()
            if len(data) != item['bytes'] or sha(data) != item['sha256'] or \
               remote_bytes(panel, 'cat ' + target) != data:
                raise RuntimeError(f'Staged {name} differs from audited source')
        report['status'] = 'ready'
        save()
        print('COLD_BOOT_READY logs=' + str(directory), flush=True)
        with dev.SerialCapture(dev.UART, directory) as serial:
            report['p8_write_started'] = dev.now()
            report['status'] = 'arming'
            save()
            try:
                write_p8(panel, candidate)
                actual = read_p8(panel)
                if actual != candidate:
                    raise RuntimeError('Candidate p8 readback differs')
            except BaseException:
                # Stock is still running; restore the exact known-good image.
                report['candidate_write_failed'] = True
                try:
                    write_p8(panel, original)
                    report['original_restored'] = read_p8(panel) == original
                finally:
                    save()
                raise
            report['p8_candidate_verified'] = True
            if args.power_cycle:
                report['status'] = 'awaiting-physical-power-cycle'
                save()
                print('POWER_CYCLE_READY: remove and reconnect PoE/power once; '
                      'leave USB connected', flush=True)
                deadline = time.monotonic() + args.arm_timeout
                serial_path = directory / 'serial.raw'
                while time.monotonic() < deadline:
                    captured = serial_path.read_bytes() if serial_path.exists() else b''
                    if b'PPA supports' in captured or b'U-Boot 2013.04' in captured:
                        report['boot_seen_on_serial'] = dev.now()
                        break
                    if serial.error:
                        report['serial_error'] = serial.error
                        break
                    time.sleep(0.5)
                else:
                    current = panel.snapshot()
                    if current['boot_id'] == before['boot_id'] and \
                       current['kernel'] == before['kernel']:
                        write_p8(panel, original)
                        report['original_restored'] = read_p8(panel) == original
                        report['status'] = 'power-cycle-not-done-disarmed'
                    else:
                        report['status'] = 'power-cycle-unobserved-check-device'
                    save()
                    raise TimeoutError('No physical boot observed during arming window')
            else:
                report['status'] = 'rebooting'
                save()
                try:
                    request = panel.run('reboot\n', timeout=20)
                    report['reboot_ssh_exit'] = request.returncode
                except subprocess.TimeoutExpired:
                    # A closing SSH session can outlive the reboot request.
                    report['reboot_ssh_exit'] = 'ssh-timeout'
                report['reboot_requested'] = dev.now()
                save()
            try:
                after = dev.wait_for_stock(panel, before, timeout=args.timeout)
            except TimeoutError:
                report['status'] = 'needs-manual-recovery'
                report['serial_bytes'] = serial.byte_count
                # If the reboot was rejected and the old stock boot is still
                # running, disarm the candidate rather than leaving it queued.
                try:
                    current = panel.snapshot()
                    report['timeout_snapshot'] = current
                    if current['boot_id'] == before['boot_id'] and \
                       current['kernel'] == before['kernel']:
                        write_p8(panel, original)
                        report['original_restored'] = read_p8(panel) == original
                        report['status'] = ('reboot-not-executed-disarmed' if
                                            report['original_restored'] else
                                            'reboot-not-executed-restore-failed')
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    report['timeout_inspection_error'] = str(exc)
                save()
                print('TIMEOUT: stock did not return; inspect the serial log. '
                      'A cold power cycle may be needed.', flush=True)
                raise
            report['after'] = after
            report['stock_p8_sha256'] = sha(read_p8(panel))
            # Give the passive UART thread a moment to drain the last lines.
            time.sleep(2)
        data = (directory / 'serial.raw').read_bytes()
        markers = {
            'uboot_saved_factory': b'PERRIER_ONESHOT_SAVED' in data,
            'uboot_bootz': b'Starting kernel' in data,
            'new_kernel_init': b'PERRIER_COLD01_INIT_ENTER' in data,
            'new_kernel_reboot': b'PERRIER_COLD01_REBOOT_TO_STOCK' in data,
        }
        report['markers'] = markers
        report['serial_bytes'] = len(data)
        report['serial_error'] = serial.error
        report['status'] = 'passed' if all(markers.values()) and \
            report['stock_p8_sha256'] == dev.STOCK_ENV_SHA256 else 'recovered-with-unexpected-state'
        report['finished'] = dev.now()
        save()
        print(json.dumps({'status': report['status'], 'markers': markers,
                          'stock_kernel': after['kernel'],
                          'factory_app': after['factory_app'],
                          'stock_p8_sha256': report['stock_p8_sha256'],
                          'logs': str(directory)}, indent=2), flush=True)
        if report['status'] != 'passed':
            raise RuntimeError('Cold boot did not satisfy every handoff and recovery check')


if __name__ == '__main__':
    main()
