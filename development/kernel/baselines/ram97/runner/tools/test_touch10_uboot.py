"""Host-only regression tests for interleaved UART handoff evidence."""
import unittest

from touch10_uboot import serial_handoff_markers


KERNEL = '6.18.48-perrier-ram73'
GUARD = b'PERRIER_GUARD_READY backend=linux-watchdog boot_grace=90 lease=60 watchdog=120'
# Exact guard-line interruption captured in the ram73 boot, without keys.
INTERLEAVED_GUARD = (
    b'PERRIER_GU[    5.419738] smsc95xx 1-1:1.0 eth0: Link is Down\r\n'
    b'ARD_READY backend=linux-watchdog boot_grace=90 lease=60 watchdog'
    b'[    5.419738] smsc95xx 1-1:1.0 eth0: Link is Down\r\n=120'
)


def capture(guard):
    return (b'PERRIER_ONESHOT_SAVED\r\n'
            b'[    0.000000] Linux version ' + KERNEL.encode() + b'\r\n'
            b'PERRIER_RAM_SSH_STARTED ip=10.77.10.10 version=ram73\r\n' +
            guard + b'\r\n')


class HandoffMarkerTests(unittest.TestCase):
    def test_uninterrupted_console_needs_no_reconstruction(self):
        markers, reconstructed = serial_handoff_markers(capture(GUARD), KERNEL)
        self.assertTrue(all(markers.values()))
        self.assertEqual(reconstructed, [])

    def test_real_double_printk_interruption_preserves_guard_proof(self):
        markers, reconstructed = serial_handoff_markers(capture(INTERLEAVED_GUARD), KERNEL)
        self.assertTrue(all(markers.values()))
        self.assertEqual(reconstructed, ['mainline_watchdog_ready'])

    def test_missing_guard_remains_missing(self):
        damaged = INTERLEAVED_GUARD.replace(b'PERRIER_GU', b'PERRIER_XX')
        markers, _ = serial_handoff_markers(capture(damaged), KERNEL)
        self.assertFalse(markers['mainline_watchdog_ready'])

    def test_wrong_candidate_kernel_remains_rejected(self):
        markers, _ = serial_handoff_markers(capture(INTERLEAVED_GUARD), KERNEL + '-wrong')
        self.assertFalse(markers['candidate_kernel'])
        self.assertFalse(markers['ram_ssh_started'])


if __name__ == '__main__':
    unittest.main()
