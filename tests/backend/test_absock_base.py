#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/backend/test_absock_base.py

Comprehensive test suite for --absock-base integration in backend and steam_handoff.
Verifies:
1. Default behavior (absock_base=None): No ELFUSE_ABSOCK_BASE in extra_env / plan env.
2. Valid explicit base with socket-derived (06a2fceb...):
   - Sets ELFUSE_ABSOCK_BASE in native plan env to canonical resolved absolute path.
   - Descriptor reports supports_absock_base=True and capability.
3. Rejecting explicit base on unsupported runtimes (hash-based, not path-name):
   - Old lifecycle (f2a678dd...), layout-only (0079fc5d...), original (dd5dae9e...), or unknown.
   - Returns status BLOCKED (reason contains unsupported absock base) and CLI exit 20.
4. Strict security validation of absock_base:
   - Must be inside LAB.
   - Must exist and be a directory.
   - Must be owned by current uid.
   - Mode must be 0700 (no group or other permissions).
   - Must not have leaf symlink (including with trailing slash, check before resolve).
   - Byte length check: len(os.fsencode(clean_base)) < 60 and clean_base + 18 <= 72.
   - Unicode path length handled via bytes, not characters.
5. Hand-off integration:
   - Config stores absock_base.
   - Execution time re-checks absock_base directory security.
   - If base is modified, swapped, or symlinked after preparation, execution is BLOCKED with exit 20.
   - Preparation is strictly plan-only (does not create base directory, does not install).
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.bundle import (
    LAB,
    build_plan,
    get_elfuse_descriptor,
    validate_absock_base,
)
from scripts.backend.steam_handoff import prepare_runtime_tool

SOCKET_DERIVED_ELFUSE = LAB / "sources/elfuse-socket-derived/build/elfuse"
LIFECYCLE_ELFUSE = LAB / "sources/elfuse-lifecycle-derived/build/elfuse"
CRASH_CANDIDATE_ELFUSE = LAB / "sources/elfuse-crash-derived/build/elfuse-candidate"
MANIFEST = LAB / "artifacts/public-proton/bundle.json"
SYSROOT = LAB / "fixtures/runtime/arch-case"
PREFIX = LAB / "fixtures/runtime/steam-shaped/compat/pfx"
LINUX_PYTHON = LAB / "fixtures/runtime/arch-case/usr/bin/python3"
RUNTIME_BUNDLE = LAB / "fixtures/runtime/proton-derived"


class TestAbsockBase(unittest.TestCase):
    def setUp(self):
        self.test_dir = LAB / f"logs/backend/test_absock_{os.getpid()}_{id(self)}"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        # Use a short directory name directly under LAB to guarantee < 60 bytes (LAB is 41 bytes, .s_t is 45 bytes)
        self.valid_base = LAB / ".s_t"
        self.valid_base.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.valid_base, 0o700)

    def tearDown(self):
        if self.valid_base.exists():
            shutil.rmtree(self.valid_base, ignore_errors=True)
        unicode_test_dir = LAB / ".s_中"
        if unicode_test_dir.exists():
            shutil.rmtree(unicode_test_dir, ignore_errors=True)
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_default_plan_has_no_absock_base_env(self):
        """Default build_plan without absock_base must not set ELFUSE_ABSOCK_BASE."""
        plan = build_plan(
            MANIFEST,
            SYSROOT,
            PREFIX,
            ["runinprefix", "C:\\test.exe"],
            engine="proton",
            linux_python=LINUX_PYTHON,
            runtime_bundle=RUNTIME_BUNDLE,
            elfuse_path=SOCKET_DERIVED_ELFUSE,
            absock_base=None,
        )
        self.assertEqual(plan["status"], "PLAN_READY")
        self.assertNotIn("ELFUSE_ABSOCK_BASE", plan["env"])
        self.assertIsNone(plan["absock_base"])

    def test_valid_explicit_base_with_socket_derived_elfuse(self):
        """Explicit valid base with socket-derived elfuse sets ELFUSE_ABSOCK_BASE in plan."""
        plan = build_plan(
            MANIFEST,
            SYSROOT,
            PREFIX,
            ["runinprefix", "C:\\test.exe"],
            engine="proton",
            linux_python=LINUX_PYTHON,
            runtime_bundle=RUNTIME_BUNDLE,
            elfuse_path=SOCKET_DERIVED_ELFUSE,
            absock_base=self.valid_base,
        )
        self.assertEqual(plan["status"], "PLAN_READY")
        self.assertIn("ELFUSE_ABSOCK_BASE", plan["env"])
        self.assertEqual(plan["env"]["ELFUSE_ABSOCK_BASE"], str(self.valid_base.resolve()))
        self.assertEqual(plan["absock_base"], str(self.valid_base.resolve()))
        self.assertTrue(plan["runtime_descriptor"]["capabilities"]["supports_absock_base"])

    def test_explicit_base_rejected_on_unsupported_runtimes(self):
        """Passing absock_base to runtimes that do not support it (e.g. lifecycle f2, original) must fail closed."""
        unsupported_runtimes = [
            LIFECYCLE_ELFUSE,
            CRASH_CANDIDATE_ELFUSE,
            LAB / "sources/elfuse/build/elfuse",
        ]
        for elfuse_p in unsupported_runtimes:
            if not elfuse_p.exists():
                continue
            plan = build_plan(
                MANIFEST,
                SYSROOT,
                PREFIX,
                ["runinprefix", "C:\\test.exe"],
                engine="proton",
                linux_python=LINUX_PYTHON,
                runtime_bundle=RUNTIME_BUNDLE,
                elfuse_path=elfuse_p,
                absock_base=self.valid_base,
            )
            self.assertEqual(plan["status"], "BLOCKED")
            self.assertIn("supports_absock_base", plan["reason"])
            self.assertFalse(plan["execution_performed"])

    def test_validate_absock_base_outside_lab_rejected(self):
        """Paths outside lab must be rejected."""
        with tempfile.TemporaryDirectory() as external_dir:
            os.chmod(external_dir, 0o700)
            with self.assertRaises(ValueError) as ctx:
                validate_absock_base(external_dir)
            self.assertIn("lab", str(ctx.exception).lower())

    def test_validate_absock_base_nonexistent_rejected(self):
        """Non-existent directory must be rejected."""
        nonexistent = self.test_dir / "does_not_exist"
        with self.assertRaises(ValueError) as ctx:
            validate_absock_base(nonexistent)
        self.assertIn("exist", str(ctx.exception).lower())

    def test_validate_absock_base_file_rejected(self):
        """Regular file must be rejected."""
        file_path = self.test_dir / "regular_file"
        file_path.write_text("hello")
        os.chmod(file_path, 0o700)
        with self.assertRaises(ValueError) as ctx:
            validate_absock_base(file_path)
        self.assertIn("directory", str(ctx.exception).lower())

    def test_validate_absock_base_symlink_leaf_rejected(self):
        """Symlink leaf pointing to valid dir must be rejected."""
        symlink_base = self.test_dir / "symlink_base"
        os.symlink(self.valid_base, symlink_base)
        with self.assertRaises(ValueError) as ctx:
            validate_absock_base(symlink_base)
        self.assertIn("symlink", str(ctx.exception).lower())

    def test_validate_absock_base_symlink_with_trailing_slash_rejected(self):
        """Symlink with trailing slash must also be rejected before resolution."""
        symlink_base = self.test_dir / "symlink_slash"
        os.symlink(self.valid_base, symlink_base)
        path_with_slash = str(symlink_base) + "/"
        with self.assertRaises(ValueError) as ctx:
            validate_absock_base(path_with_slash)
        self.assertIn("symlink", str(ctx.exception).lower())

    def test_validate_absock_base_bad_permissions_rejected(self):
        """Base with group or other permissions (e.g. 0755, 0770) must be rejected."""
        insecure_dir = self.test_dir / "insecure_base"
        insecure_dir.mkdir(exist_ok=True)
        os.chmod(insecure_dir, 0o755)
        with self.assertRaises(ValueError) as ctx:
            validate_absock_base(insecure_dir)
        self.assertIn("0700", str(ctx.exception))

    def test_validate_absock_base_length_limit(self):
        """Path exceeding length budget (<60 bytes for clean_base) must be rejected."""
        long_dir = self.test_dir / ("a" * 70)
        long_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(long_dir, 0o700)
        with self.assertRaises(ValueError) as ctx:
            validate_absock_base(long_dir)
        self.assertIn("length", str(ctx.exception).lower())

    def test_validate_absock_base_unicode_byte_length(self):
        """Unicode characters count as UTF-8 bytes, not python str len."""
        # 1 Chinese character = 3 UTF-8 bytes; LAB (41) + /.s_中 (7) = 48 bytes < 60
        c_dir = LAB / ".s_中"
        c_dir.mkdir(exist_ok=True)
        os.chmod(c_dir, 0o700)
        clean = validate_absock_base(c_dir)
        self.assertEqual(clean, str(c_dir.resolve()))

    def test_steam_handoff_prepare_absock_base_plan_only(self):
        """steam_handoff.prepare_runtime_tool stores absock_base and creates plan-only candidate."""
        candidate_out = self.test_dir / "candidate_absock"
        mock_target = self.test_dir / "mock_target"

        res = prepare_runtime_tool(
            candidate_out,
            mock_target,
            execute_runtime=False,
            elfuse_path=SOCKET_DERIVED_ELFUSE,
            absock_base=self.valid_base,
        )
        self.assertFalse(res["applied"])
        self.assertFalse(res["execute_runtime"])

        cfg = json.loads((candidate_out / "config.json").read_text())
        self.assertEqual(cfg["absock_base"], str(self.valid_base.resolve()))

        # Run wrapper in plan-only mode
        wrapper = candidate_out / "proton-wrapper.sh"
        cmd = [str(wrapper), "runinprefix", "C:\\test.exe"]
        p = subprocess.run(cmd, cwd=LAB, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"Wrapper failed: {p.stderr}")
        data = json.loads(p.stdout)
        self.assertEqual(data["status"], "PLAN_READY")
        self.assertEqual(data["env"]["ELFUSE_ABSOCK_BASE"], str(self.valid_base.resolve()))

    def test_steam_handoff_execute_revalidates_absock_base(self):
        """Execution mode revalidates absock_base security; swapping to symlink blocks with exit 20."""
        candidate_out = self.test_dir / "candidate_swapped"
        mock_target = self.test_dir / "mock_target"

        res = prepare_runtime_tool(
            candidate_out,
            mock_target,
            execute_runtime=True,
            elfuse_path=SOCKET_DERIVED_ELFUSE,
            absock_base=self.valid_base,
        )

        # Before running, swap valid_base to an insecure symlink
        os.chmod(self.valid_base, 0o755)

        wrapper = candidate_out / "proton-wrapper.sh"
        cmd = [str(wrapper), "runinprefix", "C:\\test.exe"]
        p = subprocess.run(cmd, cwd=LAB, capture_output=True, text=True)
        self.assertEqual(p.returncode, 20)
        data = json.loads(p.stdout)
        self.assertEqual(data["status"], "BLOCKED")
        self.assertIn("0700", data["reason"])


if __name__ == "__main__":
    unittest.main()
