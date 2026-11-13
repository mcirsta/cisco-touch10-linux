#!/usr/bin/env python3
"""Build the ram116 RAM image using only this clone and pinned upstream inputs."""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STAGES = ('inputs', 'userspace', 'rootfs', 'kernel')
COMMANDS = ('git', 'patch', 'make', 'clang', 'clang++', 'ld.lld', 'llvm-ar',
            'llvm-objcopy', 'cpp', 'dtc', 'bison', 'flex', 'cmake', 'ninja',
            'pkg-config', 'autoreconf', 'automake', 'libtoolize', 'autopoint', 'gperf',
            'qemu-arm')


def check_host() -> dict:
    missing = [name for name in COMMANDS if shutil.which(name) is None]
    if sys.version_info < (3, 12):
        missing.append('Python >= 3.12')
    if missing:
        raise RuntimeError('Missing host build dependencies: ' + ', '.join(missing))
    qt = {}
    for component in ('Qt6Core', 'Qt6Qml', 'Qt6ShaderTools'):
        result = subprocess.run(['pkg-config', '--modversion', component], capture_output=True, text=True)
        if result.returncode or not result.stdout.strip().startswith('6.12.'):
            raise RuntimeError(f'Qt 6.12 host development tools are required: {component}')
        qt[component] = result.stdout.strip()
    return {
        'python': sys.version.split()[0], 'host_qt': qt,
        'clang': subprocess.check_output(['clang', '--version'], text=True).splitlines()[0],
        'cmake': subprocess.check_output(['cmake', '--version'], text=True).splitlines()[0],
        'ninja_parallelism': 'Ninja default; no override',
    }


def command(root: Path, output: Path, name: str, arguments: list[str], *, env=None) -> None:
    logfile = output / 'logs' / (name + '.log')
    print(f'Building {name}; log: {logfile}', flush=True)
    with logfile.open('w') as stream:
        result = subprocess.run(arguments, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        tail = logfile.read_text(errors='replace').splitlines()[-35:]
        raise RuntimeError(f'{name} failed (exit {result.returncode}):\n' + '\n'.join(tail))


def invalidate(report: dict, stage: str) -> None:
    """A rebuilt dependency makes all downstream completion records stale."""
    index = STAGES.index(stage)
    for name in STAGES[index:]:
        report['stages'].pop(name, None)
    report.pop('kernel_build', None)
    if index <= STAGES.index('rootfs'):
        report.pop('rootfs', None)
    if stage == 'inputs':
        report.pop('inputs', None)
    report.pop('completed_utc', None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path,
                        help='Output directory (default: development/standalone/out/ram116)')
    parser.add_argument('--cache', type=Path, help='Optional cache of verified upstream source inputs')
    parser.add_argument('--offline', action='store_true', help='Require inputs already present or cached')
    parser.add_argument('--authorized-key', type=Path,
                        help='Public SSH key to authorize; SSH is disabled when omitted')
    parser.add_argument('--stage', choices=('all', *STAGES), default='all',
                        help='Run all stages, or resume one stage whose inputs were freshly built')
    parser.add_argument('--check-host', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output or root / 'development/standalone/out/ram116').resolve()
    if args.check_host:
        print(json.dumps(check_host(), indent=2))
        return
    os.umask(0o077)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'logs').mkdir(exist_ok=True)
    report_path = output / 'build.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else {'stages': {}}
    report.update({
        'kernel': '6.18.48-perrier-ram116', 'profile': 'cpu-dvfs-mid-trial',
        'build_entry_point': 'development/standalone/build.py',
        'host': check_host(), 'live_tested': False,
        'historical_artifacts_required': False,
    })

    def save() -> None:
        report_path.write_text(json.dumps(report, indent=2) + '\n')

    stages = STAGES if args.stage == 'all' else (args.stage,)
    for stage in stages:
        invalidate(report, stage)
        start = time.monotonic()
        report['state'] = 'building-' + stage
        save()
        try:
            if stage == 'inputs':
                import inputs
                report['inputs'] = inputs.prepare(root, args.cache, args.offline)
            elif stage == 'userspace':
                command(root, output, 'qt-and-alsa', ['bash', 'development/perrier-qt/build_qt.sh'])
                command(root, output, 'alsa-dmix', [sys.executable, 'development/audio/build_dmix_lib.py'])
                command(root, output, 'ram-tools', [sys.executable, 'development/perrier-ramenv/build_tools.py'])
            elif stage == 'rootfs':
                from rootfs import build_rootfs
                report['rootfs'] = build_rootfs(root, output, authorized_key=args.authorized_key)
                command(root, output, 'packaged-qt',
                        [sys.executable, 'development/perrier-qt/preflight_qemu.py'],
                        env=dict(os.environ, PERRIER_QT_RUNTIME=str(output / 'rootfs/qt'),
                                 PERRIER_QEMU_SYSROOT=str(output / 'rootfs')))
                report['rootfs']['packaged_qt_qemu_passed'] = True
            elif stage == 'kernel':
                import kernel
                report['kernel_build'] = kernel.build(root, output, output / 'initramfs.cpio')
        except Exception as error:
            report.update(state='failed-' + stage, error=str(error))
            save()
            raise
        report['stages'][stage] = {'passed': True, 'elapsed_seconds': round(time.monotonic() - start, 2)}
        report.pop('error', None)
        save()
        print(f'Completed {stage} in {time.monotonic() - start:.1f}s', flush=True)
    complete = all(report['stages'].get(name, {}).get('passed') for name in STAGES)
    report.update(state='built-and-audited' if complete else 'stage-complete',
                  completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    save()
    print(json.dumps({'state': report['state'], 'report': str(report_path),
                      'live_tested': False}, indent=2))


if __name__ == '__main__':
    main()
