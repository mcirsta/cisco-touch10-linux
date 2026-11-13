"""Exercise the CLI's real lifecycle with tiny staged build fixtures."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
SPEC = importlib.util.spec_from_file_location('build_lifecycle_entry', HERE / 'build.py')
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


def artifacts(output):
    paths = {'zImage': 'kernel-build/arch/arm/boot/zImage', 'board.dtb': 'board.dtb',
             'initramfs.cpio': 'initramfs.cpio', 'kernel.config': 'kernel.config'}
    result = {}
    for name, relative in paths.items():
        p = output / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(('fixture-' + name).encode())
        result[name] = {'path': relative, 'size': p.stat().st_size,
                        'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    return result


class BuildLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.out = self.root / 'development/standalone/out'
        self.old = {}
        for name in ('ram116', 'ram117'):
            directory = self.out / name
            directory.mkdir(parents=True)
            data = {'kernel': name, 'retained_on': '2026-11-13',
                    'artifacts': artifacts(directory)}
            marker = directory / 'retained-build.json'
            marker.write_text(json.dumps(data))
            self.old[name] = marker.read_bytes()

    def invoke(self, *arguments, fail=False):
        def rootfs(root, output, **kwargs):
            (output / 'initramfs.cpio').write_bytes(b'070701-fresh-rootfs')
            return {'passed': True}

        def kernel(root, output, image):
            if fail:
                (output / 'experiment.c').write_text('unpublished source\n')
                (output / 'kernel-build').mkdir()
                (output / 'kernel-build/partial.o').write_bytes(b'\x7fELFpartial')
                raise RuntimeError('fixture compiler failure')
            report = {'passed': True, 'kernel': 'fixture-kernel', 'artifacts': artifacts(output)}
            (output / 'kernel-build.json').write_text(json.dumps(report))
            return report

        modules = {'inputs': types.SimpleNamespace(prepare=lambda *args: {}),
                   'rootfs': types.SimpleNamespace(build_rootfs=rootfs),
                   'kernel': types.SimpleNamespace(build=kernel)}
        with patch.dict(sys.modules, modules), patch.object(build, 'check_host', return_value={}), \
             patch.object(build, 'command'), patch.object(sys, 'argv', ['build.py', '--root', str(self.root), *arguments]), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            build.main()

    def test_success_promotes_audited_bundle_and_rotates_third(self):
        self.invoke('--output', str(self.out / 'ram118'))
        self.assertEqual({p.name for p in self.out.iterdir() if not p.name.startswith('.')},
                         {'ram117', 'ram118'})
        self.assertTrue((self.out / 'ram118/retained-build.json').is_file())
        self.assertFalse(any((self.out / '.work').iterdir()))
        self.assertFalse((self.out / 'ram118/rootfs').exists())
        self.assertFalse((self.out / 'ram118/kernel-build/partial.o').exists())

    def test_failure_preserves_changes_without_replacing_successes(self):
        with self.assertRaisesRegex(RuntimeError, 'fixture compiler failure'):
            self.invoke(fail=True)
        for name, marker in self.old.items():
            self.assertEqual((self.out / name / 'retained-build.json').read_bytes(), marker)
        self.assertFalse(any((self.out / '.work').iterdir()))
        store = self.root / 'development/source-preservation/auto'
        manifests = list(store.rglob('manifest.json'))
        self.assertTrue(manifests)
        import preservation
        restored = self.root / 'restored-failure'
        output_snapshot = next(p for p in manifests
                               if json.loads(p.read_text())['original_tree'].startswith(
                                   'development/standalone/out/.work/'))
        preservation.restore_snapshot(output_snapshot, restored)
        self.assertEqual((restored / 'experiment.c').read_text(), 'unpublished source\n')
        self.assertFalse((restored / 'kernel-build/partial.o').exists())
        self.assertFalse((restored / 'initramfs.cpio').exists())

    def test_staged_build_waits_until_kernel_audit_then_cleans(self):
        self.invoke('--stage', 'inputs')
        work = list((self.out / '.work').iterdir())
        self.assertEqual(len(work), 1)
        self.assertEqual((self.out / 'ram116/retained-build.json').read_bytes(), self.old['ram116'])
        for stage in ('userspace', 'rootfs', 'kernel'):
            self.invoke('--stage', stage)
        self.assertFalse(work[0].exists())
        self.assertEqual(json.loads((self.out / 'ram116/build.json').read_text())['state'],
                         'built-and-audited')

    def test_resume_requires_current_build_dependencies(self):
        with patch.object(build, 'check_host', return_value={}):
            with self.assertRaisesRegex(RuntimeError, 'preceding stages'):
                build.run_stages(self.root, self.out / '.work/new', ('kernel',))

    def test_output_symlink_cannot_replace_another_bundle(self):
        (self.out / 'alias').symlink_to('ram117')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.invoke('--output', str(self.out / 'alias'))
        self.assertEqual((self.out / 'ram117/retained-build.json').read_bytes(), self.old['ram117'])

    def test_workspace_symlink_is_rejected_before_build_writes(self):
        outside = self.root / 'unrelated'
        outside.mkdir()
        (self.out / '.work').symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.invoke()
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
