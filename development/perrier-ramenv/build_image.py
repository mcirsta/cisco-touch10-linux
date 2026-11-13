#!/usr/bin/env python3
"""Package the interactive RAM environment using the reviewed Perrier board."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NATIVE = ROOT / 'development/perrier-native'
SRC = ROOT / 'development/sources/linux-6.18.48'
OUT = HERE / 'kernel-build'
FS = HERE / 'rootfs'
VERSION = '6.18.48-perrier-ram44'
DEST = HERE
PROFILE = 'clockfix'
TOUCH = ROOT / 'development/perrier-touch'
BACKLIGHT = ROOT / 'development/perrier-backlight'
KEYPAD = ROOT / 'development/perrier-keypad'
SMP = ROOT / 'development/perrier-smp'
THERMAL = ROOT / 'development/perrier-thermal'
TC = ROOT / 'development/perrier-qt/sources/armv7-eabihf--musl--stable-2026.08-1'
PREFIX = str(TC / 'bin/arm-buildroot-linux-musleabihf-')
spec = importlib.util.spec_from_file_location('native_build', NATIVE / 'build.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
SOFTWARE = ('BINFMT_SCRIPT', 'UNIX98_PTYS', 'EPOLL', 'SIGNALFD', 'TIMERFD',
            'EVENTFD', 'UNIX', 'SYSCTL', 'PROC_SYSCTL', 'SYSVIPC', 'INOTIFY_USER', 'FHANDLE',
            'ADVISE_SYSCALLS', 'COREDUMP', 'PACKET', 'MULTIUSER', 'IKCONFIG', 'IKCONFIG_PROC',
            'FILE_LOCKING')

def run(args, **kw):
    return subprocess.run([str(a) for a in args], check=True, **kw)

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def put(name, content, mode=0o644):
    p = FS / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    p.chmod(mode)

def copy(source, name, executable=False):
    p = FS / name
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, p)
    if executable:
        p.chmod(0o755)
        run([PREFIX+'strip', '--strip-unneeded', p])

def link(name, target):
    p = FS / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.symlink_to(target)

def stage():
    if FS.exists(): shutil.rmtree(FS)
    FS.mkdir(mode=0o700)
    for name in ('dev', 'proc', 'sys', 'run', 'tmp', 'root', 'etc/dropbear', 'bin', 'sbin', 'usr/bin', 'usr/sbin'):
        (FS/name).mkdir(parents=True, exist_ok=True)
    tools = json.loads((HERE/'tools-manifest.json').read_text())['artifacts']
    for name, info in tools.items():
        p = Path(info['path'])
        assert digest(p) == info['sha256'], name
        where = 'bin/busybox' if name == 'busybox' else ('usr/sbin/'+name if name in ('dropbear','dropbearkey') else 'usr/bin/'+name)
        copy(p, where, True)
    bb = Path(tools['busybox']['path'])
    applets = run(['qemu-arm','-cpu','cortex-a9',bb,'--list'], capture_output=True, text=True).stdout.splitlines()
    for name in applets:
        if name != 'busybox': link('bin/'+name, 'busybox')
    link('init', 'bin/busybox')
    link('sbin/init', '../bin/busybox')
    qt = ROOT/'development/perrier-qt/runtime'
    manifest = json.loads((qt.parent/'runtime-manifest.json').read_text())
    for name, info in manifest['files'].items(): assert digest(qt/name) == info['sha256']
    shutil.copytree(qt, FS/'qt', symlinks=True)
    link('lib','qt/lib')
    link('usr/lib','../lib')
    (FS/'root').chmod(0o700)
    put('etc/passwd','root:x:0:0:root:/root:/bin/sh\n')
    put('etc/group','root:x:0:\n')
    put('etc/shadow','root:*:0:0:99999:7:::\n',0o600)
    put('etc/shells','/bin/sh\n/bin/ash\n')
    put('etc/hosts','127.0.0.1 localhost\n10.77.10.10 touch10-ram\n10.77.10.1 host\n')
    put('etc/profile','export PATH=/bin:/sbin:/usr/bin:/usr/sbin\nexport PS1="touch10-ram# "\ncd /tmp\n')
    put('etc/inittab','::sysinit:/etc/init.d/rcS\nttyS0::respawn:-/bin/sh\n::ctrlaltdel:/bin/reboot\n::shutdown:/bin/sync\n')
    startup = (HERE/'rcS').read_text()
    if PROFILE in ('native-touch', 'native-backlight', 'native-keypad', 'keypad-newqt', 'native-thermal', 'native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        marker = {'native-touch':'ram50', 'native-backlight':'ram51',
                  'native-keypad':'ram52', 'keypad-newqt':'ram57',
                  'native-thermal':'ram58',
                  'native-smp':'ram53',
                  'smp-onecpu':'ram54', 'smp-sync':'ram55',
                  'smp-nosmp':'ram56'}[PROFILE]
        startup = startup.replace('ram44', marker)
        startup = startup.replace('/usr/bin/touch-uinput --interactive > /tmp/touch-raw.log 2>&1 &\necho $! > /run/touch.pid\n',
                                  'echo native-cyttsp4 > /run/touch-driver\n')
        startup += '''
# One bounded read-only network/IRQ diagnostic if host SSH cannot connect.
(
    for delay in 15 20 20; do
        sleep "$delay"
        echo PERRIER_NET_DIAGNOSTIC_BEGIN
        cat /proc/net/dev
        cat /proc/net/arp
        cat /proc/interrupts
        cat /run/ssh.log
        echo PERRIER_NET_DIAGNOSTIC_END
    done
) > /dev/console 2>&1 &
'''
    put('etc/init.d/rcS',startup,0o755)
    put('usr/bin/qt-run',(HERE/'qt-run').read_text(),0o755)
    put('root/.ssh/authorized_keys',(ROOT/'access/touch10_root_ecdsa.pub').read_text(),0o600)
    (FS/'root/.ssh').chmod(0o700)
    key = ROOT/'access/touch10_ram_host_ecdsa'
    keygen = Path(tools['dropbearkey']['path'])
    if not key.exists():
        run(['qemu-arm','-cpu','cortex-a9',keygen,'-t','ecdsa','-s','256','-f',key], capture_output=True)
        key.chmod(0o600)
    pub = run(['qemu-arm','-cpu','cortex-a9',keygen,'-y','-f',key], capture_output=True, text=True)
    public = next(line for line in pub.stdout.splitlines() if line.startswith('ecdsa-sha2-'))
    (ROOT/'access/known_hosts_ram').write_text('10.77.10.10 '+public+'\n')
    copy(key,'etc/dropbear/ram_host_key')
    (FS/'etc/dropbear/ram_host_key').chmod(0o600)
    cfg = ROOT/'access/ssh_config'
    if 'Host touch10-ram\n' not in cfg.read_text():
        with cfg.open('a') as f:
            f.write('\nHost touch10-ram\n    HostName 10.77.10.10\n    User root\n'
                    f'    IdentityFile {ROOT}/access/touch10_root_ecdsa\n'
                    '    IdentitiesOnly yes\n    PreferredAuthentications publickey\n'
                    f'    UserKnownHostsFile {ROOT}/access/known_hosts_ram\n'
                    '    StrictHostKeyChecking yes\n    BatchMode yes\n'
                    '    ConnectTimeout 3\n    ServerAliveInterval 5\n    ServerAliveCountMax 2\n')
    helpers = [(HERE/'ram_guard.c','usr/sbin/ram-guard'),
               (HERE/'event_dump.c','usr/bin/event-dump')]
    if PROFILE == 'clockfix':
        helpers.append((NATIVE/'touch_uinput.c','usr/bin/touch-uinput'))
    for source, name in helpers:
        run([PREFIX+'gcc','-O2','-g','-Wall','-Wextra','-static','-mcpu=cortex-a9',
             '-mfpu=neon','-mfloat-abi=hard',source,'-o',DEST/Path(name).name])
        copy(DEST/Path(name).name,name,True)
    root_manifest={}
    data=b''
    for p in sorted(FS.rglob('*')):
        name=str(p.relative_to(FS))
        if p.is_symlink():
            target=str(p.readlink())
            data+=native.cpio_entry(name,0o120777,target.encode())
            root_manifest[name]={'symlink':target}
        elif p.is_dir():
            data+=native.cpio_entry(name,stat.S_IFDIR | stat.S_IMODE(p.stat().st_mode))
        else:
            data+=native.cpio_entry(name,stat.S_IFREG | stat.S_IMODE(p.stat().st_mode),p.read_bytes())
            root_manifest[name]={'sha256':digest(p),'bytes':p.stat().st_size}
    data+=native.cpio_entry('dev/console',0o020600,major=5,minor=1)
    data+=native.cpio_entry('dev/null',0o020666,major=1,minor=3)
    data+=native.cpio_entry('TRAILER!!!',0)
    (DEST/'initramfs.cpio').write_bytes(data)
    (DEST/'rootfs-manifest.json').write_text(json.dumps(root_manifest,indent=2)+'\n')

def main():
    global DEST, OUT, FS, VERSION, PROFILE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('clockfix','native-touch','native-backlight','native-keypad','keypad-newqt','native-thermal','native-smp','smp-onecpu','smp-sync','smp-nosmp'), default='clockfix')
    args = parser.parse_args()
    PROFILE = args.profile
    if PROFILE == 'native-touch':
        DEST = HERE/'native-touch'
        OUT = DEST/'kernel-build'
        FS = DEST/'rootfs'
        VERSION = '6.18.48-perrier-ram50'
    elif PROFILE == 'native-backlight':
        DEST = HERE/'native-backlight'
        OUT = DEST/'kernel-build'
        FS = DEST/'rootfs'
        VERSION = '6.18.48-perrier-ram51'
    elif PROFILE == 'native-keypad':
        DEST = HERE/'native-keypad'
        OUT = DEST/'kernel-build'
        FS = DEST/'rootfs'
        VERSION = '6.18.48-perrier-ram52'
    elif PROFILE == 'keypad-newqt':
        DEST = HERE/'native-keypad-newqt'
        OUT = DEST/'kernel-build'
        FS = DEST/'rootfs'
        VERSION = '6.18.48-perrier-ram57'
    elif PROFILE == 'native-thermal':
        DEST = HERE/'native-thermal'
        OUT = DEST/'kernel-build'
        FS = DEST/'rootfs'
        VERSION = '6.18.48-perrier-ram58'
    elif PROFILE == 'native-smp':
        DEST = HERE/'native-smp'
        OUT = DEST/'kernel-build'
        FS = DEST/'rootfs'
        VERSION = '6.18.48-perrier-ram53'
    elif PROFILE == 'smp-onecpu':
        DEST = HERE/'native-smp-onecpu'
        OUT = DEST/'kernel-build'
        FS = DEST/'rootfs'
        VERSION = '6.18.48-perrier-ram54'
    elif PROFILE == 'smp-sync':
        DEST = HERE/'native-smp-sync'
        OUT = DEST/'kernel-build'
        FS = DEST/'rootfs'
        VERSION = '6.18.48-perrier-ram55'
    elif PROFILE == 'smp-nosmp':
        DEST = HERE/'native-smp-nosmp'
        OUT = DEST/'kernel-build'
        FS = DEST/'rootfs'
        VERSION = '6.18.48-perrier-ram56'
    os.umask(0o077)
    DEST.mkdir(exist_ok=True)
    stage()
    native.apply_kernel_patches()
    if PROFILE in ('native-touch', 'native-backlight', 'native-keypad', 'keypad-newqt', 'native-thermal', 'native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        native.apply_kernel_patches(TOUCH/'kernel-patches')
    OUT.mkdir(exist_ok=True)
    cfg=(NATIVE/'minimal.config').read_text().replace('-perrier-ram43',VERSION.removeprefix('6.18.48'))
    if PROFILE in ('native-touch', 'native-backlight', 'native-keypad', 'keypad-newqt', 'native-thermal', 'native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        cfg = cfg.replace('CONFIG_INPUT_UINPUT=y', '# CONFIG_INPUT_UINPUT is not set')
        cfg += '\nCONFIG_INPUT_TOUCHSCREEN=y\nCONFIG_TOUCHSCREEN_CYTTSP4=y\n'
    if PROFILE in ('native-backlight', 'native-keypad', 'keypad-newqt', 'native-thermal', 'native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        cfg += 'CONFIG_PWM=y\nCONFIG_PWM_OMAP_DMTIMER=y\nCONFIG_BACKLIGHT_PWM=y\n'
    if PROFILE in ('native-keypad', 'keypad-newqt', 'native-thermal', 'native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        cfg += 'CONFIG_INPUT_KEYBOARD=y\nCONFIG_KEYBOARD_OMAP4=y\n'
    if PROFILE == 'native-thermal':
        cfg += ('CONFIG_HWMON=y\nCONFIG_SENSORS_TMP102=y\n'
                'CONFIG_THERMAL=y\nCONFIG_THERMAL_OF=y\n'
                'CONFIG_TI_SOC_THERMAL=y\nCONFIG_TI_THERMAL=y\n'
                'CONFIG_OMAP4_THERMAL=y\n')
    if PROFILE in ('native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        cfg = cfg.replace('# CONFIG_SMP is not set', 'CONFIG_SMP=y\nCONFIG_NR_CPUS=2')
    if PROFILE in ('smp-onecpu', 'smp-sync', 'smp-nosmp'):
        old = ' panic=5"'
        assert cfg.count(old) == 1
        if PROFILE == 'smp-nosmp':
            cfg = cfg.replace(old, ' panic=5 nosmp"')
        else:
            cfg = cfg.replace(old, ' panic=5 maxcpus=1'+(' initramfs_async=0' if PROFILE == 'smp-sync' else '')+'"')
    cfg+='\n'+''.join('CONFIG_'+n+'=y\n' for n in SOFTWARE)
    cfg+=f'CONFIG_INITRAMFS_SOURCE="{DEST}/initramfs.cpio"\n'
    (DEST/'kernel.config').write_text(cfg)
    env=dict(os.environ,KCONFIG_ALLCONFIG=str(DEST/'kernel.config'),KBUILD_BUILD_USER='touch10',
             KBUILD_BUILD_HOST='perrier-dev',KBUILD_BUILD_TIMESTAMP='2026-11-09 00:00:00 UTC')
    make=['make','-C',SRC,f'O={OUT}','ARCH=arm','LLVM=1']
    run(make+['allnoconfig'],env=env)
    opts=['--enable','DRM_FBDEV_EMULATION','--enable','DRM_CLIENT_DEFAULT_FBDEV','--enable','FB_DEVICE']
    run([SRC/'scripts/config','--file',OUT/'.config',*opts])
    env.pop('KCONFIG_ALLCONFIG')
    run(make+['olddefconfig'],env=env)
    run(make+['-j'+str(os.cpu_count() or 1),'zImage'],env=env)
    if PROFILE in ('native-touch', 'native-backlight', 'native-keypad', 'keypad-newqt', 'native-thermal', 'native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        with (DEST/'preprocessed.dts').open('wb') as stream:
            run(['clang','-E','-P','-x','assembler-with-cpp','-nostdinc','-undef','-D__DTS__',
                 '-I',SRC/'arch/arm/boot/dts/ti/omap','-I',SRC/'scripts/dtc/include-prefixes',
                 {'native-touch':TOUCH/'omap4-perrier-touch.dts',
                  'native-backlight':BACKLIGHT/'omap4-perrier-backlight.dts',
                  'native-keypad':KEYPAD/'omap4-perrier-keypad.dts',
                  'keypad-newqt':KEYPAD/'omap4-perrier-keypad.dts',
                  'native-thermal':THERMAL/'omap4-perrier-thermal.dts',
                  'native-smp':SMP/'omap4-perrier-smp.dts',
                  'smp-onecpu':SMP/'omap4-perrier-smp.dts',
                  'smp-sync':SMP/'omap4-perrier-smp.dts',
                  'smp-nosmp':SMP/'omap4-perrier-smp.dts'}[PROFILE]],stdout=stream)
        run([OUT/'scripts/dtc/dtc','-i',SRC/'arch/arm/boot/dts/ti/omap',
             '-I','dts','-O','dtb','-o',DEST/'board.dtb',DEST/'preprocessed.dts'])
    else:
        dtb=NATIVE/'baselines/ram43-before-interactive/board.dtb'
        assert digest(dtb)=='73444e693857d02d5fc134697349a83e22662572f1dc17725e2878f4b90253a0'
        shutil.copy2(dtb,DEST/'board.dtb')
    files={'zImage':OUT/'arch/arm/boot/zImage','board.dtb':DEST/'board.dtb',
           'kexec':ROOT/'development/perrier/kexec-legacy-fdt'}
    record={'kernel':VERSION,'profile':PROFILE,'artifacts':{n:{'path':str(p),'sha256':digest(p),'size':p.stat().st_size}
                                       for n,p in files.items()},
            'rootfs_manifest_sha256':digest(DEST/'rootfs-manifest.json'),
            'initramfs_sha256':digest(DEST/'initramfs.cpio'),
            'kernel_config_sha256':digest(OUT/'.config'),
            'guard_sha256':digest(FS/'usr/sbin/ram-guard'),
            'patch_manifest_sha256':digest(NATIVE/'kernel-patches/manifest.json')}
    if PROFILE in ('native-touch', 'native-backlight', 'native-keypad', 'keypad-newqt', 'native-thermal', 'native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        record['touch_patch_manifest_sha256']=digest(TOUCH/'kernel-patches/manifest.json')
        record['touch_dts_sha256']=digest(TOUCH/'omap4-perrier-touch.dts')
        record['base_dts_sha256']=digest(NATIVE/'omap4-perrier-ram.dts')
    if PROFILE in ('native-backlight', 'native-keypad', 'keypad-newqt', 'native-thermal', 'native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        record['backlight_dts_sha256']=digest(BACKLIGHT/'omap4-perrier-backlight.dts')
    if PROFILE in ('native-keypad', 'keypad-newqt', 'native-thermal', 'native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        record['keypad_dts_sha256']=digest(KEYPAD/'omap4-perrier-keypad.dts')
    if PROFILE == 'native-thermal':
        record['thermal_dts_sha256']=digest(THERMAL/'omap4-perrier-thermal.dts')
    if PROFILE in ('native-smp', 'smp-onecpu', 'smp-sync', 'smp-nosmp'):
        record['smp_dts_sha256']=digest(SMP/'omap4-perrier-smp.dts')
    (DEST/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))

if __name__=='__main__': main()
