#!/usr/bin/env python3
"""Interactive Perrier RAM sessions with a host lease and watchdog recovery."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import uuid
import touch10_dev as dev

ROOT = dev.ROOT
ENV = ROOT/'development/perrier-ramenv'
CURRENT = ENV/'current-session.json'
SSH = ['ssh','-F',str(dev.SSH_CONFIG),'touch10-ram']

def remote(script, timeout=12, binary=False):
    return subprocess.run(SSH+['sh -s'],input=script.encode() if binary else script,
                          capture_output=True,text=not binary,timeout=timeout)

def ram_state():
    r=remote('set -e\ncat /run/touch10-ram\nuname -r\ncat /proc/sys/kernel/random/boot_id\n/usr/sbin/ram-guard renew\ncat /run/guard.json\n')
    if r.returncode: raise RuntimeError('RAM SSH is not ready: '+r.stderr.strip())
    lines=r.stdout.splitlines()
    if len(lines)!=4 or lines[0]!='perrier-interactive-ram44' or lines[1]!='6.18.48-perrier-ram44':
        raise RuntimeError('Unexpected RAM environment identity')
    state=json.loads(lines[3])
    if state['state']!='feeding': raise RuntimeError('RAM watchdog is not feeding: '+str(state))
    return {'marker':lines[0],'kernel':lines[1],'boot_id':lines[2],'guard':state}

def artifacts():
    audit=json.loads((ENV/'reviewed-image.json').read_text())
    if not audit.get('passed'): raise RuntimeError('RAM image audit did not pass')
    files={n:Path(v['path']) for n,v in audit['artifacts'].items()}
    for n,p in files.items():
        if hashlib.sha256(p.read_bytes()).hexdigest()!=audit['artifacts'][n]['sha256']:
            raise RuntimeError('RAM artifact changed after audit: '+n)
    return audit,files

def push_file(source: Path, destination: str):
    ram_state()
    if not destination.startswith('/tmp/') or '..' in Path(destination).parts:
        raise RuntimeError('push destinations must be under RAM /tmp')
    data=source.read_bytes()
    expected=hashlib.sha256(data).hexdigest()
    dest=shlex.quote(destination)
    temp=shlex.quote(destination+'.upload-'+uuid.uuid4().hex[:8])
    r=subprocess.run(SSH+[f'umask 077; cat > {temp} && sha256sum {temp}'],
                     input=data,capture_output=True,timeout=120)
    fields=r.stdout.split()
    if r.returncode or not fields or fields[0].decode()!=expected: raise RuntimeError('Upload hash mismatch')
    r=remote(f'chmod 700 {temp}\nmv {temp} {dest}\n')
    if r.returncode: raise RuntimeError(r.stderr)
    print('Uploaded and verified',len(data),'bytes to',destination,flush=True)

def restart_qt(source: Path, mirror_x: bool = False, offset_x: int = 0,
               center_x: int = 640, display_shift_x: int = 0):
    if not -300 <= offset_x <= 300:
        raise ValueError('Qt horizontal offset must be within -300..300 pixels')
    if not 20 <= center_x <= 1259:
        raise ValueError('Qt center target must be within 20..1259')
    if not -300 <= display_shift_x <= 300:
        raise ValueError('Qt display shift must be within -300..300 pixels')
    data=source.read_bytes()
    destination='/tmp/grid-'+hashlib.sha256(data).hexdigest()[:16]
    push_file(source,destination)
    script=f'''set -eu
if [ -f /run/qt.pid ]; then
    pid=$(cat /run/qt.pid)
    case "$pid" in ''|*[!0-9]*) exit 2;; esac
    if [ -e /proc/$pid/exe ]; then
        old=$(readlink /proc/$pid/exe)
        case "$old" in /tmp/grid-*|/qt/bin/perrier-touch-grid) kill -TERM "$pid";; *) exit 3;; esac
        i=0
        while [ -e /proc/$pid/exe ] && [ "$i" -lt 50 ]; do sleep 0.1; i=$((i+1)); done
        [ ! -e /proc/$pid/exe ] || exit 4
    fi
fi
QT_QPA_FB_DISABLE_INPUT=1 PERRIER_QT_DURATION_MS=0 PERRIER_QT_APP={shlex.quote(destination)} \
    PERRIER_TOUCH_X_MODE={'mirror' if mirror_x else 'direct'} PERRIER_TOUCH_X_OFFSET={offset_x} \
    PERRIER_QT_CENTER_X={center_x} PERRIER_QT_DISPLAY_SHIFT_X={display_shift_x} \
    /usr/bin/qt-run > /tmp/qt-active.log 2>&1 < /dev/null &
pid=$!
echo "$pid" > /run/qt.pid
echo {shlex.quote(destination)} > /run/qt-app
sleep 2
kill -0 "$pid"
cat /tmp/qt-active.log
echo qt_pid="$pid"
cat /proc/sys/kernel/random/boot_id
'''
    r=remote(script,timeout=15)
    if r.returncode or 'PERRIER_QT_EVDEV_READY' not in r.stdout:
        raise RuntimeError('Qt restart failed: '+r.stdout+'\n'+r.stderr)
    print(r.stdout,end='')

def session(args):
    os.umask(0o077)
    audit,files=artifacts()
    if not args.prove_recovery:
        proof=json.loads((ENV/'watchdog-proof.json').read_text())
        if proof.get('status')!='passed' or proof['guard_sha256']!=audit['guard_sha256']:
            raise RuntimeError('The RAM feeder needs its hardware expiry proof first')
    with (ROOT/'development/.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        directory=ROOT/'development/runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-interactive-'+uuid.uuid4().hex[:6])
        directory.mkdir(parents=True)
        report={'command':'interactive-ram','status':'booting','started':dev.now(),
                'host_pid':os.getpid(),'directory':str(directory),'guard_sha256':audit['guard_sha256'],
                'proof_run':args.prove_recovery,'artifacts':audit['artifacts']}
        def save():
            dev.write_json(directory/'result.json',report)
            dev.write_json(CURRENT,report)
        save()
        panel=dev.Panel(directory)
        checks=dev.host_checks()
        dev.validate_host(checks)
        report['before']=panel.snapshot()
        if report['before']['kernel']!='3.4.113+': raise RuntimeError('Boot requires the stock system')
        report['environment_before']=panel.env_hash()
        if report['environment_before']!=dev.STOCK_ENV_SHA256: raise RuntimeError('Stock environment changed')
        dev.display_handoff_check(panel,report)
        print('Logs:',directory,flush=True)
        with dev.SerialCapture(dev.UART,directory) as serial:
            try:
                dev.armed_watchdog_request(panel,report,True,perrier=True,candidate_files=files)
                deadline=time.monotonic()+90
                while True:
                    try:
                        state=ram_state()
                        break
                    except (RuntimeError,subprocess.TimeoutExpired):
                        if time.monotonic()>deadline: raise RuntimeError('RAM SSH startup deadline exceeded')
                        time.sleep(2)
                report['ram']=state
                report['status']='interactive'
                report['ready_at']=dev.now()
                report['hold_minutes']=args.minutes
                save()
                print('RAM_READY kernel='+state['kernel']+' boot_id='+state['boot_id'],flush=True)
                start=time.monotonic()
                deadline=start+(130 if args.prove_recovery else args.minutes*60)
                failures=0
                reason='lease_complete'
                while time.monotonic()<deadline:
                    request=directory/'recover-request.json'
                    if request.exists():
                        reason=json.loads(request.read_text())['mode']
                        break
                    try:
                        state=ram_state()
                        if state['boot_id']!=report['ram']['boot_id']: raise RuntimeError('RAM boot identity changed')
                        report['last_guard']=state['guard']
                        report['last_lease_at']=dev.now()
                        save()
                        failures=0
                    except (RuntimeError,subprocess.TimeoutExpired) as exc:
                        failures+=1
                        report['last_lease_error']=str(exc)
                        if failures>=3:
                            reason='connection_lost'
                            break
                    time.sleep(10)
                if args.prove_recovery:
                    if report.get('last_guard',{}).get('pings',0)<20:
                        raise RuntimeError('Feeder did not survive the initial watchdog interval')
                    reason='hardware_expiry'
                report['status']='recovering'
                report['recovery_reason']=reason
                report['recovery_started']=dev.now()
                save()
                if reason!='connection_lost':
                    command='expire' if reason=='hardware_expiry' else 'reboot'
                    try: remote('/usr/sbin/ram-guard '+command+'\n')
                    except subprocess.TimeoutExpired: pass
                print('RECOVERY_WAIT reason='+reason,flush=True)
                recovery_start=time.monotonic()
                report['after']=dev.wait_for_stock(panel,report['before'],timeout=300)
                report['recovery_elapsed_seconds']=round(time.monotonic()-recovery_start,1)
                report['environment_after']=panel.env_hash()
                report['stock_recovered']=True
                if report['environment_after']!=report['environment_before']:
                    raise RuntimeError('Environment hash changed')
                if args.prove_recovery and report['recovery_elapsed_seconds']<100:
                    raise RuntimeError('Stock returned before the expected hardware watchdog expiry')
                report['status']='passed'
                if args.prove_recovery:
                    report['guard_sha256']=audit['guard_sha256']
                    dev.write_json(ENV/'watchdog-proof.json',report)
                print('STOCK_RECOVERED environment_unchanged=1',flush=True)
            except BaseException as exc:
                report['status']='failed'
                report['error']=str(exc)
                save()
                # No more leases: guard requests stock reboot; WDT covers a stuck kernel.
                try:
                    if 'ram_stage' not in report:
                        report['after']=panel.snapshot()
                    else:
                        report['after']=dev.wait_for_stock(panel,report['before'],timeout=300)
                    report['environment_after']=panel.env_hash()
                    report['stock_recovered']=True
                except Exception as recovery:
                    report['recovery_error']=str(recovery)
                raise
            finally:
                report['finished']=dev.now()
                report['serial_error']=serial.error
                save()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    boot=sub.add_parser('session')
    boot.add_argument('--minutes',type=int,default=120)
    boot.add_argument('--prove-recovery',action='store_true')
    sub.add_parser('status')
    recovery=sub.add_parser('recover')
    recovery.add_argument('--hardware',action='store_true')
    push=sub.add_parser('push')
    push.add_argument('source',type=Path)
    push.add_argument('destination')
    qt=sub.add_parser('qt-restart')
    qt.add_argument('source',type=Path,nargs='?',
                    default=ROOT/'development/perrier-qt/build-arm-a9-local/perrier-touch-grid')
    qt.add_argument('--mirror-x',action='store_true')
    qt.add_argument('--x-offset',type=int,default=0)
    qt.add_argument('--center-x',type=int,default=640)
    qt.add_argument('--display-shift-x',type=int,default=0)
    args=p.parse_args()
    if args.command=='session':
        if not 1<=args.minutes<=480: p.error('Session duration must be 1..480 minutes')
        session(args)
    elif args.command=='status':
        print(json.dumps(ram_state(),indent=2))
    elif args.command=='recover':
        current=json.loads(CURRENT.read_text())
        if current['status']!='interactive': raise RuntimeError('No interactive session is active')
        dev.write_json(Path(current['directory'])/'recover-request.json',
                       {'mode':'hardware_expiry' if args.hardware else 'requested_reboot'})
        print('Recovery requested; the session controller will verify stock boot')
    elif args.command=='push':
        push_file(args.source,args.destination)
    elif args.command=='qt-restart':
        restart_qt(args.source,args.mirror_x,args.x_offset,args.center_x,args.display_shift_x)

if __name__=='__main__': main()
