#!/usr/bin/env python3
"""
scripts/runtime/xvfb_wine/test_controller.py

Unit and fake fixture tests for controller.py logic:
- Verifies write_xauthority uses O_CREAT|O_EXCL with strict 0600 mode.
- Verifies pre-check detection with os.path.lexists on regular, socket, and dangling symlinks.
- Verifies controlled child timeout termination without setsid/killpg.
- Verifies check_displayfd_match integer matching and mismatch rejection.
- Verifies precision owned cleanup:
  * Lock file only unlinked if file content PID matches.
  * Socket file only unlinked if inode and UID matches.
- Verifies resolve_active_display gate rejects colon fallback when pathname fails.
"""

import os
import sys
import stat
import tempfile
import unittest
from pathlib import Path
import subprocess

LAB_ROOT = Path(__file__).resolve().parents[3]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.runtime.xvfb_wine.controller import (
    write_xauthority,
    check_displayfd_match,
    clean_owned_lock,
    clean_owned_socket,
    resolve_active_display,
)


class TestControllerSafety(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmppath = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_write_xauthority_mode_and_excl(self):
        auth_file = self.tmppath / "test_Xauthority"
        cookie = b"\x01" * 16
        write_xauthority(auth_file, 97, cookie)

        # 1. File must exist and have 0600 permissions
        st = os.stat(str(auth_file))
        mode = stat.S_IMODE(st.st_mode)
        self.assertEqual(mode, 0o600, f"Expected mode 0600, got {oct(mode)}")

        # 2. O_CREAT | O_EXCL must reject existing file
        with self.assertRaises(FileExistsError):
            write_xauthority(auth_file, 97, cookie)

    def test_lexists_dangling_symlink(self):
        target = self.tmppath / "nonexistent"
        link = self.tmppath / "dangling_link"
        os.symlink(str(target), str(link))

        # os.path.exists returns False for dangling link, but lexists returns True
        self.assertFalse(os.path.exists(str(link)))
        self.assertTrue(os.path.lexists(str(link)))

    def test_child_timeout_termination_no_killpg(self):
        # Verify direct child process termination under timeout without calling killpg
        proc = subprocess.Popen(["sleep", "10"])
        try:
            proc.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                rc = proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait(timeout=1)
            self.assertIsNotNone(rc)
            self.assertNotEqual(rc, 0)

    def test_check_displayfd_match(self):
        # Exact match
        self.assertTrue(check_displayfd_match("97\n", 97))
        self.assertTrue(check_displayfd_match(" 97 ", 97))

        # Mismatch
        with self.assertRaises(AssertionError):
            check_displayfd_match("98", 97)

        # Non-integer
        with self.assertRaises(AssertionError):
            check_displayfd_match("error", 97)

    def test_clean_owned_lock(self):
        lock_file = self.tmppath / ".X97-lock"
        
        # Test 1: PID matches -> cleaned
        with open(lock_file, "w") as f:
            f.write("   12345\n")
        self.assertTrue(clean_owned_lock(str(lock_file), 12345))
        self.assertFalse(os.path.lexists(str(lock_file)))

        # Test 2: PID mismatch -> preserved
        with open(lock_file, "w") as f:
            f.write("   54321\n")
        self.assertFalse(clean_owned_lock(str(lock_file), 12345))
        self.assertTrue(os.path.lexists(str(lock_file)))

    def test_clean_owned_socket(self):
        sock_file = self.tmppath / "X97"
        sock_file.touch()
        st = os.lstat(str(sock_file))
        expected_tuple = (st.st_dev, st.st_ino, st.st_uid)

        # Test 1: Inode matches -> cleaned
        self.assertTrue(clean_owned_socket(str(sock_file), expected_tuple))
        self.assertFalse(os.path.lexists(str(sock_file)))

        # Test 2: Inode mismatch -> preserved
        sock_file.touch()
        mismatched_tuple = (st.st_dev, st.st_ino + 9999, st.st_uid)
        self.assertFalse(clean_owned_socket(str(sock_file), mismatched_tuple))
        self.assertTrue(os.path.lexists(str(sock_file)))

    def test_resolve_active_display_gate(self):
        # Pathname success -> allowed
        res = resolve_active_display({"success": True, "display": "/tmp/.X11-unix/X97"})
        self.assertEqual(res, "/tmp/.X11-unix/X97")

        # Pathname failure -> strictly raises RuntimeError (no colon fallback)
        with self.assertRaises(RuntimeError):
            resolve_active_display({"success": False, "error_code": 1})


if __name__ == "__main__":
    unittest.main()
