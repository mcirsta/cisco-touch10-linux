"""Rebuilding a dependency must not report an older image as freshly audited."""
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "standalone_build", Path(__file__).resolve().parents[1] / "build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class BuildDependencyStateTests(unittest.TestCase):
    def setUp(self):
        self.report = {
            "stages": {name: {"passed": True} for name in ("inputs", "userspace", "rootfs", "kernel")},
            "inputs": {"archive": "source-release"},
            "rootfs": {"initramfs_sha256": "previous-rootfs"},
            "kernel_build": {"embedded_initramfs_verified": True},
            "completed_utc": "previous-completion",
        }

    def test_rootfs_rebuild_invalidates_kernel_without_rebuilding_earlier_stages(self):
        inputs = self.report["inputs"]
        build.invalidate(self.report, "rootfs")
        self.assertEqual(set(self.report["stages"]), {"inputs", "userspace"})
        self.assertIs(self.report["inputs"], inputs)
        self.assertNotIn("rootfs", self.report)
        self.assertNotIn("kernel_build", self.report)
        self.assertNotIn("completed_utc", self.report)

    def test_userspace_rebuild_invalidates_rootfs_and_embedded_kernel(self):
        build.invalidate(self.report, "userspace")
        self.assertEqual(set(self.report["stages"]), {"inputs"})
        self.assertEqual(self.report["inputs"]["archive"], "source-release")
        self.assertNotIn("rootfs", self.report)
        self.assertNotIn("kernel_build", self.report)

    def test_kernel_resume_preserves_all_prepared_dependencies(self):
        inputs, rootfs = self.report["inputs"], self.report["rootfs"]
        build.invalidate(self.report, "kernel")
        self.assertEqual(set(self.report["stages"]), {"inputs", "userspace", "rootfs"})
        self.assertIs(self.report["inputs"], inputs)
        self.assertIs(self.report["rootfs"], rootfs)
        self.assertNotIn("kernel_build", self.report)
        self.assertNotIn("completed_utc", self.report)


if __name__ == "__main__":
    unittest.main()
