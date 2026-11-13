#!/usr/bin/env python3
"""Interactive Perrier RAM sessions with a host lease and watchdog recovery."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import libfdt
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import uuid
import runpy
import touch10_dev as dev

ROOT = dev.ROOT
ENV = ROOT/'development/perrier-ramenv'
CURRENT = ENV/'current-session.json'
SSH = ['ssh','-F',str(dev.SSH_CONFIG),'touch10-ram']

def remote(script, timeout=12, binary=False):
    return subprocess.run(SSH+['sh -s'],input=script.encode() if binary else script,
                          capture_output=True,text=not binary,timeout=timeout)

def ram_state(expected_kernel=None):
    r=remote('set -e\ncat /run/touch10-ram\nuname -r\ncat /proc/sys/kernel/random/boot_id\n/usr/sbin/ram-guard renew\ncat /run/guard.json\n')
    if r.returncode: raise RuntimeError('RAM SSH is not ready: '+r.stderr.strip())
    lines=r.stdout.splitlines()
    kernels={'perrier-interactive-ram44':'6.18.48-perrier-ram44',
             'perrier-interactive-ram45':'6.18.48-perrier-ram45',
             'perrier-interactive-ram46':'6.18.48-perrier-ram46',
             'perrier-interactive-ram47':'6.18.48-perrier-ram47',
             'perrier-interactive-ram48':'6.18.48-perrier-ram48',
             'perrier-interactive-ram49':'6.18.48-perrier-ram49',
             'perrier-interactive-ram50':'6.18.48-perrier-ram50',
             'perrier-interactive-ram51':'6.18.48-perrier-ram51',
             'perrier-interactive-ram52':'6.18.48-perrier-ram52',
             'perrier-interactive-ram53':'6.18.48-perrier-ram53',
             'perrier-interactive-ram54':'6.18.48-perrier-ram54',
             'perrier-interactive-ram55':'6.18.48-perrier-ram55',
             'perrier-interactive-ram56':'6.18.48-perrier-ram56',
             'perrier-interactive-ram57':'6.18.48-perrier-ram57',
             'perrier-interactive-ram58':'6.18.48-perrier-ram58',
             'perrier-interactive-ram59':'6.18.48-perrier-ram59',
             'perrier-interactive-ram60':'6.18.48-perrier-ram60',
             'perrier-interactive-ram61':'6.18.48-perrier-ram61',
             'perrier-interactive-ram62':'6.18.48-perrier-ram62',
             'perrier-interactive-ram63':'6.18.48-perrier-ram63',
             'perrier-interactive-ram64':'6.18.48-perrier-ram64',
             'perrier-interactive-ram65':'6.18.48-perrier-ram65',
             'perrier-interactive-ram66':'6.18.48-perrier-ram66',
             'perrier-interactive-ram67':'6.18.48-perrier-ram67',
             'perrier-interactive-ram68':'6.18.48-perrier-ram68',
             'perrier-interactive-ram69':'6.18.48-perrier-ram69',
             'perrier-interactive-ram70':'6.18.48-perrier-ram70',
             'perrier-interactive-ram71':'6.18.48-perrier-ram71',
             'perrier-interactive-ram72':'6.18.48-perrier-ram72',
             'perrier-interactive-ram73':'6.18.48-perrier-ram73',
             'perrier-interactive-ram74':'6.18.48-perrier-ram74',
             'perrier-interactive-ram75':'6.18.48-perrier-ram75',
             'perrier-interactive-ram76':'6.18.48-perrier-ram76',
             'perrier-interactive-ram77':'6.18.48-perrier-ram77',
             'perrier-interactive-ram78':'6.18.48-perrier-ram78',
             'perrier-interactive-ram79':'6.18.48-perrier-ram79',
             'perrier-interactive-ram80':'6.18.48-perrier-ram80',
             'perrier-interactive-ram81':'6.18.48-perrier-ram81',
             'perrier-interactive-ram85':'6.18.48-perrier-ram85',
             'perrier-interactive-ram86':'6.18.48-perrier-ram86',
             'perrier-interactive-ram87':'6.18.48-perrier-ram87',
             'perrier-interactive-ram88':'6.18.48-perrier-ram88',
             'perrier-interactive-ram89':'6.18.48-perrier-ram89',
             'perrier-interactive-ram90':'6.18.48-perrier-ram90',
             'perrier-interactive-ram91':'6.18.48-perrier-ram91',
             'perrier-interactive-ram92':'6.18.48-perrier-ram92',
             'perrier-interactive-ram93':'6.18.48-perrier-ram93',
             'perrier-interactive-ram94':'6.18.48-perrier-ram94',
             'perrier-interactive-ram95':'6.18.48-perrier-ram95',
             'perrier-interactive-ram96':'6.18.48-perrier-ram96',
             'perrier-interactive-ram97':'6.18.48-perrier-ram97',
             'perrier-interactive-ram98':'6.18.48-perrier-ram98',
             'perrier-interactive-ram99':'6.18.48-perrier-ram99',
             'perrier-interactive-ram100':'6.18.48-perrier-ram100',
             'perrier-interactive-ram101':'6.18.48-perrier-ram101'}
    if len(lines)!=4 or kernels.get(lines[0])!=lines[1] or (expected_kernel and lines[1]!=expected_kernel):
        raise RuntimeError('Unexpected RAM environment identity')
    state=json.loads(lines[3])
    if state['state']!='feeding': raise RuntimeError('RAM watchdog is not feeding: '+str(state))
    return {'marker':lines[0],'kernel':lines[1],'boot_id':lines[2],'guard':state}

def artifacts(profile='clockfix'):
    image_dir={'clockfix':ENV,
               'native-touch':ENV/'native-touch',
               'native-backlight':ENV/'native-backlight',
               'native-keypad':ENV/'native-keypad',
               'keypad-newqt':ENV/'native-keypad-newqt',
               'native-thermal':ENV/'native-thermal',
               'native-watchdog':ENV/'native-watchdog',
               'cold-ethernet':ENV/'cold-ethernet',
               'gen4-touch':ENV/'gen4-touch',
               'mainline-ram':ENV/'mainline-ram',
               'mainline-bus':ENV/'mainline-bus',
               'display-dispc':ENV/'display-dispc',
               'display-pll':ENV/'display-pll',
               'display-pll-only':ENV/'display-pll-only',
               'display-onoff':ENV/'display-onoff',
               'display-align':ENV/'display-align',
               'dsi-hsync':ENV/'dsi-hsync',
               'dsi-late-video':ENV/'dsi-late-video',
               'dsi-standard-video':ENV/'dsi-standard-video',
               'dsi-exact-lines':ENV/'dsi-exact-lines',
               'dsi-command-clock':ENV/'dsi-command-clock',
               'bridge-regmap':ENV/'bridge-regmap',
               'bridge-reset':ENV/'bridge-reset',
               'dsi-mainline-hbp':ENV/'dsi-mainline-hbp',
               'dsi-mainline-porches':ENV/'dsi-mainline-porches',
               'dsi-mainline-pads':ENV/'dsi-mainline-pads',
               'bridge-clock-order':ENV/'bridge-clock-order',
               'display-hbp':ENV/'display-hbp',
               'display-porches':ENV/'display-porches',
               'display-pads':ENV/'display-pads',
               'display-sync-align':ENV/'display-sync-align',
               'display-core-fck':ENV/'display-core-fck',
               'display-mainline-sync':ENV/'display-mainline-sync',
               'display-stop-trace':ENV/'display-stop-trace',
               'display-stop-fix':ENV/'display-stop-fix',
               'native-leds':ENV/'native-leds',
               'peripherals':ENV/'peripherals',
               'rtc-gpio':ENV/'rtc-gpio',
               'native-audio':ENV/'native-audio',
               'application-audio':ENV/'application-audio',
               'speaker-audio':ENV/'speaker-audio',
               'native-diagnostics':ENV/'native-diagnostics',
               'pmu-probe':ENV/'pmu-probe',
               'native-smp':ENV/'native-smp',
               'smp-onecpu':ENV/'native-smp-onecpu',
               'smp-sync':ENV/'native-smp-sync',
               'smp-nosmp':ENV/'native-smp-nosmp'}[profile]
    audit=json.loads((image_dir/'reviewed-image.json').read_text())
    if not audit.get('passed'): raise RuntimeError('RAM image audit did not pass')
    expected={'clockfix':'6.18.48-perrier-ram44',
              'native-touch':'6.18.48-perrier-ram50',
              'native-backlight':'6.18.48-perrier-ram51',
              'native-keypad':'6.18.48-perrier-ram52',
              'keypad-newqt':'6.18.48-perrier-ram57',
              'native-thermal':'6.18.48-perrier-ram58',
              'native-watchdog':'6.18.48-perrier-ram59',
              'cold-ethernet':'6.18.48-perrier-ram60',
              'gen4-touch':'6.18.48-perrier-ram64',
              'mainline-ram':'6.18.48-perrier-ram65',
              'mainline-bus':'6.18.48-perrier-ram66',
              'display-dispc':'6.18.48-perrier-ram67',
              'display-pll':'6.18.48-perrier-ram68',
              'display-pll-only':'6.18.48-perrier-ram69',
              'display-onoff':'6.18.48-perrier-ram70',
              'display-align':'6.18.48-perrier-ram71',
              'dsi-hsync':'6.18.48-perrier-ram72',
              'dsi-late-video':'6.18.48-perrier-ram73',
              'dsi-standard-video':'6.18.48-perrier-ram74',
              'dsi-exact-lines':'6.18.48-perrier-ram75',
              'dsi-command-clock':'6.18.48-perrier-ram76',
              'bridge-regmap':'6.18.48-perrier-ram77',
              'bridge-reset':'6.18.48-perrier-ram78',
              'dsi-mainline-hbp':'6.18.48-perrier-ram79',
              'dsi-mainline-porches':'6.18.48-perrier-ram80',
              'dsi-mainline-pads':'6.18.48-perrier-ram81',
              'bridge-clock-order':'6.18.48-perrier-ram85',
              'display-hbp':'6.18.48-perrier-ram86',
              'display-porches':'6.18.48-perrier-ram87',
              'display-pads':'6.18.48-perrier-ram88',
              'display-sync-align':'6.18.48-perrier-ram89',
              'display-core-fck':'6.18.48-perrier-ram90',
              'display-mainline-sync':'6.18.48-perrier-ram91',
              'display-stop-trace':'6.18.48-perrier-ram92',
              'display-stop-fix':'6.18.48-perrier-ram93',
              'native-leds':'6.18.48-perrier-ram94',
              'peripherals':'6.18.48-perrier-ram95',
              'rtc-gpio':'6.18.48-perrier-ram96',
              'native-audio':'6.18.48-perrier-ram97',
              'application-audio':'6.18.48-perrier-ram98',
              'speaker-audio':'6.18.48-perrier-ram99',
              'native-diagnostics':'6.18.48-perrier-ram100',
              'pmu-probe':'6.18.48-perrier-ram101',
              'native-smp':'6.18.48-perrier-ram53',
              'smp-onecpu':'6.18.48-perrier-ram54',
              'smp-sync':'6.18.48-perrier-ram55',
              'smp-nosmp':'6.18.48-perrier-ram56'}[profile]
    if audit['kernel'] != expected:
        raise RuntimeError('Unexpected image profile or kernel release')
    files={n:Path(v['path']) for n,v in audit['artifacts'].items()}
    for n,p in files.items():
        if hashlib.sha256(p.read_bytes()).hexdigest()!=audit['artifacts'][n]['sha256']:
            raise RuntimeError('RAM artifact changed after audit: '+n)
    return audit,files

def watchdog_proof_path(audit):
    if audit.get('watchdog_backend') == 'linux-watchdog':
        return ENV/'native-watchdog/watchdog-proof.json'
    return ENV/'watchdog-proof.json'

def seeded_board_dtb(source: Path, destination: Path):
    """Supply fresh host entropy through the standard one-shot FDT property."""
    parse=runpy.run_path(str(ROOT/'development/perrier-simpledrm/audit.py'))['fdt_nodes']
    original=source.read_bytes()
    before=parse(original)
    assert 'rng-seed' not in before['/chosen']
    seed=os.getrandom(64)
    assert len(seed)==64
    fdt=libfdt.Fdt(original)
    fdt.resize(len(original)+4096)
    fdt.setprop(fdt.path_offset('/chosen'),'rng-seed',seed)
    fdt.pack()
    result=bytes(fdt.as_bytearray()[:fdt.totalsize()])
    after=parse(result)
    assert after['/chosen']['rng-seed']==seed
    for path,properties in before.items():
        assert {k:v for k,v in after[path].items() if k!='rng-seed'}==properties,path
    assert set(before)==set(after)
    destination.write_bytes(result)
    destination.chmod(0o600)
    return hashlib.sha256(result).hexdigest()

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

def restart_qt(source: Path, mirror_x: bool = False, offset_x: int = 0):
    if not -300 <= offset_x <= 300:
        raise ValueError('Qt horizontal offset must be within -300..300 pixels')
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
    /usr/bin/qt-run > /tmp/qt-active.log 2>&1 < /dev/null &
pid=$!
echo "$pid" > /run/qt.pid
echo {shlex.quote(destination)} > /run/qt-app
ready_wait=0
while ! grep -q '^PERRIER_QT_EVDEV_READY ' /tmp/qt-active.log; do
    if ! kill -0 "$pid" || [ "$ready_wait" -ge 15 ]; then
        cat /tmp/qt-active.log
        exit 5
    fi
    sleep 1
    ready_wait=$((ready_wait+1))
done
kill -0 "$pid"
cat /tmp/qt-active.log
echo qt_pid="$pid"
cat /proc/sys/kernel/random/boot_id
'''
    r=remote(script,timeout=25)
    if r.returncode or 'PERRIER_QT_EVDEV_READY' not in r.stdout:
        raise RuntimeError('Qt restart failed: '+r.stdout+'\n'+r.stderr)
    print(r.stdout,end='')

def session(args):
    os.umask(0o077)
    audit,files=artifacts(args.profile)
    if not args.prove_recovery:
        proof=json.loads(watchdog_proof_path(audit).read_text())
        if proof.get('status')!='passed' or proof['guard_sha256']!=audit['guard_sha256']:
            raise RuntimeError('The RAM feeder needs its hardware expiry proof first')
    with (ROOT/'development/.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        directory=ROOT/'development/runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-interactive-'+uuid.uuid4().hex[:6])
        directory.mkdir(parents=True)
        report={'command':'interactive-ram','profile':args.profile,'status':'booting','started':dev.now(),
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
                boot_files=files.copy()
                seed_path=directory/'one-time-seeded-board.dtb'
                if args.profile in ('native-touch','native-backlight','native-keypad','keypad-newqt','native-thermal','native-watchdog','cold-ethernet','gen4-touch','mainline-ram','mainline-bus','display-dispc','display-pll','display-pll-only','display-onoff','display-align','dsi-hsync','dsi-late-video','dsi-standard-video','dsi-exact-lines','dsi-command-clock','bridge-regmap','bridge-reset','dsi-mainline-hbp','dsi-mainline-porches','dsi-mainline-pads','bridge-clock-order','display-hbp','display-porches','display-pads','display-sync-align','display-core-fck','display-mainline-sync','display-stop-trace','display-stop-fix','native-leds','peripherals','rtc-gpio','native-audio','application-audio','speaker-audio','native-diagnostics','pmu-probe','native-smp','smp-onecpu','smp-sync','smp-nosmp'):
                    report['boot_dtb_sha256']=seeded_board_dtb(files['board.dtb'],seed_path)
                    report['entropy_source']='host getrandom(64) via one-time FDT rng-seed'
                    boot_files['board.dtb']=seed_path
                    save()
                try:
                    dev.armed_watchdog_request(panel,report,True,perrier=True,candidate_files=boot_files)
                finally:
                    seed_path.unlink(missing_ok=True)
                deadline=time.monotonic()+90
                while True:
                    try:
                        state=ram_state(audit['kernel'])
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
                        state=ram_state(audit['kernel'])
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
                    dev.write_json(watchdog_proof_path(audit),report)
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
    boot.add_argument('--profile',choices=('clockfix','native-touch','native-backlight','native-keypad','keypad-newqt','native-thermal','native-watchdog','cold-ethernet','gen4-touch','mainline-ram','mainline-bus','display-dispc','display-pll','display-pll-only','display-onoff','display-align','dsi-hsync','dsi-late-video','dsi-standard-video','dsi-exact-lines','dsi-command-clock','bridge-regmap','bridge-reset','dsi-mainline-hbp','dsi-mainline-porches','dsi-mainline-pads','bridge-clock-order','display-hbp','display-porches','display-pads','display-sync-align','display-core-fck','display-mainline-sync','display-stop-trace','display-stop-fix','native-leds','peripherals','rtc-gpio','native-audio','application-audio','speaker-audio','native-diagnostics','pmu-probe','native-smp','smp-onecpu','smp-sync','smp-nosmp'),default='clockfix')
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
        restart_qt(args.source,args.mirror_x,args.x_offset)

if __name__=='__main__': main()
