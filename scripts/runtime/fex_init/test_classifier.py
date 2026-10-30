#!/usr/bin/env python3
"""
Unit tests for FEX marker and diagnostic classification logic.
Tests positive and negative cases for libarm64ecfex loading.
"""

import re
import unittest


def classify_fex_module_marker(lines) -> bool:
    has_loaded = False
    has_failed = False
    for l in lines:
        if "could not load" in l and "libarm64ecfex.dll" in l:
            has_failed = True
        elif re.search(r"Loaded\s+.*libarm64ecfex\.dll.*builtin", l, re.IGNORECASE):
            has_loaded = True
    if has_failed:
        return False
    return has_loaded


class TestFexClassifier(unittest.TestCase):
    def test_positive_load_builtin(self):
        sample_lines = [
            '0024:trace:loaddll:build_module Loaded L"C:\\minimal-x64.exe" at 0000000140000000: native',
            '0024:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\ntdll.dll" at 000000DFFFE30000: builtin',
            '0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin',
            '0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\kernelbase.dll" at 000000DFFF960000: builtin',
        ]
        self.assertTrue(classify_fex_module_marker(sample_lines))

    def test_negative_could_not_load_status_c0000135(self):
        # Lead's negative case from run-kb_ei513
        sample_lines = [
            '0024:trace:loaddll:build_module Loaded L"C:\\minimal-x64.exe" at 0000000140000000: native',
            '0024:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\ntdll.dll" at 000000DFFFE30000: builtin',
            '0024:err:module:load_arm64ec_module could not load L"C:\\windows\\system32\\libarm64ecfex.dll", status c0000135',
            '0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code -1073741515, process_exiting 0.',
        ]
        self.assertFalse(classify_fex_module_marker(sample_lines))

    def test_negative_only_search_string(self):
        sample_lines = [
            '0034:trace:process:find_exe_file looking for L"C:\\windows\\system32\\libarm64ecfex.dll"',
        ]
        self.assertFalse(classify_fex_module_marker(sample_lines))

    def test_negative_empty_lines(self):
        self.assertFalse(classify_fex_module_marker([]))


if __name__ == "__main__":
    unittest.main()
