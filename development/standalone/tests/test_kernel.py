"""Negative tests for the standalone image's non-negotiable RAM safeguards."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("standalone_kernel", HERE / "kernel.py")
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)


class KernelSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / ".config"
        self.text = (HERE / "kernel/ram116.config").read_text().replace(
            'CONFIG_INITRAMFS_SOURCE=""', 'CONFIG_INITRAMFS_SOURCE="/fresh-build/initramfs.cpio"')

    def check(self, text):
        self.path.write_text(text)
        return kernel.check_config(self.path)

    def test_ram116_config_keeps_both_cpus_and_watchdog(self):
        report = self.check(self.text)
        self.assertEqual(report["smp_cpus"], 2)
        self.assertTrue(report["watchdog_nowayout"])

    def test_rejects_missing_watchdog_nowayout(self):
        with self.assertRaisesRegex(AssertionError, "WATCHDOG_NOWAYOUT"):
            self.check(self.text.replace("CONFIG_WATCHDOG_NOWAYOUT=y", "# CONFIG_WATCHDOG_NOWAYOUT is not set"))

    def test_rejects_cpu_hotplug(self):
        with self.assertRaisesRegex(AssertionError, "HOTPLUG_CPU"):
            self.check(self.text.replace("# CONFIG_HOTPLUG_CPU is not set", "CONFIG_HOTPLUG_CPU=y"))

    def test_rejects_generic_omap_power_initialization(self):
        with self.assertRaises(AssertionError):
            self.check(self.text.replace("initcall_blacklist=omap2_common_pm_late_init ", ""))

    def test_rejects_inherited_disk_root_argument(self):
        with self.assertRaises(AssertionError):
            self.check(self.text.replace('CONFIG_CMDLINE="', 'CONFIG_CMDLINE="root=/dev/mmcblk0p3 '))

    def test_rejects_missing_fresh_archive(self):
        with self.assertRaises(AssertionError):
            self.check(self.text.replace('CONFIG_INITRAMFS_SOURCE="/fresh-build/initramfs.cpio"',
                                         'CONFIG_INITRAMFS_SOURCE=""'))


if __name__ == "__main__":
    unittest.main()
