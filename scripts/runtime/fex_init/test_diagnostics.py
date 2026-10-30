#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for FEX runtime diagnostic classifier (scripts/runtime/fex_init/diagnostics.py).
Ensures:
- Strict true positive: only 'Loaded ... libarm64ecfex.dll ... builtin' counts as loaded
- Strict true negative: 'could not load ... libarm64ecfex.dll' is classified as failure
- Search strings or looking_for do not trigger false positive
- error_observed is UNKNOWN when neither error nor success marker is present
- target_entry vs whole_success separation
- hello-x64.exe stdout with target_exit -11 classified as PARTIAL_OUTPUT_THEN_CRASH, whole_success=False
- NtTerminateProcess exit_code 0 trace does not count as whole_success when process crashed
- Timeout (exit 124) and cleanup_errors prevent whole_success (no false greens)
- Pure function execution with zero Wine subprocess calls
"""

import sys
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parents[3]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.runtime.fex_init.diagnostics import (
    classify_fex_module_marker,
    classify_error_observed,
    classify_target_entry,
    classify_run_outcome,
)


class TestFexDiagnostics(unittest.TestCase):
    # 1. Module marker tests
    def test_positive_load_builtin(self):
        sample_lines = [
            '0024:trace:loaddll:build_module Loaded L"C:\\minimal-x64.exe" at 0000000140000000: native',
            '0024:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\ntdll.dll" at 000000DFFFE30000: builtin',
            '0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin',
            '0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\kernelbase.dll" at 000000DFFF960000: builtin',
        ]
        res = classify_fex_module_marker(sample_lines)
        self.assertTrue(res["loaded"])
        self.assertFalse(res["failure"])

    def test_negative_could_not_load_status_c0000135(self):
        # Lead's negative case from run-kb_ei513 line 199
        sample_lines = [
            '0024:trace:loaddll:build_module Loaded L"C:\\minimal-x64.exe" at 0000000140000000: native',
            '0024:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\ntdll.dll" at 000000DFFFE30000: builtin',
            '0024:err:module:load_arm64ec_module could not load L"C:\\windows\\system32\\libarm64ecfex.dll", status c0000135',
            '0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code -1073741515, process_exiting 0.',
        ]
        res = classify_fex_module_marker(sample_lines)
        self.assertFalse(res["loaded"])
        self.assertTrue(res["failure"])
        self.assertEqual(res["failure_reason"], "c0000135")

    def test_negative_only_search_string(self):
        sample_lines = [
            '0034:trace:process:find_exe_file looking for L"C:\\windows\\system32\\libarm64ecfex.dll"',
        ]
        res = classify_fex_module_marker(sample_lines)
        self.assertFalse(res["loaded"])
        self.assertFalse(res["failure"])

    def test_negative_empty_lines(self):
        res = classify_fex_module_marker([])
        self.assertFalse(res["loaded"])
        self.assertFalse(res["failure"])

    # 2. Error observed tests
    def test_error_observed_explicit_mapping_error(self):
        sample_lines = [
            "0024:err:virtual:try_map_free_area mmap() error Address already in use, range 0xfeffff0000-0xffffff0000",
        ]
        self.assertTrue(classify_error_observed(sample_lines, fex_loaded=False))

    def test_error_observed_false_when_fex_loaded(self):
        sample_lines = [
            '0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin',
        ]
        self.assertFalse(classify_error_observed(sample_lines, fex_loaded=True))

    def test_error_observed_unknown_when_neither(self):
        # When neither error nor FEX loaded marker is seen, MUST report UNKNOWN
        sample_lines = [
            "0024:trace:loaddll:build_ntdll_module Loaded L\"C:\\windows\\system32\\ntdll.dll\": builtin",
        ]
        self.assertEqual(classify_error_observed(sample_lines, fex_loaded=False), "UNKNOWN")

    # 3. Target entry tests
    def test_target_entry_minimal_arm64(self):
        self.assertTrue(classify_target_entry("minimal-arm64.exe", target_exit=37, stdout_text=""))
        self.assertFalse(classify_target_entry("minimal-arm64.exe", target_exit=0, stdout_text=""))
        self.assertFalse(classify_target_entry("minimal-arm64.exe", target_exit=-11, stdout_text=""))

    def test_target_entry_minimal_x64(self):
        self.assertTrue(classify_target_entry("minimal-x64.exe", target_exit=43, stdout_text=""))
        self.assertFalse(classify_target_entry("minimal-x64.exe", target_exit=0, stdout_text=""))
        self.assertFalse(classify_target_entry("minimal-x64.exe", target_exit=-11, stdout_text=""))

    def test_target_entry_hello_x64(self):
        self.assertTrue(classify_target_entry("hello-x64.exe", target_exit=0, stdout_text="X64_FEX_OK\n"))
        self.assertTrue(classify_target_entry("hello-x64.exe", target_exit=-11, stdout_text="X64_FEX_OK\n"))
        self.assertFalse(classify_target_entry("hello-x64.exe", target_exit=0, stdout_text="Some other text\n"))

    # 4. Partial output then crash test
    def test_partial_output_then_crash_with_fake_ntterminate_zero(self):
        """
        Lead's finding: hello stdout was produced ('X64_FEX_OK'), but target crashed with -11.
        Even if stderr contains NtTerminateProcess exit_code 0 trace, it MUST be classified as:
        partial_output_then_crash=True, whole_success=False!
        """
        stderr_sample = (
            '0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin\n'
            '0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 0, process_exiting 0.\n'
        )
        res_dict = {
            "exit": -11,
            "target_exit": -11,
            "supervisor_exit": -9,
            "timed_out": False,
            "cleanup_errors": [],
            "seconds": 2.5,
            "run_dir": "/mock/run",
        }
        outcome = classify_run_outcome("hello-x64.exe", res_dict, stdout_text="X64_FEX_OK\n", stderr_text=stderr_sample)

        self.assertTrue(outcome["target_entry"])
        self.assertTrue(outcome["partial_output_then_crash"])
        self.assertFalse(outcome["whole_success"])
        self.assertEqual(outcome["status"], "PARTIAL_OUTPUT_THEN_CRASH")
        self.assertFalse(outcome["fex_module_load_failure"])
        self.assertTrue(outcome["fex_module_marker"])

    # 5. Whole success tests
    def test_whole_success_clean_hello_x64(self):
        stderr_sample = (
            '0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin\n'
        )
        res_dict = {
            "exit": 0,
            "target_exit": 0,
            "supervisor_exit": 0,
            "timed_out": False,
            "cleanup_errors": [],
            "seconds": 1.2,
            "run_dir": "/mock/run",
        }
        outcome = classify_run_outcome("hello-x64.exe", res_dict, stdout_text="X64_FEX_OK\n", stderr_text=stderr_sample)
        self.assertTrue(outcome["target_entry"])
        self.assertFalse(outcome["partial_output_then_crash"])
        self.assertTrue(outcome["whole_success"])
        self.assertEqual(outcome["status"], "WHOLE_SUCCESS")

    def test_whole_success_false_on_timeout(self):
        res_dict = {
            "exit": 124,
            "target_exit": None,
            "supervisor_exit": -9,
            "timed_out": True,
            "cleanup_errors": [],
            "seconds": 50.0,
            "run_dir": "/mock/run",
        }
        outcome = classify_run_outcome("hello-x64.exe", res_dict, stdout_text="", stderr_text="")
        self.assertFalse(outcome["whole_success"])
        self.assertTrue(outcome["timeout"])
        self.assertEqual(outcome["status"], "TIMEOUT")

    def test_whole_success_false_on_cleanup_error(self):
        # Target reached 0, but cleanup failed (e.g. PermissionError)
        # MUST NOT be declared whole_success
        stderr_sample = (
            '0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin\n'
        )
        res_dict = {
            "exit": 125,
            "target_exit": 0,
            "supervisor_exit": 0,
            "timed_out": False,
            "cleanup_errors": ["[Errno 1] Operation not permitted"],
            "seconds": 1.5,
            "run_dir": "/mock/run",
        }
        outcome = classify_run_outcome("hello-x64.exe", res_dict, stdout_text="X64_FEX_OK\n", stderr_text=stderr_sample)
        self.assertFalse(outcome["whole_success"])
        self.assertEqual(outcome["status"], "CLEANUP_FAILED")

    def test_minimal_x64_false_green_on_timeout_with_exit_43(self):
        """Regression test for Lead review: res target_exit=43 but exit=124/timed_out=True
        MUST NOT have whole_success=True!"""
        res_dict = {
            "exit": 124,
            "target_exit": 43,
            "supervisor_exit": -9,
            "timed_out": True,
            "cleanup_errors": [],
            "seconds": 50.0,
            "run_dir": "/mock/run",
        }
        outcome = classify_run_outcome("minimal-x64.exe", res_dict, stdout_text="", stderr_text="")
        self.assertTrue(outcome["target_entry"])
        self.assertFalse(outcome["whole_success"], "Minimal x64 with timeout must not be whole_success!")
        self.assertEqual(outcome["status"], "TIMEOUT")

    def test_minimal_x64_false_green_on_cleanup_error_with_exit_43(self):
        """Regression test for Lead review: res target_exit=43 but cleanup_errors non-empty
        MUST NOT have whole_success=True!"""
        res_dict = {
            "exit": 125,
            "target_exit": 43,
            "supervisor_exit": 0,
            "timed_out": False,
            "cleanup_errors": ["[Errno 1] Operation not permitted"],
            "seconds": 2.0,
            "run_dir": "/mock/run",
        }
        outcome = classify_run_outcome("minimal-x64.exe", res_dict, stdout_text="", stderr_text="")
        self.assertTrue(outcome["target_entry"])
        self.assertFalse(outcome["whole_success"], "Minimal x64 with cleanup_errors must not be whole_success!")
        self.assertEqual(outcome["status"], "CLEANUP_FAILED")

    def test_minimal_arm64_false_green_on_timeout_with_exit_37(self):
        """Regression test for Lead review: res target_exit=37 but timed out
        MUST NOT have whole_success=True!"""
        res_dict = {
            "exit": 124,
            "target_exit": 37,
            "supervisor_exit": -9,
            "timed_out": True,
            "cleanup_errors": [],
            "seconds": 50.0,
            "run_dir": "/mock/run",
        }
        outcome = classify_run_outcome("minimal-arm64.exe", res_dict, stdout_text="", stderr_text="")
        self.assertTrue(outcome["target_entry"])
        self.assertFalse(outcome["whole_success"], "Minimal arm64 with timeout must not be whole_success!")
        self.assertEqual(outcome["status"], "TIMEOUT")

    def test_minimal_x64_false_green_on_mismatched_overall_exit(self):
        """Lead review: res target_exit=43 but overall exit=1 (mismatch) must not be whole_success."""
        res_dict = {
            "exit": 1,
            "target_exit": 43,
            "supervisor_exit": 0,
            "timed_out": False,
            "cleanup_errors": [],
            "seconds": 2.0,
            "run_dir": "/mock/run",
        }
        outcome = classify_run_outcome("minimal-x64.exe", res_dict, stdout_text="", stderr_text="")
        self.assertTrue(outcome["target_entry"])
        self.assertFalse(outcome["whole_success"], "Minimal x64 with mismatched overall exit must not be whole_success!")

    def test_minimal_arm64_false_green_on_mismatched_overall_exit(self):
        """Lead review: res target_exit=37 but overall exit=1 (mismatch) must not be whole_success."""
        res_dict = {
            "exit": 1,
            "target_exit": 37,
            "supervisor_exit": 0,
            "timed_out": False,
            "cleanup_errors": [],
            "seconds": 2.0,
            "run_dir": "/mock/run",
        }
        outcome = classify_run_outcome("minimal-arm64.exe", res_dict, stdout_text="", stderr_text="")
        self.assertTrue(outcome["target_entry"])
        self.assertFalse(outcome["whole_success"], "Minimal arm64 with mismatched overall exit must not be whole_success!")

    def test_negative_not_loaded_prefix_pattern(self):
        """Regression test for Lead review: line containing 'not Loaded' must not be a false positive."""
        sample_lines = [
            '0024:trace:loaddll:build_module not Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin',
            '0024:warn:loaddll:skip Loaded not libarm64ecfex.dll builtin',
        ]
        res = classify_fex_module_marker(sample_lines)
        self.assertFalse(res["loaded"], "'not Loaded ...' line must not trigger loaded true positive")


if __name__ == "__main__":
    unittest.main()
