#!/usr/bin/env python3
"""
TDD tests for safe_process runner in scripts/runtime/
Verifies argv execution, environment isolation, timeout handling without PID reuse race.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
LAB_ROOT = Path(__file__).resolve().parents[2]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.runtime.safe_process import run_safe_isolated


class TestSafeProcess(unittest.TestCase):
    def setUp(self):
        self.log_dir = LAB_ROOT / "logs" / "runtime-worker" / "test-logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def test_normal_exit(self):
        res = run_safe_isolated(
            [sys.executable, "-c", "import sys; print('SAFE_RUN_OK'); sys.exit(0)"],
            log_root=self.log_dir,
            timeout=5
        )
        self.assertEqual(res["exit"], 0)
        self.assertFalse(res["timed_out"])
        stdout_text = Path(res["stdout"]).read_text()
        self.assertIn("SAFE_RUN_OK", stdout_text)

    def test_nonzero_exit(self):
        res = run_safe_isolated(
            [sys.executable, "-c", "import sys; sys.exit(42)"],
            log_root=self.log_dir,
            timeout=5
        )
        self.assertEqual(res["exit"], 42)
        self.assertFalse(res["timed_out"])

    def test_timeout_handling(self):
        res = run_safe_isolated(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            log_root=self.log_dir,
            timeout=1
        )
        self.assertTrue(res["timed_out"])
        self.assertNotEqual(res["exit"], 0)

    def test_environment_isolation(self):
        res = run_safe_isolated(
            [sys.executable, "-c", "import os; print(os.environ.get('HOME')); print(os.environ.get('TMPDIR'))"],
            log_root=self.log_dir,
            timeout=5
        )
        self.assertEqual(res["exit"], 0)
        lines = Path(res["stdout"]).read_text().splitlines()
        home = lines[0]
        tmp = lines[1]
        self.assertTrue(home.startswith(str(self.log_dir)))
        self.assertTrue(tmp.startswith(str(self.log_dir)))


if __name__ == "__main__":
    unittest.main()
