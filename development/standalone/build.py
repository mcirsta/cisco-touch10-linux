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
import uuid

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


def run_stages(root: Path, output: Path, stages=STAGES, *, cache=None,
               offline=False, authorized_key=None) -> dict:
    """Run fresh stages in a caller-owned workspace; caller holds build_lock.

    This also serves other profiles that build their own kernel after the
    common userspace/rootfs stages. No retention or source deletion happens here.
    """
    root, output = Path(root).resolve(), Path(output).resolve()
    sys.path.insert(0, str(HERE))
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

    for stage in stages:
        required = STAGES[:STAGES.index(stage)]
        if not all(report['stages'].get(name, {}).get('passed') for name in required):
            raise RuntimeError('Run the preceding stages before resuming ' + stage)
        invalidate(report, stage)
        start = time.monotonic()
        report['state'] = 'building-' + stage
        save()
        try:
            if stage == 'inputs':
                import inputs
                report['inputs'] = inputs.prepare(root, cache, offline)
            elif stage == 'userspace':
                command(root, output, 'qt-and-alsa', ['bash', 'development/perrier-qt/build_qt.sh'])
                command(root, output, 'alsa-dmix', [sys.executable, 'development/audio/build_dmix_lib.py'])
                command(root, output, 'ram-tools', [sys.executable, 'development/perrier-ramenv/build_tools.py'])
            elif stage == 'rootfs':
                from rootfs import build_rootfs
                report['rootfs'] = build_rootfs(root, output, authorized_key=authorized_key)
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
    return report


def active_work(root: Path, destination: Path, *, restart: bool) -> tuple[Path, Path]:
    """Find a staged build, or create isolated work without changing a good image."""
    from lifecycle import _output, cleanup_failed, finalize_build
    destination = _output(root, destination)
    managed = root / 'development/standalone/out'
    if destination.parent != managed or destination.name.startswith('.'):
        raise ValueError('Automatic cleanup requires --output development/standalone/out/<name>; '
                         'use --keep-work for another path')
    directory = managed / '.lifecycle'
    directory.mkdir(parents=True, exist_ok=True)
    if (managed / '.work').is_symlink():
        raise RuntimeError('The build workspace directory must not be a symlink')
    pointer = directory / ('active-' + destination.name + '.json')
    if pointer.is_symlink():
        raise RuntimeError('The active build record must not be a symlink')
    if pointer.exists():
        saved = Path(json.loads(pointer.read_text())['work'])
        work = saved.resolve()
        if work.parent != managed / '.work' or saved.is_symlink():
            raise RuntimeError('Unsafe active build workspace: ' + str(work))
        if work.exists() and not restart:
            return work, pointer
        if work.exists():
            record_path = work / 'build.json'
            record = json.loads(record_path.read_text()) if record_path.exists() else {}
            if record.get('state') == 'built-and-audited':
                cleanup = finalize_build(root, work, destination=destination)
            else:
                cleanup = cleanup_failed(root, work)
            if work.exists():
                raise RuntimeError('Previous workspace cleanup was deferred: ' +
                                   cleanup.get('reason', str(work)))
        pointer.unlink(missing_ok=True)
    elif not restart:
        raise RuntimeError('No staged build to resume; start with --stage inputs or --stage all')
    work = managed / '.work' / (destination.name + '-' + uuid.uuid4().hex)
    work.mkdir(parents=True)
    temporary = pointer.with_name(pointer.name + '.' + uuid.uuid4().hex)
    temporary.write_text(json.dumps({'work': str(work)}, indent=2) + '\n')
    temporary.replace(pointer)
    return work, pointer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path,
                        help='Retained bundle (default: development/standalone/out/ram116)')
    parser.add_argument('--cache', type=Path, help='Optional cache of original upstream sources')
    parser.add_argument('--offline', action='store_true', help='Require local or cached inputs')
    parser.add_argument('--authorized-key', type=Path,
                        help='Public SSH key to authorize; SSH is disabled when omitted')
    parser.add_argument('--stage', choices=('all', *STAGES), default='all',
                        help='Run all stages, or resume one stage of an unfinished build')
    parser.add_argument('--keep-work', action='store_true',
                        help='Debugging: build directly in --output and keep sources/intermediates')
    parser.add_argument('--check-host', action='store_true')
    args = parser.parse_args()
    if args.check_host:
        print(json.dumps(check_host(), indent=2))
        return
    sys.path.insert(0, str(HERE))
    from lifecycle import build_lock, cleanup_failed, finalize_build
    root = args.root.resolve()
    destination = Path(os.path.abspath(args.output or root / 'development/standalone/out/ram116'))
    os.umask(0o077)
    with build_lock(root):
        pointer = None
        if args.keep_work:
            destination = destination.resolve()
            if (destination / 'retained-build.json').exists():
                raise RuntimeError('Choose a separate --output for --keep-work; this is a retained image')
            work = destination
        else:
            work, pointer = active_work(root, destination,
                                        restart=args.stage in ('all', 'inputs'))
        try:
            report = run_stages(root, work, STAGES if args.stage == 'all' else (args.stage,),
                                cache=args.cache, offline=args.offline,
                                authorized_key=args.authorized_key)
        except BaseException:
            if not args.keep_work:
                try:
                    result = cleanup_failed(root, work)
                    print(json.dumps({'cleanup': result}), file=sys.stderr)
                    if not work.exists():
                        pointer.unlink(missing_ok=True)
                except Exception as cleanup_error:
                    print('Cleanup could not finish; work preserved: ' + str(cleanup_error),
                          file=sys.stderr)
            raise
        result = None
        if report['state'] == 'built-and-audited' and not args.keep_work:
            result = finalize_build(root, work, destination=destination)
            if not work.exists():
                pointer.unlink(missing_ok=True)
        final_output = destination if result and not work.exists() else work
        print(json.dumps({'state': report['state'], 'report': str(final_output / 'build.json'),
                          'cleanup': result, 'live_tested': False}, indent=2))


if __name__ == '__main__':
    main()
