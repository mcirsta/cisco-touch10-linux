"""Host-only checks for boot identity and passive capture; never accesses the panel."""
import os
from pathlib import Path
import pty
import select
import tempfile
import time
import unittest
from unittest import mock

import touch10_dev
from touch10_dev import SerialCapture, wait_for_stock


class Clock:
    value = 0.0

    def now(self):
        return self.value

    def sleep(self, delay):
        self.value += delay


class PanelSequence:
    def __init__(self, items):
        self.items = iter(items)
        self.last = None

    def snapshot(self):
        self.last = next(self.items, self.last)
        if isinstance(self.last, Exception):
            raise self.last
        return self.last


class BootIdentityTests(unittest.TestCase):
    def setUp(self):
        self.before = dict(hostname="panel", kernel="3.4.113+", boot_id="old", factory_app="running")
        self.clock = Clock()

    def wait(self, entries):
        return wait_for_stock(PanelSequence(entries), self.before, 6, 1,
                              self.clock.now, self.clock.sleep)

    def test_old_ssh_session_is_not_a_completed_reboot(self):
        with self.assertRaises(TimeoutError):
            self.wait([self.before])

    def test_recovery_requires_new_boot_and_factory_app(self):
        starting = dict(self.before, boot_id="new", factory_app="absent")
        ready = dict(starting, factory_app="running")
        self.assertEqual(self.wait([RuntimeError("offline"), self.before, starting, ready]), ready)
        self.assertEqual(self.clock.value, 3)

    def test_wrong_host_stops_instead_of_rebooting_again(self):
        with self.assertRaises(ValueError):
            self.wait([dict(self.before, boot_id="new", hostname="other")])

    def test_different_kernel_is_not_factory_recovery(self):
        with self.assertRaises(TimeoutError):
            self.wait([dict(self.before, boot_id="new", kernel="6.18-test")])


class SerialTests(unittest.TestCase):
    def test_captures_boot_bytes_without_transmitting(self):
        master, slave = pty.openpty()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                payload = b"U-Boot\r\nStarting kernel\r\npartial"
                with SerialCapture(os.ttyname(slave), directory) as capture:
                    self.assertFalse(select.select([master], [], [], 0.05)[0])
                    os.write(master, payload)
                    deadline = time.monotonic() + 2
                    while capture.byte_count < len(payload) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertFalse(select.select([master], [], [], 0.05)[0])
                self.assertIsNone(capture.error)
                self.assertEqual((directory / "serial.raw").read_bytes(), payload)
                self.assertIn("Starting kernel", (directory / "serial.log").read_text())
        finally:
            os.close(master)
            os.close(slave)


class TrialGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        directory = root / "development/ram"
        directory.mkdir(parents=True)
        fixtures = {
            "arm-watchdog": (b"reviewed helper", "ARM_WATCHDOG_SHA256"),
            "kexec-qualified": (b"reviewed loader", "KEXEC_LOADER_SHA256"),
            "kexec-stall.zImage": (b"reviewed stub", "KEXEC_STALL_SHA256"),
        }
        patches = [mock.patch.object(touch10_dev, "ROOT", root)]
        for name, (payload, constant) in fixtures.items():
            (directory / name).write_bytes(payload)
            patches.append(mock.patch.object(
                touch10_dev, constant, touch10_dev.hashlib.sha256(payload).hexdigest()))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_changed_watchdog_helper_is_rejected_before_upload(self):
        panel = mock.Mock()
        report = {"before": {"kexec_loaded": "0"}}
        with mock.patch.object(touch10_dev, "ARM_WATCHDOG_SHA256", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "differs from reviewed"):
                touch10_dev.armed_watchdog_request(panel, report, False)
        panel.stage_ram.assert_not_called()

    def test_execution_requires_prior_closed_fd_recovery(self):
        panel = mock.Mock()
        report = {"before": {"kexec_loaded": "0"}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "development/ram").mkdir(parents=True)
            (root / "development/ram/arm-watchdog").write_bytes(b"reviewed helper")
            (root / "development/ram/kexec-stall.zImage").write_bytes(b"reviewed stub")
            loader = root / "development/ram/kexec-qualified"
            loader.parent.mkdir(parents=True, exist_ok=True)
            loader.write_bytes(b"reviewed loader")
            with mock.patch.object(touch10_dev, "ROOT", root), \
                 mock.patch.object(touch10_dev, "ARM_WATCHDOG_SHA256", touch10_dev.hashlib.sha256(b"reviewed helper").hexdigest()), \
                 mock.patch.object(touch10_dev, "KEXEC_LOADER_SHA256", touch10_dev.hashlib.sha256(b"reviewed loader").hexdigest()), \
                 mock.patch.object(touch10_dev, "KEXEC_STALL_SHA256", touch10_dev.hashlib.sha256(b"reviewed stub").hexdigest()):
                with self.assertRaisesRegex(RuntimeError, "must pass before kexec"):
                    touch10_dev.armed_watchdog_request(panel, report, True)
        panel.stage_ram.assert_not_called()

    def test_changed_loader_is_rejected_before_upload(self):
        panel = mock.Mock()
        with mock.patch.object(touch10_dev, "KEXEC_LOADER_SHA256", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "loader differs from reviewed"):
                touch10_dev.armed_watchdog_request(panel, {"before": {"kexec_loaded": "0"}}, False)
        panel.stage_ram.assert_not_called()

    def test_existing_kexec_image_is_not_replaced(self):
        panel = mock.Mock()
        with self.assertRaisesRegex(RuntimeError, "already loaded"):
            touch10_dev.armed_watchdog_request(panel, {"before": {"kexec_loaded": "1"}}, True)
        panel.stage_ram.assert_not_called()


if __name__ == "__main__":
    unittest.main()
