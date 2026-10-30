#!/usr/bin/env python3
"""
scripts/runtime/proton_launcher/test_proton_launcher.py

Integration test suite for the unmodified Proton Python launcher under elfuse.
Verifies:
1. minimal-x64.exe execution through Proton launcher exits with 43.
2. hello-x64.exe execution through Proton launcher produces 'X64_FEX_OK' and exits with 0.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
RUNNER = LAB_ROOT / "scripts" / "runtime" / "proton_launcher" / "run_proton.py"


class TestProtonLauncher(unittest.TestCase):
    def test_plan_generation(self):
        plan_file = LAB_ROOT / "logs" / "proton-launcher" / "plan.json"
        self.assertTrue(plan_file.exists(), "plan.json should be generated")
        with open(plan_file, "r") as f:
            plan = json.load(f)
        self.assertEqual(plan.get("status"), "PLAN_READY")
        self.assertEqual(plan.get("engine"), "proton")
        self.assertIn("python3", plan["argv"][7])
        self.assertIn("proton", plan["argv"][8])

    def test_minimal_x64_exit_43(self):
        cmd = [
            sys.executable,
            str(RUNNER),
            "--target", "minimal-x64.exe",
            "--verb", "runinprefix",
            "--timeout", "70"
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 43, f"Expected exit code 43 for minimal-x64, got {proc.returncode}")

    def test_hello_x64_exit_0_and_stdout(self):
        cmd = [
            sys.executable,
            str(RUNNER),
            "--target", "hello-x64.exe",
            "--verb", "runinprefix",
            "--timeout", "70"
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, f"Expected exit code 0 for hello-x64, got {proc.returncode}. Output:\n{proc.stdout}")
        self.assertIn("X64_FEX_OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
