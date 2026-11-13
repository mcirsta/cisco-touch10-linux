#!/usr/bin/env python3
"""Build pinned ALSA userspace for Perrier's Cortex-A9 musl runtime."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLCHAIN = ROOT / 'development/perrier-qt/sources/armv7-eabihf--musl--stable-2026.08-1'
BUILD = HERE / 'app-build'
INSTALL = HERE / 'app-install'
LOG = ROOT / 'development/kernel/out/application-audio'
PINS = {'alsa-lib': 'f44e0abd5382f519cc6fa69850c34e6e9c09d5f5',
        'alsa-utils': 'f3537ede21d0bc5b34835988752523b08459c532'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    LOG.mkdir(parents=True, exist_ok=True)
    compiler = TOOLCHAIN / 'bin/arm-buildroot-linux-musleabihf-gcc'
    env = dict(os.environ, PATH=str(TOOLCHAIN / 'bin') + ':' + os.environ['PATH'],
               CC=str(compiler), CFLAGS='-Os -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard')
    args = json.loads((HERE / 'alsa-configure-args.json').read_text())
    args[0] = str(HERE / 'alsa-lib/configure')
    configurations = {'alsa-lib': args[1:]}
    def run(command, cwd, log, environment=env):
        with (LOG / log).open('w') as stream:
            subprocess.run(command, cwd=cwd, env=environment, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
    for name, pin in PINS.items():
        source = HERE / name
        assert subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD'], text=True).strip() == pin
        assert not subprocess.check_output(['git', '-C', source, 'diff', '--name-only'], text=True).strip()
        if not (source / 'configure').exists():
            run(['autoreconf', '-fi'], source, name + '-autoreconf.log')
        (BUILD / name).mkdir(parents=True, exist_ok=True)
    run(args, BUILD / 'alsa-lib', 'alsa-configure.log')
    run(['make', '-j' + str(os.cpu_count() or 1)], BUILD / 'alsa-lib', 'alsa-build.log')
    run(['make', 'DESTDIR=' + str(INSTALL), 'install'], BUILD / 'alsa-lib', 'alsa-install.log')
    utils_args = ['--host=arm-buildroot-linux-musleabihf', '--prefix=/usr',
                  '--disable-alsatest', '--disable-nls', '--disable-alsamixer',
                  '--disable-xmlto', '--disable-rst2man', '--disable-bat',
                  '--disable-alsaloop', '--disable-alsaconf', '--disable-nhlt', '--disable-rpath']
    configurations['alsa-utils'] = utils_args
    utils_env = dict(env, CPPFLAGS='-I' + str(INSTALL / 'usr/include'),
                     ALSA_CFLAGS='-I' + str(INSTALL / 'usr/include'),
                     ALSA_LIBS='-L' + str(INSTALL / 'usr/lib') + ' -lasound',
                     PKG_CONFIG_LIBDIR=str(INSTALL / 'usr/lib/pkgconfig'),
                     PKG_CONFIG_SYSROOT_DIR=str(INSTALL))
    run([str(HERE / 'alsa-utils/configure')] + utils_args,
        BUILD / 'alsa-utils', 'utils-configure.log', utils_env)
    run(['make', '-C', 'include', 'version.h'], BUILD / 'alsa-utils', 'utils-version.log', utils_env)
    # An installed libtool .la names the target /usr/lib. Link the staged ARM
    # SONAME file explicitly so libtool cannot substitute a host library.
    run(['make', '-C', 'aplay', 'LIBS=' + str(INSTALL / 'usr/lib/libasound.so.2.0.0') + ' -lm -lpthread'],
        BUILD / 'alsa-utils', 'utils-build.log', utils_env)
    files = [INSTALL / 'usr/lib/libasound.so.2.0.0', BUILD / 'alsa-utils/aplay/aplay',
             HERE / 'asound.conf', HERE / 'alsa-lib/COPYING', HERE / 'alsa-utils/COPYING']
    files += sorted(p for p in (INSTALL / 'etc/alsa').rglob('*') if p.is_file())
    record = {'source_commits': PINS, 'sources_unmodified': True,
              'compiler': str(compiler), 'compiler_sha256': sha(compiler),
              'cflags': env['CFLAGS'], 'configure': configurations,
              'files': {str(p.relative_to(HERE)): {'sha256': sha(p), 'bytes': p.stat().st_size} for p in files}}
    (HERE / 'application-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Built ALSA library and aplay; recorded ' + str(len(files)) + ' inputs')


if __name__ == '__main__':
    main()
