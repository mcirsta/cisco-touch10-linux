#!/usr/bin/env python3
"""Build the RAM shell, SSH server and syscall tracer for Cortex-A9."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TC = ROOT / 'development/perrier-qt/sources/armv7-eabihf--musl--stable-2026.08-1'
PREFIX = str(TC / 'bin/arm-buildroot-linux-musleabihf-')
FLAGS = '-Os -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard'
HASHES = {
    'busybox-1.37.0.tar.bz2': '3311dff32e746499f4df0d5df04d7eb396382d7e108bb9250e7b519b837043a4',
    'dropbear-2026.94.tar.bz2': 'e098034a843699200c8c977a991fff73159735bf795d5f72ef672c41a6b1ae81',
    'strace-7.3.tar.xz': '529634c40910895a9a1f3c5c1e65da2ca9ed72fb158dfc4bcc89efdf05e39b72',
}

def run(args, **kw):
    subprocess.run([str(a) for a in args], check=True, **kw)

def main():
    sources = HERE / 'sources'
    sources.mkdir(exist_ok=True)
    for name, expected in HASHES.items():
        archive = HERE / 'downloads' / name
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
        dest = sources / name.split('.tar.')[0]
        if not dest.exists():
            with tarfile.open(archive) as tar:
                tar.extractall(sources, filter='data')
    jobs = str(os.cpu_count() or 1)
    bb = sources / 'busybox-1.37.0'
    if not (bb / '.config').exists():
        run(['make', 'ARCH=arm', 'CROSS_COMPILE='+PREFIX, 'defconfig'], cwd=bb)
    cfg = (bb / '.config').read_text()
    cfg = cfg.replace('# CONFIG_STATIC is not set', 'CONFIG_STATIC=y')
    for option in ('FEATURE_SUID', 'TC', 'WATCHDOG', 'SHA1_HWACCEL', 'SHA256_HWACCEL'):
        cfg = cfg.replace(f'CONFIG_{option}=y', f'# CONFIG_{option} is not set')
    (bb / '.config').write_text(cfg)
    run(['make', 'ARCH=arm', 'CROSS_COMPILE='+PREFIX, 'oldconfig'], cwd=bb, input=b'\n' * 1000)
    run(['make', '-j' + jobs, 'CROSS_COMPILE=' + PREFIX,
         'EXTRA_CFLAGS=' + FLAGS], cwd=bb)
    env = dict(os.environ, CC=PREFIX+'gcc', AR=PREFIX+'ar', RANLIB=PREFIX+'ranlib',
               CFLAGS=FLAGS, LDFLAGS='-static')
    db = sources / 'dropbear-2026.94'
    (db / 'localoptions.h').write_text('''#define DROPBEAR_SVR_PASSWORD_AUTH 0
#define DROPBEAR_SVR_PAM_AUTH 0
#define DROPBEAR_SVR_AGENTFWD 0
#define DROPBEAR_SVR_REMOTETCPFWD 0
#define DROPBEAR_SVR_X11FWD 0
''')
    if not (db / 'Makefile').exists():
        run(['./configure', '--host=arm-buildroot-linux-musleabihf',
             '--disable-zlib', '--disable-syslog', '--disable-wtmp',
             '--disable-utmp', '--disable-lastlog', '--disable-pam'], cwd=db, env=env)
    run(['make', '-j'+jobs, 'PROGRAMS=dropbear dropbearkey scp'], cwd=db, env=env)
    st = sources / 'strace-7.3'
    if not (st / 'Makefile').exists():
        run(['./configure', '--host=arm-buildroot-linux-musleabihf',
             '--enable-mpers=no', '--with-libunwind=no', '--with-libdw=no'], cwd=st, env=env)
    run(['make', '-j'+jobs], cwd=st, env=env)
    artifacts = {
        'busybox': bb / 'busybox', 'dropbear': db / 'dropbear',
        'dropbearkey': db / 'dropbearkey', 'scp': db / 'scp',
        'strace': st / 'src/strace',
        'gdbserver': TC / 'arm-buildroot-linux-musleabihf/debug-root/usr/bin/gdbserver',
    }
    record = {'cpu': 'cortex-a9', 'compiler': 'GCC 15.3.0', 'sources': HASHES,
              'artifacts': {name: {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                            for name, p in artifacts.items()}}
    (HERE / 'tools-manifest.json').write_text(json.dumps(record, indent=2)+'\n')
    for name, flags in [('busybox', ['echo', 'RAM_TOOLS_OK']), ('dropbear', ['-V']),
                        ('strace', ['-V'])]:
        run(['qemu-arm', '-cpu', 'cortex-a9', artifacts[name], *flags])
    runtime = ROOT / 'development/perrier-qt/runtime/lib'
    run(['qemu-arm', '-cpu', 'cortex-a9', runtime / 'ld-musl-armhf.so.1',
         '--library-path', runtime, artifacts['gdbserver'], '--version'])

if __name__ == '__main__':
    main()
