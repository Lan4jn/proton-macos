#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/backend/test_steam_plan_compat.py

TDD Test Suite for Reversible Compatibility Module Installation Plan (task-129).

Verifies Acceptance Criteria 1:
(a) Manifest Generation: plan containing compat module records target_rel_path, source_sha256, size, original backup sha256.
(b) Apply: only replaces within isolated fixture root, matches source SHA256.
(c) Verify: detects tampering or deletion.
(d) Rollback: restores target file byte-for-byte to original SHA256, zero write outside fixture root (snapshot checked).
(e) Security: rejects absolute paths, '..' traversal, symlink escapes.
(f) Precondition validation: missing target file or architecture mismatch explicitly fails (no silent skip).
"""

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.steam_plan import (
    SteamPlanError,
    apply_installation_plan,
    compute_tree_fingerprint,
    create_compat_module_plan,
    create_installation_plan,
    rollback_installation_manifest,
    sha256_file,
    validate_path_enclosure,
    verify_installation_manifest,
)


class TestSteamPlanCompat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Host paths snapshot to verify zero external write
        cls.host_probe_paths = [
            Path("/tmp"),
            Path("/Applications"),
            Path(os.path.expanduser("~/Library/Application Support"))
        ]
        cls.host_snapshots = {}
        for p in cls.host_probe_paths:
            if p.exists():
                cls.host_snapshots[p] = set(os.listdir(p))

    def setUp(self):
        # Create an isolated fixture Steam root in lab scratch directory
        self.scratch_dir = Path(tempfile.mkdtemp(prefix="test_steam_compat_", dir=str(LAB / "logs")))
        self.fixture_steam_root = self.scratch_dir / "SteamRoot"
        self.fixture_steam_root.mkdir(parents=True, exist_ok=True)

        # Create a mock Proton tool tree inside the fixture root
        self.proton_rel_path = Path("compatibilitytools.d/proton_arm64/files/lib/wine/aarch64-unix/win32u.so")
        self.target_win32u = self.fixture_steam_root / self.proton_rel_path
        self.target_win32u.parent.mkdir(parents=True, exist_ok=True)

        # Original unpatched win32u.so content (mocking original SHA256 4f6013fa...)
        # We write minimal valid ELF header with EM_AARCH64 (183 = 0xb7)
        self.orig_elf_content = (
            b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 +  # e_ident (64-bit LSB)
            b"\x03\x00" +                                  # e_type: ET_DYN (3)
            b"\xb7\x00" +                                  # e_machine: EM_AARCH64 (183)
            b"\x01\x00\x00\x00" +                        # e_version: 1
            b"MOCK_ORIGINAL_WIN32U_CONTENT_4F6013FA" * 10
        )
        self.target_win32u.write_bytes(self.orig_elf_content)
        self.orig_sha256 = sha256_file(self.target_win32u)

        # Source patched win32u.so (mocking patched SHA256 59a76b05...)
        self.source_dir = self.scratch_dir / "compat_sources"
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.patched_win32u = self.source_dir / "win32u_patched.so"
        self.patched_elf_content = (
            b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 +
            b"\x03\x00" +
            b"\xb7\x00" +
            b"\x01\x00\x00\x00" +
            b"MOCK_PATCHED_GUARD_V3_WIN32U_59A76B05" * 12
        )
        self.patched_win32u.write_bytes(self.patched_elf_content)
        self.patched_sha256 = sha256_file(self.patched_win32u)

    def tearDown(self):
        # Remove scratch dir
        shutil.rmtree(self.scratch_dir, ignore_errors=True)

        # Verify host paths were not modified
        for p, orig_files in self.host_snapshots.items():
            if p.exists():
                cur_files = set(os.listdir(p))
                self.assertEqual(orig_files, cur_files, f"Host path '{p}' was modified during test!")

    def test_a_create_compat_plan_structure(self):
        """(a) Plan contains compat module entry with relative path, source SHA, size, and original backup."""
        plan = create_compat_module_plan(
            fixture_steam_root=self.fixture_steam_root,
            target_rel_path=str(self.proton_rel_path),
            source_module_path=self.patched_win32u,
            expected_orig_sha256=self.orig_sha256,
            expected_arch="aarch64"
        )

        self.assertEqual(plan["format_version"], "1.0.0")
        self.assertEqual(plan["plan_type"], "compat_module_replacement")
        self.assertEqual(plan["fixture_steam_root"], str(self.fixture_steam_root))
        
        # Verify steps
        self.assertEqual(len(plan["steps"]), 1)
        step = plan["steps"][0]
        self.assertEqual(step["type"], "replace_compat_module")
        self.assertEqual(step["relative_path"], str(self.proton_rel_path))
        self.assertEqual(step["source"], str(self.patched_win32u))
        self.assertEqual(step["destination"], str(self.target_win32u))
        self.assertEqual(step["source_sha256"], self.patched_sha256)
        self.assertEqual(step["expected_orig_sha256"], self.orig_sha256)
        self.assertEqual(step["expected_arch"], "aarch64")

    def test_b_apply_compat_plan_replaces_and_matches_sha(self):
        """(b) apply replaces strictly inside fixture root, matches source SHA256, produces backup."""
        plan = create_compat_module_plan(
            fixture_steam_root=self.fixture_steam_root,
            target_rel_path=str(self.proton_rel_path),
            source_module_path=self.patched_win32u,
            expected_orig_sha256=self.orig_sha256,
            expected_arch="aarch64"
        )

        backup_dir = self.fixture_steam_root / ".compat_backups"
        manifest = apply_installation_plan(plan, self.fixture_steam_root, backup_dir=backup_dir)

        # 1. Target win32u was replaced with patched content
        self.assertEqual(sha256_file(self.target_win32u), self.patched_sha256)

        # 2. Manifest records compat module details
        self.assertIn("compat_modules", manifest)
        self.assertEqual(len(manifest["compat_modules"]), 1)
        entry = manifest["compat_modules"][0]
        self.assertEqual(entry["target_rel_path"], str(self.proton_rel_path))
        self.assertEqual(entry["source_sha256"], self.patched_sha256)
        self.assertEqual(entry["original_sha256"], self.orig_sha256)

        # 3. Backup exists and holds original SHA256
        backup_path = Path(entry["backup_path"])
        self.assertTrue(backup_path.exists())
        self.assertEqual(sha256_file(backup_path), self.orig_sha256)

    def test_c_verify_detects_tampering_or_missing(self):
        """(c) verify detects corrupted file or deleted target."""
        plan = create_compat_module_plan(
            fixture_steam_root=self.fixture_steam_root,
            target_rel_path=str(self.proton_rel_path),
            source_module_path=self.patched_win32u,
            expected_orig_sha256=self.orig_sha256,
            expected_arch="aarch64"
        )
        backup_dir = self.fixture_steam_root / ".compat_backups"
        manifest = apply_installation_plan(plan, self.fixture_steam_root, backup_dir=backup_dir)

        # Valid initial state
        valid, errors = verify_installation_manifest(manifest, self.fixture_steam_root)
        self.assertTrue(valid)
        self.assertEqual(len(errors), 0)

        # 1. Tamper target file
        self.target_win32u.write_bytes(b"CORRUPTED_TAMPERED_DATA")
        valid, errors = verify_installation_manifest(manifest, self.fixture_steam_root)
        self.assertFalse(valid)
        self.assertTrue(any("Corrupted" in e for e in errors))

        # 2. Missing target file
        self.target_win32u.unlink()
        valid, errors = verify_installation_manifest(manifest, self.fixture_steam_root)
        self.assertFalse(valid)
        self.assertTrue(any("Missing" in e for e in errors))

    def test_d_rollback_restores_original_byte_for_byte(self):
        """(d) rollback restores target file to original SHA256 and leaves zero external write."""
        # Record pre-install tree fingerprint
        pre_fingerprint = compute_tree_fingerprint(self.fixture_steam_root)

        plan = create_compat_module_plan(
            fixture_steam_root=self.fixture_steam_root,
            target_rel_path=str(self.proton_rel_path),
            source_module_path=self.patched_win32u,
            expected_orig_sha256=self.orig_sha256,
            expected_arch="aarch64"
        )
        backup_dir = self.fixture_steam_root / ".compat_backups"
        manifest = apply_installation_plan(plan, self.fixture_steam_root, backup_dir=backup_dir)
        self.assertEqual(sha256_file(self.target_win32u), self.patched_sha256)

        # Rollback
        rollback_report = rollback_installation_manifest(manifest, self.fixture_steam_root)
        self.assertEqual(rollback_report["status"], "success")

        # Check target win32u byte-for-byte exact restoration
        self.assertEqual(sha256_file(self.target_win32u), self.orig_sha256)
        self.assertEqual(self.target_win32u.read_bytes(), self.orig_elf_content)

        # Verify backup directory cleaned up or restored
        post_fingerprint = compute_tree_fingerprint(self.fixture_steam_root)
        self.assertEqual(pre_fingerprint, post_fingerprint)

    def test_e_security_rejects_escape_and_traversal(self):
        """(e) Rejects absolute path, '..' traversal, and symlink escape."""
        # 1. Absolute path target
        with self.assertRaises(SteamPlanError):
            create_compat_module_plan(
                fixture_steam_root=self.fixture_steam_root,
                target_rel_path="/Applications/Steam.app/libwin32u.so",
                source_module_path=self.patched_win32u
            )

        # 2. '..' Traversal outside fixture root
        with self.assertRaises(SteamPlanError):
            create_compat_module_plan(
                fixture_steam_root=self.fixture_steam_root,
                target_rel_path="../../outside/win32u.so",
                source_module_path=self.patched_win32u
            )

        # 3. Symlink escape
        escape_dir = self.scratch_dir / "outside_escape"
        escape_dir.mkdir(parents=True, exist_ok=True)
        outside_file = escape_dir / "evil.so"
        outside_file.write_bytes(b"EVIL")
        
        symlink_target = self.fixture_steam_root / "symlink_leak.so"
        os.symlink(outside_file, symlink_target)

        with self.assertRaises(SteamPlanError):
            create_compat_module_plan(
                fixture_steam_root=self.fixture_steam_root,
                target_rel_path="symlink_leak.so",
                source_module_path=self.patched_win32u
            )

    def test_f_precondition_failures_explicit(self):
        """(f) Missing target file or architecture mismatch explicitly fails (no silent skip)."""
        # 1. Target file does not exist
        missing_rel_path = "compatibilitytools.d/proton_arm64/files/nonexistent.so"
        with self.assertRaises(SteamPlanError) as ctx:
            create_compat_module_plan(
                fixture_steam_root=self.fixture_steam_root,
                target_rel_path=missing_rel_path,
                source_module_path=self.patched_win32u
            )
        self.assertIn("Target file does not exist", str(ctx.exception))

        # 2. Original SHA256 mismatch
        with self.assertRaises(SteamPlanError) as ctx:
            create_compat_module_plan(
                fixture_steam_root=self.fixture_steam_root,
                target_rel_path=str(self.proton_rel_path),
                source_module_path=self.patched_win32u,
                expected_orig_sha256="0000000000000000000000000000000000000000000000000000000000000000"
            )
        self.assertIn("Original file checksum mismatch", str(ctx.exception))

        # 3. Architecture mismatch (e.g. target is x86_64, not aarch64)
        x86_elf_content = (
            b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 +
            b"\x03\x00" +
            b"\x3e\x00" +  # EM_X86_64 (62 = 0x3e)
            b"\x01\x00\x00\x00" +
            b"X86_64_CONTENT"
        )
        x86_target = self.fixture_steam_root / "compatibilitytools.d/proton_x64/lib.so"
        x86_target.parent.mkdir(parents=True, exist_ok=True)
        x86_target.write_bytes(x86_elf_content)

        with self.assertRaises(SteamPlanError) as ctx:
            create_compat_module_plan(
                fixture_steam_root=self.fixture_steam_root,
                target_rel_path="compatibilitytools.d/proton_x64/lib.so",
                source_module_path=self.patched_win32u,
                expected_arch="aarch64"
            )
        self.assertIn("Target architecture mismatch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
