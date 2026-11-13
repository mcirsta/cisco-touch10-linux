"""Audited retention and source preservation exercised in isolated fixtures only."""
from __future__ import annotations

import fcntl
import hashlib
import io
import json
from pathlib import Path
import sys
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lifecycle
import preservation


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.out = self.root / lifecycle.OUT
        self.out.mkdir(parents=True)
        self.source = self.root / 'development/sources/linux-6.18.48'
        self.archive = self.source.parent / 'linux-6.18.48.tar.xz'
        self.archive.parent.mkdir(parents=True)
        with tarfile.open(self.archive, 'w:xz') as package:
            directory = tarfile.TarInfo('linux-6.18.48')
            directory.type, directory.mode = tarfile.DIRTYPE, 0o755
            package.addfile(directory)
            member = tarfile.TarInfo('linux-6.18.48/hello.c')
            payload = b'int upstream = 1;\n'
            member.size, member.mode = len(payload), 0o644
            package.addfile(member, io.BytesIO(payload))
        write_json(self.root / 'development/standalone/inputs.json', {
            'archives': {'linux': {
                'extract_to': 'development/sources', 'top_directory': self.source.name,
                'destination': str(self.archive.relative_to(self.root)),
                'sha256': lifecycle.digest(self.archive)}}, 'git': {}})

    def unpack(self):
        with tarfile.open(self.archive) as package:
            package.extractall(self.source.parent, filter='data')
        return self.source

    def build(self, version, date, *, suffix='', audit=True):
        work = self.out / '.work' / (version + suffix)
        work.mkdir(parents=True)
        artifacts = {}
        for name, relative in (
            ('zImage', 'kernel-build/arch/arm/boot/zImage'),
            ('board.dtb', 'board.dtb'), ('initramfs.cpio', 'initramfs.cpio'),
            ('kernel.config', 'kernel.config'),
        ):
            path = work / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((version + suffix + ':' + name).encode())
            artifacts[name] = {'path': relative, 'bytes': path.stat().st_size,
                               'sha256': lifecycle.digest(path)}
        (work / 'kernel-build/intermediate.o').write_bytes(b'\x7fELFcompiled object')
        (work / 'kernel-build/.config').write_text('CONFIG_SMP=y\n')
        (work / 'logs').mkdir()
        (work / 'logs/compiler.log').write_text('unique compiler diagnostic\n')
        (work / 'source-inputs').mkdir()
        (work / 'source-inputs/local.patch').write_text('source recipe\n')
        (work / 'input-records').mkdir()
        (work / 'input-records/rootfs-build.json').write_text('{"fresh": true}\n')
        report = {'state': 'built-and-audited', 'kernel': 'linux-' + version,
                  'completed_utc': date, 'stages': {
                      name: {'passed': True} for name in ('inputs', 'userspace', 'rootfs', 'kernel')}}
        write_json(work / 'build.json', report)
        if audit:
            write_json(work / 'kernel-build.json', {'passed': True, 'kernel': report['kernel'],
                       'profile': version, 'artifacts': artifacts, 'live_tested': False})
        return work

    def finalize(self, version, date, **kwargs):
        work = self.build(version, date)
        result = lifecycle.finalize_build(self.root, work,
                    destination=self.out / version, **kwargs)
        self.assertEqual(result['state'], 'cleaned', result)
        return result

    def restored(self, result, tree):
        records = json.loads((Path(result['snapshot_store']) / 'cleanup.json').read_text())
        record = next(record for record in records['snapshots'] if record['tree'] == str(tree))
        target = self.root / ('restored-' + str(len(list(self.root.glob('restored-*')))))
        preservation.restore_snapshot(record, target)
        return target

    def test_three_builds_keep_two_and_rebuild_version_replaces_it(self):
        self.finalize('ram201', '2026-01-01T01:00:00+00:00')
        self.finalize('ram202', '2026-01-01T02:00:00+00:00')
        third = self.finalize('ram203', '2026-01-01T03:00:00+00:00')
        self.assertFalse((self.out / 'ram201').exists())
        self.assertEqual(third['retained'], ['ram202', 'ram203'])
        self.assertEqual(self.restored(third, self.out / 'ram201').joinpath('logs/compiler.log').read_text(),
                         'unique compiler diagnostic\n')
        replacement = self.build('ram203', '2026-01-01T04:00:00+00:00', suffix='-new')
        result = lifecycle.finalize_build(self.root, replacement, destination=self.out / 'ram203')
        self.assertEqual(result['state'], 'cleaned', result)
        self.assertEqual(result['retained'], ['ram202', 'ram203'])
        self.assertIn(b'ram203-new', (self.out / 'ram203/initramfs.cpio').read_bytes())
        self.assertFalse((self.out / 'ram203/kernel-build/intermediate.o').exists())
        self.assertTrue((self.out / 'ram203/kernel-build/.config').exists())
        self.assertTrue((self.out / 'ram203/source-inputs/local.patch').exists())
        self.assertTrue((self.out / 'ram203/input-records/rootfs-build.json').exists())

    def test_changed_source_new_binary_fixture_and_config_survive_cleanup(self):
        source = self.unpack()
        (source / 'hello.c').write_text('int unpublished = 2;\n')
        (source / 'fixture.bin').write_bytes(b'\x00\xffunique source fixture')
        (source / '.config').write_text('CONFIG_NEW=y\n')
        (source / 'generated.o').write_bytes(b'\x7fELFobject output')
        generated = self.root / 'development/perrier-qt/build-local-qtbase'
        generated.mkdir(parents=True)
        (generated / 'manual-source.c').write_text('int unpublished_in_build;\n')
        (generated / 'qt-tool').write_bytes(b'\x7fELFtool output')
        (generated / 'built-in.a').write_bytes(b'!<thin>\nreproduced thin archive')
        (generated / '.ninja_deps').write_bytes(b'cache data')
        result = self.finalize('ram201', '2026-01-01T01:00:00+00:00')
        self.assertFalse(source.exists())
        self.assertFalse(generated.exists())
        restored = self.restored(result, source)
        self.assertEqual((restored / 'hello.c').read_text(), 'int unpublished = 2;\n')
        self.assertEqual((restored / 'fixture.bin').read_bytes(), b'\x00\xffunique source fixture')
        self.assertTrue((restored / '.config').exists())
        self.assertEqual((restored / 'generated.o').read_bytes(), b'\x7fELFobject output')
        restored_build = self.restored(result, generated)
        self.assertTrue((restored_build / 'manual-source.c').exists())
        self.assertFalse((restored_build / 'qt-tool').exists())
        self.assertFalse((restored_build / 'built-in.a').exists())
        self.assertFalse((restored_build / '.ninja_deps').exists())
        self.assertTrue(self.archive.exists())

    def test_failed_partial_payloads_removed_diagnostics_and_source_preserved(self):
        self.finalize('ram201', '2026-01-01T01:00:00+00:00')
        source = self.unpack()
        (source / 'hello.c').unlink()
        work = self.build('failed', '2026-01-01T02:00:00+00:00', audit=False)
        reproduced = (
            'kernel-build/usr/initramfs_inc_data',
            'kernel-build/usr/initramfs_data.cpio.gz',
            'kernel-build/arch/arm/boot/Image',
            'kernel-build/arch/arm/boot/compressed/piggy_data',
            'kernel-build/arch/arm/boot/compressed/piggy.xzkern',
            'kernel-build/arch/arm/boot/dts/ti/omap4-perrier.dtb',
            'initramfs.cpio.new', 'initramfs.cpio.tmp', 'rootfs/qt/cache/item.qmlc',
        )
        for relative in reproduced:
            path = work / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'raw or compressed build output, without ELF magic')
        (work / 'kernel-build/manual-evidence.bin').write_bytes(b'unknown unique binary evidence')
        result = lifecycle.cleanup_failed(self.root, work)
        self.assertEqual(result['state'], 'failed-work-cleaned', result)
        self.assertFalse(work.exists())
        self.assertTrue((self.out / 'ram201/initramfs.cpio').exists())
        restored = self.restored(result, work)
        self.assertTrue((restored / 'logs/compiler.log').exists())
        self.assertFalse((restored / 'initramfs.cpio').exists())
        self.assertFalse((restored / 'kernel-build/arch/arm/boot/zImage').exists())
        for relative in reproduced:
            self.assertFalse((restored / relative).exists(), relative)
        self.assertEqual((restored / 'kernel-build/manual-evidence.bin').read_bytes(),
                         b'unknown unique binary evidence')
        self.assertFalse((self.restored(result, source) / 'hello.c').exists())

    def test_failed_or_unaudited_current_build_never_replaces_success(self):
        self.finalize('ram201', '2026-01-01T01:00:00+00:00')
        old = (self.out / 'ram201/initramfs.cpio').read_bytes()
        work = self.build('ram201', '2026-01-01T02:00:00+00:00', suffix='-bad')
        report = json.loads((work / 'build.json').read_text())
        report['state'] = 'failed-kernel'
        write_json(work / 'build.json', report)
        result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertEqual(result['state'], 'cleanup-deferred')
        self.assertTrue(work.exists())
        self.assertEqual(old, (self.out / 'ram201/initramfs.cpio').read_bytes())
        with self.assertRaisesRegex(ValueError, 'isolated'):
            lifecycle.cleanup_failed(self.root, self.out / 'ram201')

    def test_changed_artifact_aborts_before_compaction_or_any_pruning(self):
        work = self.build('ram201', '2026-01-01T01:00:00+00:00')
        (work / 'board.dtb').write_bytes(b'changed after audit')
        result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertEqual(result['state'], 'cleanup-deferred')
        self.assertIn('Artifact verification', result['reason'])
        self.assertTrue(work.exists())
        self.assertFalse((self.out / 'ram201').exists())

    def test_active_ram_runner_defers_without_removing_anything(self):
        source = self.unpack()
        work = self.build('ram201', '2026-01-01T01:00:00+00:00')
        lock = self.root / 'development/.runner.lock'
        with lock.open('a+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertEqual(result['state'], 'cleanup-deferred')
        self.assertIn('RAM runner', result['reason'])
        self.assertTrue(work.exists())
        self.assertTrue(source.exists())

    def test_build_lock_is_exclusive_and_nonblocking(self):
        with lifecycle.build_lock(self.root):
            with self.assertRaisesRegex(lifecycle.CleanupDeferred, 'Another build'):
                with lifecycle.build_lock(self.root):
                    self.fail('Concurrent build acquired source lock')

    def test_unmanaged_or_symlink_output_cannot_be_deleted(self):
        work = self.build('ram201', '2026-01-01T01:00:00+00:00')
        outside = self.root / 'backups'
        outside.mkdir()
        with self.assertRaises(ValueError):
            lifecycle.finalize_build(self.root, work, destination=outside)
        (self.out / 'ram201').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertTrue(work.exists())
        self.assertTrue(outside.exists())

    def test_source_symlink_escape_is_left_intact(self):
        outside = self.root / 'backups'
        outside.mkdir()
        (outside / 'precious').write_text('device backup')
        self.source.symlink_to(outside, target_is_directory=True)
        work = self.build('ram201', '2026-01-01T01:00:00+00:00')
        result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertEqual(result['state'], 'cleanup-deferred')
        self.assertTrue(self.source.is_symlink())
        self.assertEqual((outside / 'precious').read_text(), 'device backup')
        self.assertTrue(work.exists())

    def test_changed_input_manifest_cannot_target_backups_or_root_git(self):
        backups = self.root / 'backups/stock'
        backups.mkdir(parents=True)
        (backups / 'raw.bin').write_bytes(b'unique device backup')
        manifest_path = self.root / 'development/standalone/inputs.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['archives']['linux']['extract_to'] = 'backups'
        manifest['archives']['linux']['top_directory'] = 'stock'
        write_json(manifest_path, manifest)
        work = self.build('ram201', '2026-01-01T01:00:00+00:00')
        result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertEqual(result['state'], 'cleanup-deferred')
        self.assertTrue((backups / 'raw.bin').exists())
        manifest['archives'] = {}
        manifest['git'] = {'source': {'destination': '.git'}}
        write_json(manifest_path, manifest)
        result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertEqual(result['state'], 'cleanup-deferred')
        self.assertTrue(work.exists())

    def test_legacy_bundles_adopt_manifest_dates_and_unregistered_data_is_kept(self):
        for name in ('ram116', 'ram117'):
            work = self.build(name, '2026-01-01T01:00:00+00:00')
            audit = json.loads((work / 'kernel-build.json').read_text())
            write_json(work / 'retained-build.json', {
                'retained_on': '2026-01-01', 'kernel': name, 'artifacts': audit['artifacts']})
            work.rename(self.out / name)
        unrelated = self.out / 'manual-investigation'
        unrelated.mkdir()
        (unrelated / 'unique.bin').write_bytes(b'unregistered evidence')
        result = self.finalize('ram118', '2026-01-01T03:00:00+00:00')
        self.assertEqual(result['retained'], ['ram117', 'ram118'])
        self.assertFalse((self.out / 'ram116').exists())
        self.assertEqual((unrelated / 'unique.bin').read_bytes(), b'unregistered evidence')

    def test_known_python_cache_removed_but_unknown_content_is_recoverable(self):
        cache = self.root / 'development/standalone/__pycache__'
        cache.mkdir(parents=True)
        (cache / 'build.cpython-314.pyc').write_bytes(b'compiled Python cache')
        (cache / 'unexpected-source.py').write_text('unpublished = True\n')
        result = self.finalize('ram201', '2026-01-01T01:00:00+00:00')
        self.assertFalse(cache.exists())
        restored = self.restored(result, cache)
        self.assertFalse((restored / 'build.cpython-314.pyc').exists())
        self.assertEqual((restored / 'unexpected-source.py').read_text(), 'unpublished = True\n')

    def test_changes_during_compaction_abort_and_remove_our_partial_copy(self):
        source = self.unpack()
        work = self.build('ram201', '2026-01-01T01:00:00+00:00')
        compact = lifecycle._compact

        def change_during_copy(*args, **kwargs):
            compact(*args, **kwargs)
            (source / 'hello.c').write_text('edit during compaction\n')

        with mock.patch.object(lifecycle, '_compact', side_effect=change_during_copy):
            result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertEqual(result['state'], 'cleanup-deferred')
        self.assertTrue(work.exists())
        self.assertEqual((source / 'hello.c').read_text(), 'edit during compaction\n')
        self.assertEqual(list((self.out / '.lifecycle').glob('compact-*')), [])

    def test_preservation_failure_or_race_keeps_original_trees(self):
        source = self.unpack()
        work = self.build('ram201', '2026-01-01T01:00:00+00:00')
        with mock.patch.object(lifecycle, '_capture_source', side_effect=RuntimeError('preserver failed')):
            result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertEqual(result['state'], 'cleanup-deferred')
        self.assertTrue(work.exists())
        self.assertTrue(source.exists())
        with mock.patch.object(lifecycle, '_capture_source', side_effect=subprocess.CalledProcessError(1, ['git'])):
            result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertEqual(result['state'], 'cleanup-deferred')
        self.assertTrue(work.exists())
        self.assertTrue(source.exists())
        real_match = preservation.snapshot_matches_tree
        raced = False

        def race(record, tree):
            nonlocal raced
            if tree == source and not raced:
                (source / 'hello.c').write_text('changed concurrently\n')
                raced = True
            return real_match(record, tree)

        with mock.patch.object(preservation, 'snapshot_matches_tree', side_effect=race):
            result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201')
        self.assertEqual(result['state'], 'cleanup-deferred')
        self.assertIn('changed after', result['reason'])
        self.assertTrue(work.exists())
        self.assertEqual((source / 'hello.c').read_text(), 'changed concurrently\n')
        self.assertFalse((self.out / 'ram201').exists())

    def test_in_source_tool_outputs_removed_while_binary_test_fixtures_preserved(self):
        archive = self.root / 'development/perrier-ramenv/downloads/busybox-1.37.0.tar.xz'
        archive.parent.mkdir(parents=True)
        with tarfile.open(archive, 'w:xz') as package:
            for name in ('busybox-1.37.0', 'busybox-1.37.0/libbb'):
                directory = tarfile.TarInfo(name)
                directory.type, directory.mode = tarfile.DIRTYPE, 0o755
                package.addfile(directory)
            member = tarfile.TarInfo('busybox-1.37.0/libbb/helper.c')
            member.size, member.mode = 5, 0o644
            package.addfile(member, io.BytesIO(b'int x'))
        source = self.root / 'development/perrier-ramenv/sources/busybox-1.37.0'
        source.parent.mkdir(parents=True)
        with tarfile.open(archive) as package:
            package.extractall(source.parent, filter='data')
        manifest_path = self.root / 'development/standalone/inputs.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['archives']['busybox'] = {
            'extract_to': str(source.parent.relative_to(self.root)),
            'top_directory': source.name, 'destination': str(archive.relative_to(self.root)),
            'sha256': lifecycle.digest(archive)}
        write_json(manifest_path, manifest)
        for name, data in (('busybox', b'\x7fELFbuilt executable'),
                           ('libbb/helper.o', b'\x7fELFbuilt object'),
                           ('libbb/lib.a', b'!<arch>\ncompiled archive'),
                           ('tools/testing/selftests/new-fixture.o', b'\x7fELFunique test evidence')):
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        result = self.finalize('ram201', '2026-01-01T01:00:00+00:00')
        restored = self.restored(result, source)
        self.assertFalse((restored / 'busybox').exists())
        self.assertFalse((restored / 'libbb/helper.o').exists())
        self.assertFalse((restored / 'libbb/lib.a').exists())
        self.assertEqual((restored / 'tools/testing/selftests/new-fixture.o').read_bytes(),
                         b'\x7fELFunique test evidence')

    def test_registered_in_source_recipe_maps_real_upstream_output_names(self):
        policies = {
            'busybox': {
                'sources': ('applets/usage.c', 'applets/usage_pod.c', 'applets/applet_tables.c'),
                'outputs': ('applets/usage', 'applets/usage_pod', 'applets/applet_tables'),
            },
            'dropbear': {
                'sources': ('src/dbutil.c', 'src/svr-main.c', 'libtomcrypt/src/misc/crypt.c'),
                'outputs': ('obj/dbutil.o', 'obj/svr-main.o', 'libtomcrypt/src/misc/crypt.o',
                            'libtomcrypt/libtomcrypt.a', 'libtommath/libtommath.a', 'conftest'),
            },
            'strace': {
                'sources': ('src/access.c', 'src/strace.c', 'src/ioctlsort.c',
                            'src/disable_ptrace.c', 'src/disable_ptrace_get_syscall_info.c',
                            'src/disable_ptrace_getregset.c', 'src/disable_ptrace_set_syscall_info.c'),
                'outputs': ('src/libstrace.a', 'src/libstrace_a-access.o', 'src/strace-strace.o',
                            'src/disable_ptrace', 'src/disable_ptrace_get_syscall_info',
                            'src/disable_ptrace_getregset', 'src/disable_ptrace_set_syscall_info',
                            'src/disable_ptrace-disable_ptrace.o', 'src/ioctlsort0',
                            'src/ioctlsort0.o', 'src/ioctlsort1', 'conftest'),
            },
        }
        for recipe, policy in policies.items():
            tree = self.root / recipe
            for source in policy['sources']:
                path = tree / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('int source;\n')
            for name in policy['outputs']:
                path = tree / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'!<arch>\narchive' if name.endswith('.a') else b'\x7fELFcompiled')
                with self.subTest(recipe=recipe, output=name):
                    self.assertIsNotNone(lifecycle._source_generated_reason(
                        tree, name, {'kind': 'file'}, recipe))
            for name in ('tests/fixture.o', 'src/unknown-fixture.o', 'unknown-program'):
                path = tree / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'\x7fELFunique fixture')
                with self.subTest(recipe=recipe, unknown=name):
                    self.assertIsNone(lifecycle._source_generated_reason(
                        tree, name, {'kind': 'file'}, recipe))

    def test_keep_work_retains_sources_and_full_work_but_promotes_compact(self):
        source = self.unpack()
        work = self.build('ram201', '2026-01-01T01:00:00+00:00')
        result = lifecycle.finalize_build(self.root, work, destination=self.out / 'ram201', keep_work=True)
        self.assertEqual(result['state'], 'cleaned', result)
        self.assertTrue(source.exists())
        self.assertTrue(work.exists())
        self.assertTrue((work / 'kernel-build/intermediate.o').exists())
        self.assertFalse((self.out / 'ram201/kernel-build/intermediate.o').exists())

    def test_adc_helper_rehomed_before_retiring_its_bundle(self):
        self.finalize('ram201', '2026-01-01T01:00:00+00:00')
        old = self.out / 'ram201'
        helper = old / 'helpers/restore-adc-measurements'
        helper.parent.mkdir()
        helper.write_bytes(b'approved fixture helper')
        helper_sha = lifecycle.digest(helper)
        retained = json.loads((old / 'retained-build.json').read_text())
        retained['artifacts']['approved-adc-postflight-helper'] = {
            'path': 'helpers/restore-adc-measurements', 'bytes': helper.stat().st_size,
            'sha256': helper_sha}
        write_json(old / 'retained-build.json', retained)
        home = self.root / lifecycle.ADC_HOME
        home.mkdir(parents=True)
        write_json(home / 'adc-postflight-authorization.json', {
            'authorized': True, 'helper_sha256': helper_sha,
            'restored_values': {'48:e4': '00', '49:04': '04', '49:06': '14'}})
        runtime = home / 'restore-adc-measurements'
        runtime.symlink_to(helper)
        self.finalize('ram202', '2026-01-01T02:00:00+00:00')
        with mock.patch.object(lifecycle, 'ADC_SHA256', helper_sha):
            result = self.finalize('ram203', '2026-01-01T03:00:00+00:00')
        self.assertFalse(old.exists())
        self.assertEqual(runtime.resolve(), self.out / 'ram203/helpers/restore-adc-measurements')
        self.assertEqual(runtime.read_bytes(), b'approved fixture helper')
        retained = json.loads((self.out / 'ram203/retained-build.json').read_text())
        lifecycle.verify_artifacts(self.out / 'ram203', retained['artifacts'])

    def test_current_build_is_kept_even_when_host_clock_moves_backwards(self):
        self.finalize('ram201', '2026-01-03T01:00:00+00:00')
        self.finalize('ram202', '2026-01-03T02:00:00+00:00')
        result = self.finalize('ram203', '2026-01-01T03:00:00+00:00')
        self.assertEqual(result['retained'], ['ram202', 'ram203'])


if __name__ == '__main__':
    unittest.main()
