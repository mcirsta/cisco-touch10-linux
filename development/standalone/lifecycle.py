#!/usr/bin/env python3
"""Preserve source edits, compact audited images, and retain two managed builds.

Only the enumerated build inputs and directories below are disposable. Source
snapshots stay local in development/source-preservation/auto and can be restored
with preservation.py. Verified compressed upstream inputs are deliberately kept;
external caches, evidence, backups and device state are never cleanup targets.
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import uuid

OUT = Path('development/standalone/out')
PRIVATE = Path('development/source-preservation/auto')
GENERATED = (
    'development/perrier-qt/build-local-qtbase',
    'development/perrier-qt/build-local-qtdeclarative',
    'development/perrier-qt/build-arm-a9-local',
    'development/perrier-qt/qt-arm', 'development/perrier-qt/runtime',
    'development/audio/app-build', 'development/audio/app-install',
    'development/audio/shared-build', 'development/audio/shared-install',
    'development/standalone/__pycache__', 'development/kernel/__pycache__',
    'development/perrier-ramenv/__pycache__', 'development/perrier-qt/__pycache__',
    'development/audio/__pycache__', 'tools/__pycache__',
)
REQUIRED = {'zImage', 'board.dtb', 'initramfs.cpio', 'kernel.config'}
ADC_SHA256 = '921a877fcbb0b1f9a711d1c22d5b8db6cabf39df70c8cab96e400a3942cbc6e6'
ADC_HOME = Path('development/kernel/out/native-diagnostics')


class CleanupDeferred(RuntimeError):
    """Cleanup cannot be completed safely; original trees must remain."""


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    with temporary.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _local(root: Path, path: Path | str) -> Path:
    """Keep lexical paths and reject every symlink in their ancestry."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f'Cleanup path escapes project: {candidate}') from error
    if not relative.parts:
        raise ValueError('Project root is never a cleanup target')
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f'Cleanup path follows a symlink: {current}')
    return candidate


def _output(root: Path, path: Path, *, staging=False) -> Path:
    path = _local(root, path)
    relative = path.relative_to(root / OUT)
    valid = (len(relative.parts) == 1 and not relative.name.startswith('.'))
    valid |= (staging and len(relative.parts) == 2 and relative.parts[0] == '.work'
              and not relative.name.startswith('.'))
    if not valid:
        raise ValueError(f'Not a managed build output: {path}')
    return path


@contextmanager
def build_lock(root: Path):
    """Serialize users of the shared source/build directories across builds."""
    root = Path(root).resolve()
    lock = _local(root, OUT / '.lifecycle/build.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CleanupDeferred('Another build owns the shared inputs; try after it finishes') from error
        yield


@contextmanager
def _cleanup_lock(root: Path):
    manager = _local(root, OUT / '.lifecycle')
    manager.mkdir(parents=True, exist_ok=True)
    with (manager / 'cleanup.lock').open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        runner_path = _local(root, 'development/.runner.lock')
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        with runner_path.open('a+') as runner:
            try:
                fcntl.flock(runner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CleanupDeferred('A RAM runner is active; cleanup is deferred') from error
            yield manager


def _artifact_path(output: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        try:
            value = path.relative_to(output).as_posix()
        except ValueError as error:
            raise ValueError(f'Artifact is outside its build: {path}') from error
    else:
        value = path.as_posix()
    relative = PurePosixPath(value)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError(f'Invalid artifact path: {value}')
    current = output
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f'Artifact follows a symlink: {current}')
    if not current.is_file():
        raise ValueError(f'Missing regular artifact: {current}')
    return current


def verify_artifacts(output: Path, artifacts: dict) -> dict:
    if not REQUIRED <= artifacts.keys():
        raise ValueError('An audited build must contain all four final artifacts')
    verified = {}
    for name, entry in artifacts.items():
        path = _artifact_path(output, entry['path'])
        expected_size = entry.get('bytes', entry.get('size'))
        if expected_size is None or path.stat().st_size != expected_size or digest(path) != entry['sha256']:
            raise ValueError(f'Artifact verification failed: {name}')
        verified[name] = {'path': path.relative_to(output).as_posix(),
                          'bytes': expected_size, 'sha256': entry['sha256']}
    return verified


def _admission(output: Path) -> dict:
    report = _json(output / 'build.json') if (output / 'build.json').exists() else {}
    if report and (report.get('state') != 'built-and-audited' or not all(
            report.get('stages', {}).get(name, {}).get('passed') is True
            for name in ('inputs', 'userspace', 'rootfs', 'kernel'))):
        raise ValueError('Only a complete, successful build can replace a retained image')
    audit = None
    for name in ('kernel-build.json', 'reviewed-image.json'):
        if (output / name).is_file():
            candidate = _json(output / name)
            if candidate.get('passed') is True:
                audit = candidate
                break
    if audit is None:
        raise ValueError('A fresh passed image audit is required before cleanup')
    artifacts = dict(audit.get('artifacts', {}))
    # The older SmartReflex audit records the last two hashes separately.
    for name, key in (('initramfs.cpio', 'initramfs_sha256'),
                      ('kernel.config', 'kernel_config_sha256')):
        if name not in artifacts and key in audit:
            path = output / name
            artifacts[name] = {'path': name, 'bytes': path.stat().st_size,
                               'sha256': audit[key]}
    artifacts = verify_artifacts(output, artifacts)
    completed = report.get('completed_utc') or audit.get('completed_utc') or _now()
    _date(completed)
    return {'format_version': 1, 'kernel': audit.get('kernel', report.get('kernel')),
            'profile': audit.get('profile', report.get('profile')),
            'completed_utc': completed, 'artifacts': artifacts,
            'scope': 'Audited final image bundle; temporary compilation trees removed',
            'live_tested': audit.get('live_tested', False)}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _date(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed


def _registry(root: Path) -> dict:
    """Adopt only manifest-bearing bundles; never discover deletion targets by glob."""
    out = root / OUT
    path = out / '.lifecycle/registry.json'
    registry = _json(path) if path.exists() else {'format_version': 1, 'builds': {}}
    # Exact legacy bundles are the only directories predating registration.
    for name in ('ram116', 'ram117'):
        directory = _output(root, out / name)
        marker = directory / 'retained-build.json'
        if name in registry['builds'] or not marker.is_file():
            continue
        retained = _json(marker)
        verify_artifacts(directory, retained['artifacts'])
        # Date-only legacy manifests have no trustworthy intraday build order.
        # Their version names break that tie, rather than copied file timestamps.
        completed = retained.get('completed_utc') or retained.get('retained_on')
        if completed is None:
            raise ValueError(f'Legacy image has no recorded retention date: {name}')
        _date(completed)
        registry['builds'][name] = {'completed_utc': completed,
                                   'kernel': retained.get('kernel'), 'legacy': True}
    for name in list(registry['builds']):
        directory = _output(root, out / name)
        if not directory.exists():
            del registry['builds'][name]
    return registry


def _manifest(root: Path) -> dict:
    path = root / 'development/standalone/inputs.json'
    return _json(path) if path.exists() else {'archives': {}, 'git': {}}


def _sources(root: Path, output: Path, source_inputs, cleanup_inputs: bool) -> list[dict]:
    manifest = _manifest(root)
    sources = {}
    if cleanup_inputs:
        for entry in manifest['archives'].values():
            if (Path(entry['top_directory']).name != entry['top_directory']
                    or entry['top_directory'] in {'', '.', '..'}
                    or entry['extract_to'] not in {
                        'development/sources', 'development/perrier-qt/sources',
                        'development/perrier-ramenv/sources'}):
                raise ValueError('Archive source cleanup target is outside owned source directories')
            path = _local(root, Path(entry['extract_to']) / entry['top_directory'])
            sources[path] = {'tree': path, 'kind': 'tar',
                             'archive': _local(root, entry['destination']),
                             'sha256': entry['sha256']}
        for entry in manifest['git'].values():
            if entry['destination'] not in {
                    'development/audio/alsa-lib', 'development/audio/alsa-utils',
                    'development/audio/tinyalsa', 'development/kexec-tools'}:
                raise ValueError('Git cleanup target is outside owned source directories')
            path = _local(root, entry['destination'])
            sources[path] = {'tree': path, 'kind': 'git'}
    linux = manifest['archives'].get('linux')
    source = _local(root, output / 'kernel-source')
    if source.exists():
        sources[source] = ({'tree': source, 'kind': 'tar',
                            'archive': _local(root, linux['destination']),
                            'sha256': linux['sha256']} if linux else
                           {'tree': source, 'kind': 'tree'})
    # Explicit extras permit the reviewed RAM117 kernel workspace, never broad
    # filesystem discovery. Every supplied tree still has to match an owned path.
    for supplied in source_inputs or ():
        entry = dict(supplied)
        path = _local(root, entry['tree'])
        allowed = path in sources
        relative = path.relative_to(root).as_posix()
        allowed |= relative.startswith(output.relative_to(root).as_posix() + '/kernel-source') and path == source
        if linux:
            prefix = 'development/kernel/work/'
            leaf = relative[len(prefix):] if relative.startswith(prefix) else ''
            allowed |= bool(re.fullmatch(re.escape(linux['top_directory']) + r'-ram[0-9]+', leaf))
        if not allowed:
            raise ValueError(f'Unregistered source cleanup target: {path}')
        original = sources.get(path)
        if original is not None and entry.get('kind', 'tree') != original['kind']:
            raise ValueError(f'Source preservation kind changed: {path}')
        entry['tree'] = path
        if entry.get('archive'):
            entry['archive'] = _local(root, entry['archive'])
            expected = original if original is not None else {
                'archive': _local(root, linux['destination']), 'sha256': linux['sha256']}
            if (entry['archive'] != expected['archive']
                    or entry.get('sha256') != expected['sha256']):
                raise ValueError(f'Source archive is not the pinned input: {path}')
        sources[path] = entry
    return [entry for entry in sources.values() if entry['tree'].exists()]


def _generated_reason(tree: Path, name: str, descriptor: dict) -> str | None:
    """Explicit output policy; changed upstream objects are never excluded."""
    relative = PurePosixPath(name)
    leaf = relative.name
    if '__pycache__' in relative.parts or 'autom4te.cache' in relative.parts:
        return 'Python/autoconf cache in a managed build tree'
    if leaf == '.ninja_deps':
        return 'Ninja dependency cache'
    path = tree / name
    if not path.is_file() or path.is_symlink():
        return None
    with path.open('rb') as stream:
        magic = stream.read(8)
    compiled = magic.startswith(b'\x7fELF') or magic in {b'!<arch>\n', b'!<thin>\n'}
    if compiled and (leaf.endswith(('.o', '.a', '.lo')) or re.search(r'\.so(?:\.[0-9]+)*$', leaf)):
        return 'Compiler object/archive/shared library in a managed build tree'
    if compiled and leaf in {'busybox', 'busybox_unstripped', 'dropbear', 'dropbearmulti',
                             'dropbearkey', 'dropbearconvert', 'dbclient', 'scp',
                             'strace', 'strace-log-merge', 'vmlinux', 'conf', 'fixdep',
                             'genksyms', 'modpost', 'asn1_compiler', 'dtc', 'objtool'}:
        return 'Named executable produced by the managed source/build recipe'
    if leaf.endswith(('.pyc', '.pyo')) and magic[:2] != b'#!':
        return 'Python bytecode cache'
    return None


def _source_generated_reason(tree: Path, name: str, descriptor: dict, recipe: str | None) -> str | None:
    """Only three RAM tools compile in-source; other added binaries are evidence."""
    relative = PurePosixPath(name)
    if ('__pycache__' in relative.parts or 'autom4te.cache' in relative.parts
            or relative.name == '.ninja_deps' or relative.suffix in {'.pyc', '.pyo'}):
        return _generated_reason(tree, name, descriptor)
    if recipe is None:
        return None
    # Pinned build declarations: BusyBox applets/Kbuild.src and
    # scripts/Makefile.host; Dropbear Makefile.in (OBJ_DIR=./obj,
    # VPATH=./src); strace src/Makefile.am (Automake per-target prefixes).
    exact = {
        'busybox': {'busybox', 'busybox_unstripped', 'scripts/kconfig/conf', 'scripts/basic/fixdep',
                    'applets/usage', 'applets/usage_pod', 'applets/applet_tables'},
        'dropbear': {'dropbear', 'dropbearmulti', 'dropbearkey', 'dropbearconvert', 'dbclient', 'scp',
                     'conftest'},
        'strace': {'src/strace', 'src/strace-log-merge', 'src/libstrace.a', 'conftest',
                   'src/disable_ptrace', 'src/disable_ptrace_get_syscall_info',
                   'src/disable_ptrace_getregset', 'src/disable_ptrace_set_syscall_info'},
    }
    if name in exact[recipe]:
        return _recipe_compiled(tree, name, recipe)
    # Test fixtures may deliberately be ELF objects or archives. Never infer
    # that their newly added binary data was produced by the build.
    if set(relative.parts) & {'test', 'tests', 'testing', 'testsuite', 'fixtures', 'examples'}:
        return None
    if relative.suffix in {'.o', '.lo'}:
        source = tree / relative.with_suffix('')
        if recipe == 'dropbear' and relative.parent == PurePosixPath('obj'):
            source = tree / 'src' / relative.stem
        if recipe == 'strace' and relative.parent == PurePosixPath('src'):
            prefixes = ('libstrace_a-', 'strace-', 'disable_ptrace-',
                        'disable_ptrace_get_syscall_info-', 'disable_ptrace_getregset-',
                        'disable_ptrace_set_syscall_info-')
            stem = next((relative.stem[len(prefix):] for prefix in prefixes
                         if relative.stem.startswith(prefix)), relative.stem)
            if re.fullmatch(r'ioctlsort[0-9]*', stem):
                stem = 'ioctlsort'
            source = tree / 'src' / stem
        if relative.name == 'built-in.o' or any(source.with_name(source.name + ext).is_file()
                                               for ext in ('.c', '.S', '.s', '.cpp', '.cc')):
            return _recipe_compiled(tree, name, recipe)
    if (recipe == 'strace' and re.fullmatch(r'src/ioctlsort[0-9]*', name)
            and (tree / 'src/ioctlsort.c').is_file()):
        return _recipe_compiled(tree, name, recipe)
    if relative.name in {'lib.a', 'built-in.a', 'libtomcrypt.a', 'libtommath.a'}:
        return _recipe_compiled(tree, name, recipe)
    return None


def _recipe_compiled(tree: Path, name: str, recipe: str) -> str | None:
    path = tree / name
    if path.is_file() and not path.is_symlink():
        with path.open('rb') as stream:
            magic = stream.read(8)
        if magic.startswith(b'\x7fELF') or magic in {b'!<arch>\n', b'!<thin>\n'}:
            return f'Compiled output declared by the pinned {recipe} build recipe'
    return None


def _generated_tree_reason(tree: Path, name: str, descriptor: dict) -> str | None:
    reason = _generated_reason(tree, name, descriptor)
    if reason:
        return reason
    if PurePosixPath(name).suffix in {'.qmlc', '.jsc', '.rcc', '.qsb'}:
        return 'Compiled Qt resource/cache in a generated build/install directory'
    path = tree / name
    if not path.is_file() or path.is_symlink():
        return None
    # These directories are installation/build outputs, never source inputs.
    # Source-looking additions, configs, logs, reports and unknown binary data
    # remain recoverable; executable ELF output is reproducible compilation.
    with path.open('rb') as stream:
        magic = stream.read(8)
    if magic.startswith(b'\x7fELF') or magic in {b'!<arch>\n', b'!<thin>\n'}:
        return 'Compiled binary in an enumerated generated build/install directory'
    return None


def _capture_source(root: Path, entry: dict, store: Path) -> dict:
    import preservation
    tree = entry['tree']
    manifest = _manifest(root)
    recipe = next((key for key in ('busybox', 'dropbear', 'strace')
                   if key in manifest['archives'] and tree == root /
                   manifest['archives'][key]['extract_to'] /
                   manifest['archives'][key]['top_directory']), None)
    exclude = lambda name, desc: _source_generated_reason(tree, name, desc, recipe)
    kind = entry.get('kind', 'tree')
    if kind == 'tar':
        result = preservation.capture_tar_tree(root, tree, entry['archive'], entry['sha256'],
                                              store, exclude_generated=exclude)
    elif kind == 'git':
        result = preservation.capture_git_tree(root, tree, store, exclude_generated=exclude)
    elif kind == 'tree':
        result = preservation.capture_tree(root, tree, store, exclude_generated=exclude)
    else:
        raise ValueError(f'Unknown preservation kind: {kind}')
    if result.get('verified') is not True:
        raise CleanupDeferred(f'Source snapshot was not verified: {tree}')
    return result


def _capture_generated(root: Path, tree: Path, store: Path, *, artifacts=(), source_roots=(),
                       generated_directory=False) -> dict:
    import preservation
    artifact_paths = set(artifacts)
    source_roots = set(source_roots)

    def exclude(name, descriptor):
        parts = PurePosixPath(name).parts
        if any(name == prefix or name.startswith(prefix + '/') for prefix in source_roots):
            return 'Source tree has its own verified upstream-delta snapshot'
        if name in artifact_paths:
            return 'Verified final artifact is retained in the compact image bundle'
        if parts and parts[0] in {'kernel-build', 'rootfs', 'helpers'}:
            if descriptor.get('kind') == 'file' and _kernel_payload(name):
                return 'Known payload produced by the kernel build recipe'
            return _generated_tree_reason(tree, name, descriptor)
        if name in {'initramfs.cpio', 'initramfs.cpio.new', 'initramfs.cpio.tmp', 'board.dtb'}:
            return 'Known payload produced by the managed image recipe'
        return _generated_tree_reason(tree, name, descriptor) if generated_directory else None

    result = preservation.capture_tree(root, tree, store, exclude_generated=exclude)
    if result.get('verified') is not True:
        raise CleanupDeferred(f'Generated-tree snapshot was not verified: {tree}')
    return result


def _kernel_payload(name: str) -> bool:
    """Raw/compressed linked images have no ELF magic; enumerate their recipes."""
    compression = r'(?:\.(?:gz|gzip|bz2|xz|xzkern|lzma|lzo|lz4|zst|zstd))?'
    if re.fullmatch(r'kernel-build/arch/arm/boot/(?:zImage|Image)' + compression, name):
        return True
    if re.fullmatch(r'kernel-build/arch/arm/boot/compressed/(?:piggy_data|piggy' +
                    compression + r'|vmlinux\.bin)', name):
        return True
    if re.fullmatch(r'kernel-build/usr/initramfs_data\.cpio' + compression + r'(?:\.(?:new|tmp))?', name):
        return True
    if name in {'kernel-build/usr/initramfs_inc_data', 'kernel-build/vmlinux.bin'}:
        return True
    return (name.startswith('kernel-build/arch/arm/boot/dts/') and
            PurePosixPath(name).suffix in {'.dtb', '.dtbo'})


def _check(records: list[tuple[Path, dict]]) -> None:
    import preservation
    for tree, record in records:
        if not preservation.snapshot_matches_tree(record, tree):
            raise CleanupDeferred(f'Tree changed after its snapshot; kept original: {tree}')


def _compact(root: Path, output: Path, destination: Path, retained: dict) -> None:
    """Copy final payloads and readable build records, without expanded trees."""
    destination.mkdir(parents=True)
    paths = {entry['path'] for entry in retained['artifacts'].values()}
    paths.update(str(path.relative_to(output)) for path in output.iterdir()
                 if path.is_file() and not path.is_symlink())
    # Always retain these unique configuration/symbol records used by audits.
    for name in ('kernel-build/.config', 'kernel-build/System.map'):
        if (output / name).is_file():
            paths.add(name)
    for folder in ('logs', 'rootfs-config', 'source-inputs', 'input-records'):
        directory = output / folder
        if directory.exists():
            for path in directory.rglob('*'):
                if path.is_file() and not path.is_symlink():
                    paths.add(path.relative_to(output).as_posix())
    for name in sorted(paths):
        path = _artifact_path(output, name)
        # Unknown executable/compiler output is preserved by the snapshot rules,
        # but only declared payloads are retained in the final bundle.
        if name not in {entry['path'] for entry in retained['artifacts'].values()} and _generated_tree_reason(output, name, {}):
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    _write(destination / 'retained-build.json', retained)
    verify_artifacts(destination, retained['artifacts'])


def _helper(root: Path, survivor: Path, retained: dict, retiring: list[Path]) -> tuple[Path, str] | None:
    """Keep the bounded ADC postflight helper available when its bundle ages out."""
    runtime = root / ADC_HOME / 'restore-adc-measurements'
    runtime_target = runtime.resolve(strict=True) if runtime.is_symlink() else None
    current = runtime_target if runtime_target is not None and any(
        runtime_target.is_relative_to(path) for path in retiring) else None
    for path in retiring:
        candidate = path / 'helpers/restore-adc-measurements'
        if candidate.is_file():
            current = candidate
    if current is None:
        return None
    authorization = _json(_local(root, ADC_HOME / 'adc-postflight-authorization.json'))
    if (authorization.get('authorized') is not True or authorization.get('helper_sha256') != ADC_SHA256
            or digest(current) != ADC_SHA256):
        raise CleanupDeferred('The ADC postflight helper does not match its saved approval')
    target = survivor / 'helpers/restore-adc-measurements'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current, target)
    retained['artifacts']['approved-adc-postflight-helper'] = {
        'path': 'helpers/restore-adc-measurements', 'bytes': target.stat().st_size,
        'sha256': ADC_SHA256}
    _write(survivor / 'retained-build.json', retained)
    if runtime_target is not None and any(runtime_target.is_relative_to(path) for path in retiring):
        return runtime, 'helpers/restore-adc-measurements'
    if not runtime.exists() and not runtime.is_symlink():
        return runtime, 'helpers/restore-adc-measurements'
    return None


def _cleanup(root: Path, output: Path, *, destination: Path | None, cleanup_inputs: bool,
             keep: int, source_inputs, failed: bool, keep_work: bool = False) -> dict:
    if keep != 2:
        raise ValueError('The project retention policy keeps exactly two successful builds')
    root = Path(root).resolve()
    output = _output(root, output, staging=True)
    if failed and output.parent != root / OUT / '.work':
        raise ValueError('Failed cleanup only accepts isolated .work directories')
    destination = _output(root, destination or output) if not failed else None
    if keep_work and output.parent != root / OUT / '.work':
        raise ValueError('Keeping full work requires an isolated .work directory')
    if keep_work:
        cleanup_inputs = False
    if not output.is_dir():
        raise ValueError(f'Build output does not exist: {output}')
    status = {'state': 'cleanup-deferred', 'output': str(output), 'removed': [], 'pruned': []}
    compact = None
    try:
        with _cleanup_lock(root) as manager:
            retained = None if failed else _admission(output)
            registry = _registry(root)
            sources = _sources(root, output, source_inputs, cleanup_inputs)
            generated = [_local(root, name) for name in GENERATED] if cleanup_inputs else []
            generated = [path for path in generated if path.exists()]
            if destination is not None:
                registry['builds'][destination.name] = {
                    'completed_utc': retained['completed_utc'], 'kernel': retained.get('kernel')}
            ranked = sorted(registry['builds'], key=lambda name: (
                _date(registry['builds'][name]['completed_utc']), name), reverse=True)
            survivors = set(ranked[:keep])
            if destination is not None:
                survivors.add(destination.name)
                # The current successful build is protected even with bad host clocks.
                survivors = {destination.name, *[name for name in ranked if name != destination.name][:keep - 1]}
            pruning = [_output(root, root / OUT / name) for name in ranked if name not in survivors]
            replacing = [destination] if destination and destination.exists() else []
            retiring = list(dict.fromkeys(pruning + replacing))
            # A stale/corrupted registry cannot turn arbitrary data into a prune target.
            old_manifests = {}
            for path in retiring:
                if path == output:
                    continue
                old = _json(path / 'retained-build.json')
                old['artifacts'] = verify_artifacts(path, old['artifacts'])
                old_manifests[path] = old
            store = _local(root, PRIVATE / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex))
            store.mkdir(parents=True, mode=0o700)
            status['snapshot_store'] = str(store)
            records = []
            for entry in sources:
                records.append((entry['tree'], _capture_source(root, entry, store)))
            for tree in generated:
                records.append((tree, _capture_generated(root, tree, store, generated_directory=True)))
            artifacts = () if failed else [entry['path'] for entry in retained['artifacts'].values()]
            source_roots = [str(entry['tree'].relative_to(output)) for entry in sources
                            if entry['tree'].is_relative_to(output)]
            records.append((output, _capture_generated(root, output, store,
                                                      artifacts=artifacts, source_roots=source_roots)))
            for path, old in old_manifests.items():
                records.append((path, _capture_generated(root, path, store,
                    artifacts=[entry['path'] for entry in old['artifacts'].values()])))
            _write(store / 'cleanup.json', {'format_version': 1, 'output': str(output),
                   'failed': failed, 'snapshots': [{'tree': str(tree), **record} for tree, record in records]})
            _check(records)
            helper = None
            if not failed:
                compact = _local(root, manager / ('compact-' + uuid.uuid4().hex))
                _compact(root, output, compact, retained)
                helper = _helper(root, compact, retained, retiring)
                verify_artifacts(compact, retained['artifacts'])
                _check(records)
                # Keep the old successful folder recoverable until the new bundle
                # has been promoted. Roll back the rename if promotion fails.
                previous = None
                if destination.exists():
                    previous = manager / ('replaced-' + uuid.uuid4().hex)
                    destination.rename(previous)
                try:
                    compact.rename(destination)
                except Exception:
                    if previous is not None:
                        previous.rename(destination)
                    raise
                if helper:
                    runtime, relative = helper
                    temporary = runtime.with_name('.restore-adc-' + uuid.uuid4().hex)
                    temporary.symlink_to(os.path.relpath(destination / relative, runtime.parent))
                    temporary.replace(runtime)
                if previous is not None:
                    shutil.rmtree(previous)
                for path in pruning:
                    _check([(path, next(record for tree, record in records if tree == path))])
                    shutil.rmtree(path)
                    del registry['builds'][path.name]
                    status['pruned'].append(str(path))
                _write(manager / 'registry.json', registry)
                status['destination'] = str(destination)
                status['retained'] = sorted(registry['builds'])
            # Source subtrees inside output were already removed with the old
            # full output directory (or are removed with failed/staged work below).
            for tree, record in records:
                if tree == output or tree in retiring or tree.is_relative_to(output):
                    continue
                if tree in generated or any(tree == item['tree'] for item in sources):
                    _check([(tree, record)])
                    shutil.rmtree(tree)
                    status['removed'].append(str(tree))
            if (failed or output != destination) and not keep_work:
                shutil.rmtree(output)
                status['removed'].append(str(output))
            status['state'] = 'failed-work-cleaned' if failed else 'cleaned'
            _write(store / 'result.json', status)
    except (CleanupDeferred, OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        status['reason'] = str(error)
        # A failed cleanup must never turn a successful image build into failure.
        # Keep its paths and private recovery records available for a later retry.
    finally:
        # This is our newly created copy, never an original work/source tree.
        if compact is not None and compact.exists():
            shutil.rmtree(compact)
    return status


def finalize_build(root: Path, output: Path, *, destination: Path | None = None,
                   cleanup_inputs: bool = True, keep: int = 2, source_inputs=None,
                   keep_work: bool = False) -> dict:
    """Finalize one audited build; return cleanup-deferred instead of deleting on doubt.

    output is either a direct managed version folder or out/.work/<build-id>.
    Staged builds require destination=out/<version>. source_inputs is an optional
    list of {tree, kind, archive, sha256} entries for explicitly owned input trees.
    The caller holds build_lock across compilation and this operation.
    """
    return _cleanup(root, output, destination=destination, cleanup_inputs=cleanup_inputs,
                    keep=keep, source_inputs=source_inputs, failed=False, keep_work=keep_work)


def cleanup_failed(root: Path, output: Path, *, cleanup_inputs: bool = True,
                   source_inputs=None) -> dict:
    """Preserve source changes and diagnostics, then remove failed isolated work."""
    return _cleanup(root, output, destination=None, cleanup_inputs=cleanup_inputs,
                    keep=2, source_inputs=source_inputs, failed=True)
