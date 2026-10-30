import json
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

LAB = Path(__file__).resolve().parents[2]
HARNESS = LAB / 'scripts/runtime/session_v2_round2/guest_fault_harness.py'

class GuestFaultTests(unittest.TestCase):
    def test_fake_timeout_scenario(self):
        run_id = 'test-fault-to-' + uuid.uuid4().hex[:8]
        cmd = [sys.executable, '-I', str(HARNESS), '--mode', 'timeout', '--role', 'fake', '--run-id', run_id]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        self.assertEqual(p.returncode, 0, f"Harness failed:\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
        summary = json.loads(p.stdout)
        self.assertEqual(summary['runner_exit'], 124)
        self.assertIsNone(summary['target_exit'])
        self.assertTrue(summary['inner_timed_out'])
        self.assertFalse(summary['outer_timed_out'])
        self.assertTrue(summary['cleanup_complete'])
        self.assertTrue(summary['sentinel_alive'])
        self.assertTrue(summary['sentinel_reaped'])
        self.assertEqual(len(summary['known_before_fault']), 4)
        self.assertEqual(len(summary['leaked_processes']), 0)

    def test_fake_crash_scenario(self):
        run_id = 'test-fault-cr-' + uuid.uuid4().hex[:8]
        cmd = [sys.executable, '-I', str(HARNESS), '--mode', 'crash', '--role', 'fake', '--run-id', run_id]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        self.assertEqual(p.returncode, 0, f"Harness failed:\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
        summary = json.loads(p.stdout)
        self.assertEqual(summary['runner_exit'], 70)
        self.assertTrue(summary['cleanup_complete'])
        self.assertTrue(summary['sentinel_alive'])
        self.assertTrue(summary['sentinel_reaped'])
        self.assertEqual(len(summary['known_before_fault']), 4)
        self.assertEqual(len(summary['leaked_processes']), 0)
        self.assertEqual(summary['fault_record']['signal_sent']['signal'], 'SIGKILL')
        self.assertEqual(summary['fault_record']['signal_sent']['result'], 'sent')

    def test_fault_controller_exception_still_allows_p0_cleanup_and_sentinel_reap(self):
        # Verify that if controller throws before injecting fault, P0 parent is NOT terminated early
        # and cleanly reaps via outer watchdog, sentinel is preserved and reaped, status marked UNKNOWN
        import importlib.util
        spec = importlib.util.spec_from_file_location('fault_harness', HARNESS)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        run_id = 'test-fault-exc-' + uuid.uuid4().hex[:8]
        summary = m.run_fault_scenario('timeout', 'fake', run_id, inject_fault_failure=True)
        self.assertEqual(summary['status'], 'UNKNOWN')
        self.assertIn('injected fault controller failure', summary['error'])
        self.assertTrue(summary['cleanup_complete'])
        self.assertTrue(summary['sentinel_alive'])
        self.assertTrue(summary['sentinel_reaped'])
        self.assertTrue(summary['inner_timed_out'] or summary['outer_timed_out'])
        self.assertEqual(len(summary['leaked_processes']), 0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
