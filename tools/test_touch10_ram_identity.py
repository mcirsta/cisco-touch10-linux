#!/usr/bin/env python3
"""Guard the RAM boot identity check against missing future profile entries."""
import json
import subprocess
import unittest
from unittest.mock import patch

import touch10_ram as ram


class RamIdentityTests(unittest.TestCase):
    def response(self, marker, kernel):
        guard = {'state': 'feeding', 'backend': 'linux-watchdog',
                 'timeout_seconds': 120, 'nowayout': True}
        stdout = '\n'.join((marker, kernel,
                            '9bdb2819-ed49-4719-8a90-bc13f672bd83',
                            json.dumps(guard))) + '\n'
        return subprocess.CompletedProcess([], 0, stdout, '')

    def test_new_profile_without_static_table_entry(self):
        kernel = '6.18.48-perrier-ram106'
        with patch.object(ram, 'remote', return_value=self.response(
                'perrier-interactive-ram106', kernel)):
            self.assertEqual(ram.ram_state(kernel)['kernel'], kernel)

    def test_mismatched_kernel_rejected(self):
        with patch.object(ram, 'remote', return_value=self.response(
                'perrier-interactive-ram106', '6.18.48-perrier-ram105')):
            with self.assertRaisesRegex(RuntimeError, 'identity'):
                ram.ram_state('6.18.48-perrier-ram106')

    def test_unexpected_marker_rejected(self):
        with patch.object(ram, 'remote', return_value=self.response(
                'stock-ram106', '6.18.48-perrier-ram106')):
            with self.assertRaisesRegex(RuntimeError, 'identity'):
                ram.ram_state('6.18.48-perrier-ram106')


if __name__ == '__main__':
    unittest.main()
