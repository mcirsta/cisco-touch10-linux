#!/usr/bin/env python3
"""Stage one audited U-Boot image, maintain its lease, and verify recovery."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

import touch10_dev as dev
import touch10_ram as ram

ROOT = dev.ROOT
SOURCE = ROOT / 'development/perrier-watchdog'
IMAGE = ROOT / 'development/perrier-ramenv/native-watchdog'
PLAN = IMAGE / 'uboot'
DEFAULT_PROFILE = 'dsi-standard-video'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def serial_handoff_markers(raw, kernel):
    # Kernel printk may interrupt a userspace console write mid-token.
    # Keep the raw stream, and also inspect it with complete, timestamped
    # printk records removed. This reconstructs the interrupted user write.
    userspace = re.sub(rb'\[[ \t]*\d+\.\d+\][^\r\n]*(?:\r\n|\n|\r)', b'', raw)
    tokens = {
        'factory_saved_before_handoff': b'PERRIER_ONESHOT_SAVED',
        'candidate_kernel': ('Linux version ' + kernel).encode(),
        'mainline_watchdog_ready': b'PERRIER_GUARD_READY backend=linux-watchdog',
        'ram_ssh_started': ('PERRIER_RAM_SSH_STARTED ip=10.77.10.10 version=' +
                            kernel.removeprefix('6.18.48-perrier-')).encode(),
    }
    markers = {name: token in raw or token in userspace for name, token in tokens.items()}
    reconstructed = [name for name, token in tokens.items()
                     if token not in raw and token in userspace]
    return markers, reconstructed


def remote_bytes(panel, command, data=None, timeout=60):
    result = subprocess.run(panel.ssh + [command], input=data, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Stock SSH transfer failed: ' + result.stderr.decode(errors='replace'))
    return result.stdout


def read_p8(panel):
    data = remote_bytes(panel, 'dd if=/dev/mmcblk0p8 bs=262144 count=1', timeout=20)
    if len(data) != 262144:
        raise RuntimeError('The p8 read did not return exactly 256 KiB')
    return data


def write_p8(panel, data):
    if len(data) != 262144:
        raise ValueError('Refusing a p8 write of a different size')
    remote_bytes(panel, 'cat > /dev/mmcblk0p8 && sync', data, timeout=30)


def stage(panel, manifest):
    total = sum(item['bytes'] for item in manifest['test_files'].values())
    check = panel.run(f'''set -eu
test "$(awk '$2 == "/mnt/base" {{print $1}}' /proc/mounts)" = /dev/mmcblk0p14
test "$(awk '$2 == "/mnt/base" {{print $3}}' /proc/mounts)" = ext4
test ! -L /mnt/base/touch10-dev
if [ ! -e /mnt/base/touch10-dev ]; then umask 077; mkdir /mnt/base/touch10-dev; fi
test -d /mnt/base/touch10-dev
test "$(df -Pk /mnt/base | awk 'NR == 2 {{print $4}}')" -gt {(total + 1023) // 1024 + 8192}
''')
    if check.returncode:
        raise RuntimeError('The p14 staging directory, mount, or free-space check failed')
    staged = {}
    for name, item in manifest['test_files'].items():
        target = '/mnt/base' + item['target']
        version = {'native-watchdog': 'ram59', 'cold-ethernet': 'ram60', 'gen4-touch': 'ram64', 'mainline-ram': 'ram65', 'mainline-bus': 'ram66', 'display-dispc': 'ram67', 'display-pll': 'ram68', 'display-pll-only': 'ram69', 'display-onoff': 'ram70', 'display-align': 'ram71', 'dsi-hsync': 'ram72', 'dsi-late-video': 'ram73', 'dsi-standard-video': 'ram74', 'dsi-exact-lines': 'ram75', 'dsi-command-clock': 'ram76', 'bridge-regmap': 'ram77', 'bridge-reset': 'ram78', 'dsi-mainline-hbp': 'ram79'}[manifest['profile']]
        if not re.fullmatch(r'/mnt/base/touch10-dev/' + version + r'-[0-9a-f]{12}\.(zImage|dtb)', target):
            raise ValueError('Unexpected staging path')
        data = (ROOT / item['source']).read_bytes()
        if len(data) != item['bytes'] or sha(data) != item['sha256']:
            raise ValueError('The audited ' + name + ' changed')
        exists = panel.run(f'set -e\ntest ! -L {target}\nif [ -e {target} ]; then echo yes; else echo no; fi\n')
        if exists.returncode or exists.stdout.strip() not in ('yes', 'no'):
            raise RuntimeError('Cannot check the staged file')
        if exists.stdout.strip() == 'no':
            temporary = target + '.upload-' + uuid.uuid4().hex[:8]
            remote_bytes(panel, f'umask 077; cat > {temporary}', data)
            if remote_bytes(panel, 'cat ' + temporary) != data:
                panel.run('rm -f ' + temporary + '\n')
                raise RuntimeError('The staged upload differs from its source')
            commit = panel.run(f'set -eu\n[ ! -e {target} ]\nchmod 600 {temporary}\n'
                               f'mv {temporary} {target}\nsync\n')
            if commit.returncode:
                raise RuntimeError('Cannot commit the staged file')
        if remote_bytes(panel, 'cat ' + target) != data:
            raise RuntimeError('The final staged readback differs')
        staged[name] = dict(item, device_path=target)
    return staged


def ram_diagnostics(directory):
    result = ram.remote('''set -eu
test "$(cat /sys/block/mmcblk0/ro)" = 1
if grep -q '^/dev/mmcblk0' /proc/mounts; then exit 2; fi
uname -a
cat /proc/cmdline
cat /proc/mounts
cat /run/guard.json
cat /sys/class/watchdog/watchdog0/identity
cat /sys/class/watchdog/watchdog0/nowayout
cat /sys/class/watchdog/watchdog0/timeout
cat /sys/class/watchdog/watchdog0/timeleft
cat /proc/bus/input/devices
for path in /sys/class/thermal/thermal_zone*/temp /sys/class/hwmon/hwmon*/temp*_input /sys/class/backlight/*/brightness /sys/class/graphics/fb0/virtual_size; do
    [ -r "$path" ] || continue
    printf '%s=' "$path"
    cat "$path"
done
dmesg
''', timeout=20)
    (directory / 'ram-diagnostics.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError('RAM mounts or read-only storage verification failed')
    result = ram.remote('''set -eu
PERRIER_QT_DURATION_MS=0 PERRIER_TOUCH_X_MODE=direct PERRIER_TOUCH_X_OFFSET=0 \
    /usr/bin/qt-run > /tmp/qt-active.log 2>&1 < /dev/null &
pid=$!
echo "$pid" > /run/qt.pid
echo /qt/bin/perrier-touch-grid > /run/qt-app
ready_wait=0
while ! grep -q '^PERRIER_QT_EVDEV_READY ' /tmp/qt-active.log; do
    if ! kill -0 "$pid" || [ "$ready_wait" -ge 15 ]; then
        cat /tmp/qt-active.log
        exit 1
    fi
    sleep 1
    ready_wait=$((ready_wait+1))
done
if ! kill -0 "$pid"; then
    cat /tmp/qt-active.log
    exit 1
fi
cat /tmp/qt-active.log
''', timeout=25)
    (directory / 'qt-start.log').write_text(result.stdout + result.stderr)
    return result.returncode == 0 and 'PERRIER_QT_EVDEV_READY' in result.stdout


def session(args):
    # Refresh the independent audit before making any connection to hardware.
    subprocess.run([sys.executable, SOURCE / 'audit_uboot.py', '--profile', args.profile], check=True,
                   stdout=subprocess.DEVNULL)
    manifest_path = PLAN / 'oneshot-manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest['profile'] != args.profile:
        raise ValueError('The prepared candidate belongs to another image profile')
    audit = json.loads((PLAN / 'oneshot-audit.json').read_text())
    candidate = (PLAN / 'oneshot-p8.bin').read_bytes()
    original = (ROOT / manifest['source_p8']).read_bytes()
    checksum = sha(manifest_bytes)
    if not audit['passed'] or audit['manifest_sha256'] != checksum or \
       audit['candidate_p8_sha256'] != sha(candidate) or sha(original) != dev.STOCK_ENV_SHA256:
        raise ValueError('Candidate audit changed')
    used_path = PLAN / 'used-by.json'
    if used_path.exists() and json.loads(used_path.read_text())['manifest_sha256'] == checksum:
        raise ValueError('This one-use candidate was already armed; prepare a fresh candidate')
    with (ROOT / 'development/.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        directory = ROOT / 'development/runs' / (
            datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-uboot-' +
            manifest['kernel'].removeprefix('6.18.48-perrier-') + '-' + uuid.uuid4().hex[:6])
        directory.mkdir(parents=True)
        report = {'command': 'uboot-interactive', 'profile': args.profile, 'status': 'preflight',
                  'test_scope': 'kernel handoff, RAM SSH, watchdog, and factory recovery',
                  'started': dev.now(), 'host_pid': os.getpid(), 'directory': str(directory),
                  'manifest_sha256': checksum, 'candidate_p8_sha256': sha(candidate),
                  'guard_sha256': manifest['guard_sha256'], 'proof_run': args.prove_recovery,
                  'reset_mode': 'physical-power-cycle' if args.power_cycle else 'software-reboot'}

        def save():
            dev.write_json(directory / 'result.json', report)
            dev.write_json(ram.CURRENT, report)

        save()
        dev.validate_host(dev.host_checks())
        panel = dev.Panel(directory)
        before = panel.snapshot()
        report['before'] = before
        if before['kernel'] != '3.4.113+' or before['factory_app'] != 'running' or read_p8(panel) != original:
            raise RuntimeError('The exact factory boot state is required')
        report['staged'] = stage(panel, manifest)
        if read_p8(panel) != original:
            raise RuntimeError('P8 changed while staging files')
        save()
        print('UBOOT_READY logs=' + str(directory), flush=True)
        armed = False
        with dev.SerialCapture(dev.UART, directory) as serial:
            try:
                report['status'] = 'arming'
                dev.write_json(used_path, {'manifest_sha256': checksum, 'run': str(directory), 'time': dev.now()})
                save()
                try:
                    write_p8(panel, candidate)
                    if read_p8(panel) != candidate:
                        raise RuntimeError('The p8 candidate failed exact readback')
                except BaseException:
                    write_p8(panel, original)
                    report['original_restored'] = read_p8(panel) == original
                    save()
                    raise
                armed = True
                report['p8_candidate_verified'] = True
                if args.power_cycle:
                    report['status'] = 'awaiting-physical-power-cycle'
                    save()
                    print('POWER_CYCLE_READY: cycle PoE once; leave USB attached', flush=True)
                    deadline = time.monotonic() + args.arm_timeout
                    while time.monotonic() < deadline:
                        path = directory / 'serial.raw'
                        data = path.read_bytes() if path.exists() else b''
                        if b'PPA supports' in data or b'U-Boot 2013.04' in data:
                            report['boot_seen_on_serial'] = dev.now()
                            break
                        if serial.error:
                            raise RuntimeError('Serial capture failed: ' + serial.error)
                        time.sleep(0.5)
                    else:
                        raise TimeoutError('No power cycle observed in the arming window')
                else:
                    try:
                        report['reboot_ssh_exit'] = panel.run('reboot\n', timeout=20).returncode
                    except subprocess.TimeoutExpired:
                        report['reboot_ssh_exit'] = 'ssh-timeout'
                    report['reboot_requested'] = dev.now()
                report['status'] = 'booting'
                save()
                deadline = time.monotonic() + 90
                while True:
                    try:
                        state = ram.ram_state(manifest['kernel'])
                        break
                    except (RuntimeError, subprocess.TimeoutExpired):
                        if time.monotonic() >= deadline:
                            raise RuntimeError('RAM SSH startup deadline exceeded')
                        time.sleep(2)
                if state['guard'].get('backend') != 'linux-watchdog' or \
                   not state['guard'].get('nowayout') or state['guard']['timeout_seconds'] != 120:
                    raise RuntimeError('The mainline watchdog is not feeding as audited')
                report['ram'] = state
                p8 = ram.remote('dd if=/dev/mmcblk0p8 bs=262144 count=1\n', binary=True)
                if p8.returncode or p8.stdout != original:
                    raise RuntimeError('U-Boot did not restore the exact factory p8 before handoff')
                report['factory_environment_restored_before_userspace'] = True
                report['qt_started'] = ram_diagnostics(directory)
                report['ready_at'] = dev.now()
                report['status'] = 'interactive'
                save()
                print('RAM_READY kernel=' + state['kernel'] + ' qt_started=' + str(report['qt_started']), flush=True)
                deadline = time.monotonic() + (130 if args.prove_recovery else args.minutes * 60)
                reason = 'lease_complete'
                while time.monotonic() < deadline:
                    request = directory / 'recover-request.json'
                    if request.exists():
                        reason = json.loads(request.read_text())['mode']
                        break
                    state = ram.ram_state(manifest['kernel'])
                    if state['boot_id'] != report['ram']['boot_id']:
                        raise RuntimeError('RAM boot identity changed')
                    report['last_guard'] = state['guard']
                    report['last_lease_at'] = dev.now()
                    save()
                    time.sleep(10)
                if args.prove_recovery:
                    if report['last_guard']['pings'] < 20:
                        raise RuntimeError('The feeder did not survive a full watchdog interval')
                    reason = 'hardware_expiry'
                report['status'] = 'recovering'
                report['recovery_reason'] = reason
                report['recovery_started'] = dev.now()
                save()
                command = 'expire' if reason == 'hardware_expiry' else 'reboot'
                try:
                    ram.remote('/usr/sbin/ram-guard ' + command + '\n')
                except subprocess.TimeoutExpired:
                    pass
                print('RECOVERY_WAIT reason=' + reason, flush=True)
                recovery_start = time.monotonic()
                report['after'] = dev.wait_for_stock(panel, before, timeout=args.timeout)
                report['recovery_elapsed_seconds'] = round(time.monotonic() - recovery_start, 1)
                report['stock_p8_sha256'] = sha(read_p8(panel))
                if report['stock_p8_sha256'] != dev.STOCK_ENV_SHA256:
                    raise RuntimeError('Factory environment differs after recovery')
                if args.prove_recovery and report['recovery_elapsed_seconds'] < 100:
                    raise RuntimeError('Reset happened before the expected hardware watchdog expiry')
                time.sleep(1)
                raw = (directory / 'serial.raw').read_bytes()
                report['markers'], report['serial_markers_reconstructed'] = \
                    serial_handoff_markers(raw, manifest['kernel'])
                if not all(report['markers'].values()) or serial.error:
                    raise RuntimeError('Serial handoff evidence is incomplete')
                report['stock_recovered'] = True
                report['status'] = 'passed'
                if args.prove_recovery:
                    dev.write_json(PLAN / 'watchdog-proof.json', report)
                print('STOCK_RECOVERED factory_environment_restored=1', flush=True)
            except BaseException as exc:
                report['status'] = 'failed'
                report['error'] = str(exc)
                save()
                # Stop renewing the lease. Disarm only if the original stock
                # boot is still alive; otherwise observe recovery, never retry reset.
                try:
                    current = panel.snapshot()
                except (RuntimeError, subprocess.TimeoutExpired):
                    current = None
                try:
                    if current and current['boot_id'] == before['boot_id']:
                        if armed:
                            actual = read_p8(panel)
                            if actual == candidate:
                                write_p8(panel, original)
                            report['original_restored'] = read_p8(panel) == original
                        report['after'] = current
                    elif armed:
                        report['after'] = dev.wait_for_stock(panel, before, timeout=args.timeout)
                        report['stock_p8_sha256'] = sha(read_p8(panel))
                        report['stock_recovered'] = report['stock_p8_sha256'] == dev.STOCK_ENV_SHA256
                except Exception as recovery:
                    report['recovery_error'] = str(recovery)
                raise
            finally:
                path = directory / 'serial.raw'
                if 'markers' not in report and path.exists():
                    raw = path.read_bytes()
                    report['markers'] = {
                        'factory_saved_before_handoff': b'PERRIER_ONESHOT_SAVED' in raw,
                        'candidate_kernel': ('Linux version ' + manifest['kernel']).encode() in raw,
                        'mainline_watchdog_ready': b'PERRIER_GUARD_READY backend=linux-watchdog' in raw,
                    }
                report['finished'] = dev.now()
                report['serial_error'] = serial.error
                save()


def main():
    global IMAGE, PLAN
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare', help='prepare and audit a fresh one-use candidate entirely offline')
    prepare.add_argument('--profile', choices=('native-watchdog', 'cold-ethernet', 'gen4-touch', 'mainline-ram', 'mainline-bus', 'display-dispc', 'display-pll', 'display-pll-only', 'display-onoff', 'display-align', 'dsi-hsync', 'dsi-late-video', 'dsi-standard-video', 'dsi-exact-lines', 'dsi-command-clock', 'bridge-regmap', 'bridge-reset', 'dsi-mainline-hbp'), default=DEFAULT_PROFILE)
    run = sub.add_parser('session', help='stage files, write p8 once, boot, maintain lease, and recover')
    run.add_argument('--minutes', type=int, default=5)
    run.add_argument('--profile', choices=('native-watchdog', 'cold-ethernet', 'gen4-touch', 'mainline-ram', 'mainline-bus', 'display-dispc', 'display-pll', 'display-pll-only', 'display-onoff', 'display-align', 'dsi-hsync', 'dsi-late-video', 'dsi-standard-video', 'dsi-exact-lines', 'dsi-command-clock', 'bridge-regmap', 'bridge-reset', 'dsi-mainline-hbp'), default=DEFAULT_PROFILE)
    run.add_argument('--prove-recovery', action='store_true')
    run.add_argument('--power-cycle', action='store_true')
    run.add_argument('--arm-timeout', type=int, default=900)
    run.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    IMAGE = ROOT / 'development/perrier-ramenv' / args.profile
    PLAN = IMAGE / 'uboot'
    if args.command == 'prepare':
        for name in ('prepare_uboot.py', 'audit_uboot.py'):
            subprocess.run([sys.executable, SOURCE / name, '--profile', args.profile], check=True)
    else:
        if not 1 <= args.minutes <= 480 or not 120 <= args.arm_timeout <= 3600 or not 180 <= args.timeout <= 600:
            parser.error('minutes must be 1..480, arm-timeout 120..3600, timeout 180..600')
        session(args)


if __name__ == '__main__':
    main()
