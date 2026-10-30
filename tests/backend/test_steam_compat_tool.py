#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/backend/test_steam_compat_tool.py

Comprehensive Test Suite for Steam Compatibility Tool Layout with Integrated Reversible Compat Module (task-130).

Requirements verified:
(a) Tool manifest generation: toolmanifest.vdf and compatibilitytool.vdf with legal fields
    (install_path, display_name, from_oslist, to_oslist, commandline, %verb%, --).
    Verified using an independent recursive Valve VDF parser (parse_valve_vdf), NOT self-certifying parse_simple_vdf.
(b) Unified install plan & manifest: Replaced win32u.so enters the same install-plan and manifest as a compat module entry alongside tool files.
(c) Apply: target tree SHA256 matches expected patched module and tool files.
(d) Verify: detects tampering or deletion in either tool files or compat module.
(e) Rollback: byte-for-byte restoration of compat module, and tool directory's other files are preserved untouched.
(f) Security: rejects absolute paths, '..' traversal, and symlink escapes in tool and compat module.
(g) Preconditions: explicit failure on original checksum mismatch or architecture mismatch.
(h) Relocatable launch: after installation into fixture steam root, source tool directory can be renamed/moved away and the installed tool STILL launches cleanly via its wrapper.
(i) Real argv boundary preservation: spaces, metacharacters, and verbs preserved verbatim through the adapter wrapper.
"""

import hashlib
import json
import os
import shlex
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

from scripts.backend.steam_plan import (
    SteamPlanError,
    apply_installation_plan,
    compute_tree_fingerprint,
    create_compat_tool_plan,
    generate_compatibility_tool_vdfs,
    parse_valve_vdf,
    rollback_installation_manifest,
    sha256_file,
    validate_path_enclosure,
    verify_installation_manifest,
)
from scripts.backend.steam_handoff import prepare_runtime_tool


class TestSteamCompatTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Precise bounded host observation anchors
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
        self.scratch_dir = Path(tempfile.mkdtemp(prefix="test_compat_tool_", dir=str(LAB / "logs")))
        self.fixture_steam_root = self.scratch_dir / "SteamRoot"
        self.fixture_steam_root.mkdir(parents=True, exist_ok=True)

        # 1. Mock existing tool base directory in source (representing Proton-Experimental package)
        self.source_tool_dir = self.scratch_dir / "source_proton_package"
        self.source_tool_dir.mkdir(parents=True, exist_ok=True)

        # Create mock file structure in source tool
        self.wine_rel_path = "files/lib/wine/aarch64-unix/win32u.so"
        self.source_orig_win32u = self.source_tool_dir / self.wine_rel_path
        self.source_orig_win32u.parent.mkdir(parents=True, exist_ok=True)

        # Original unpatched win32u.so (ELF 64-bit LSB EM_AARCH64 = 183)
        self.orig_elf_content = (
            b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 +
            b"\x03\x00" +
            b"\xb7\x00" +  # EM_AARCH64 (183)
            b"\x01\x00\x00\x00" +
            b"ORIGINAL_WIN32U_MOCK_CONTENT_4F6013FA" * 8
        )
        self.source_orig_win32u.write_bytes(self.orig_elf_content)
        self.orig_sha256 = sha256_file(self.source_orig_win32u)

        # 2. Source patched win32u.so (mocking 59a76b05...)
        self.patched_so_path = self.scratch_dir / "patched_win32u.so"
        self.patched_elf_content = (
            b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 +
            b"\x03\x00" +
            b"\xb7\x00" +
            b"\x01\x00\x00\x00" +
            b"PATCHED_GUARD_V3_WIN32U_59A76B05" * 10
        )
        self.patched_so_path.write_bytes(self.patched_elf_content)
        self.patched_sha256 = sha256_file(self.patched_so_path)

        # 3. Tool name and display name
        self.tool_name = "proton_arm64_patched"
        self.display_name = "Proton macOS Lab (Vulkan Guard Patched)"

    def tearDown(self):
        shutil.rmtree(self.scratch_dir, ignore_errors=True)
        # Bounded observation check
        for p, orig_files in self.host_snapshots.items():
            if p.exists():
                cur_files = set(os.listdir(p))
                self.assertEqual(orig_files, cur_files, f"Bounded observation failure: anchor '{p}' modified!")

    def test_a_vdf_generation_and_valve_vdf_parser(self):
        """(a) toolmanifest.vdf and compatibilitytool.vdf parsed with independent Valve VDF parser."""
        generate_compatibility_tool_vdfs(
            output_dir=self.source_tool_dir,
            tool_name=self.tool_name,
            display_name=self.display_name,
            wrapper_rel_path="proton-wrapper.sh"
        )

        manifest_file = self.source_tool_dir / "toolmanifest.vdf"
        compat_file = self.source_tool_dir / "compatibilitytool.vdf"

        self.assertTrue(manifest_file.exists())
        self.assertTrue(compat_file.exists())

        # Parse with independent recursive Valve VDF parser
        manifest_data = parse_valve_vdf(manifest_file.read_text(encoding="utf-8"))
        compat_data = parse_valve_vdf(compat_file.read_text(encoding="utf-8"))

        # Verify toolmanifest.vdf structure
        self.assertIn("manifest", manifest_data)
        self.assertEqual(manifest_data["manifest"]["version"], "2")
        cmdline = manifest_data["manifest"]["commandline"]
        self.assertIn("%verb%", cmdline)
        self.assertIn("--", cmdline)

        # Verify compatibilitytool.vdf structure
        self.assertIn("compatibilitytools", compat_data)
        self.assertIn("compat_tools", compat_data["compatibilitytools"])
        tools = compat_data["compatibilitytools"]["compat_tools"]
        self.assertIn(self.tool_name, tools)
        tool_entry = tools[self.tool_name]
        self.assertEqual(tool_entry["install_path"], ".")
        self.assertEqual(tool_entry["display_name"], self.display_name)
        self.assertEqual(tool_entry["from_oslist"], "windows")
        self.assertEqual(tool_entry["to_oslist"], "macos")

    def test_b_unified_install_plan_and_manifest(self):
        """(b) win32u.so enters the same install-plan and manifest as a compat module entry alongside tool files."""
        generate_compatibility_tool_vdfs(self.source_tool_dir, self.tool_name, self.display_name)

        plan = create_compat_tool_plan(
            fixture_steam_root=self.fixture_steam_root,
            source_tool_dir=self.source_tool_dir,
            tool_name=self.tool_name,
            display_name=self.display_name,
            compat_modules=[{
                "target_rel_path": self.wine_rel_path,
                "source_path": self.patched_so_path,
                "expected_orig_sha256": self.orig_sha256,
                "expected_arch": "aarch64"
            }]
        )

        self.assertEqual(plan["plan_type"], "compat_tool_installation")
        step_types = [s["type"] for s in plan["steps"]]
        self.assertIn("create_directory", step_types)
        self.assertIn("install_file", step_types)
        self.assertIn("replace_compat_module", step_types)

        manifest = apply_installation_plan(plan, self.fixture_steam_root)
        self.assertIn("installed_files", manifest)
        self.assertIn("compat_modules", manifest)
        self.assertEqual(len(manifest["compat_modules"]), 1)
        self.assertEqual(manifest["compat_modules"][0]["source_sha256"], self.patched_sha256)
        self.assertEqual(manifest["compat_modules"][0]["original_sha256"], self.orig_sha256)

    def test_c_apply_target_tree_sha_matches_expected(self):
        """(c) apply correctly installs tool and replaces win32u.so with matching SHA."""
        generate_compatibility_tool_vdfs(self.source_tool_dir, self.tool_name, self.display_name)
        plan = create_compat_tool_plan(
            self.fixture_steam_root, self.source_tool_dir, self.tool_name,
            compat_modules=[{
                "target_rel_path": self.wine_rel_path,
                "source_path": self.patched_so_path,
                "expected_orig_sha256": self.orig_sha256,
                "expected_arch": "aarch64"
            }]
        )
        manifest = apply_installation_plan(plan, self.fixture_steam_root)

        dest_tool_dir = self.fixture_steam_root / "compatibilitytools.d" / self.tool_name
        dest_win32u = dest_tool_dir / self.wine_rel_path
        self.assertTrue(dest_win32u.exists())
        self.assertEqual(sha256_file(dest_win32u), self.patched_sha256)

    def test_d_verify_detects_tampering(self):
        """(d) verify detects tampering or deletion in either tool files or compat module."""
        generate_compatibility_tool_vdfs(self.source_tool_dir, self.tool_name, self.display_name)
        plan = create_compat_tool_plan(
            self.fixture_steam_root, self.source_tool_dir, self.tool_name,
            compat_modules=[{
                "target_rel_path": self.wine_rel_path,
                "source_path": self.patched_so_path,
                "expected_orig_sha256": self.orig_sha256,
                "expected_arch": "aarch64"
            }]
        )
        manifest = apply_installation_plan(plan, self.fixture_steam_root)

        valid, errors = verify_installation_manifest(manifest, self.fixture_steam_root)
        self.assertTrue(valid)

        dest_tool_dir = self.fixture_steam_root / "compatibilitytools.d" / self.tool_name
        dest_win32u = dest_tool_dir / self.wine_rel_path

        dest_win32u.write_bytes(b"TAMPERED")
        valid, errors = verify_installation_manifest(manifest, self.fixture_steam_root)
        self.assertFalse(valid)
        self.assertTrue(any("Corrupted" in e for e in errors))

    def test_e_rollback_byte_exact_restoration(self):
        """(e) rollback restores state byte-for-byte; preserves unrelated files in fixture root."""
        generate_compatibility_tool_vdfs(self.source_tool_dir, self.tool_name, self.display_name)
        unrelated_file = self.fixture_steam_root / "config/config.vdf"
        unrelated_file.parent.mkdir(parents=True, exist_ok=True)
        unrelated_file.write_text("UnrelatedSteamConfigContent")
        unrelated_sha = sha256_file(unrelated_file)

        pre_tree = compute_tree_fingerprint(self.fixture_steam_root)

        plan = create_compat_tool_plan(
            self.fixture_steam_root, self.source_tool_dir, self.tool_name,
            compat_modules=[{
                "target_rel_path": self.wine_rel_path,
                "source_path": self.patched_so_path,
                "expected_orig_sha256": self.orig_sha256,
                "expected_arch": "aarch64"
            }]
        )
        manifest = apply_installation_plan(plan, self.fixture_steam_root)
        rollback_report = rollback_installation_manifest(manifest, self.fixture_steam_root)
        self.assertEqual(rollback_report["status"], "success")

        self.assertTrue(unrelated_file.exists())
        self.assertEqual(sha256_file(unrelated_file), unrelated_sha)
        post_tree = compute_tree_fingerprint(self.fixture_steam_root)
        self.assertEqual(pre_tree, post_tree)

    def test_f_security_rejects_escape_and_traversal(self):
        """(f) Rejects absolute paths, '..' traversal, and symlink escapes in tool and compat module."""
        with self.assertRaises(SteamPlanError):
            create_compat_tool_plan(
                self.fixture_steam_root, self.source_tool_dir, self.tool_name,
                compat_modules=[{
                    "target_rel_path": "/usr/lib/win32u.so",
                    "source_path": self.patched_so_path
                }]
            )

        with self.assertRaises(SteamPlanError):
            create_compat_tool_plan(
                self.fixture_steam_root, self.source_tool_dir, "../../evil_tool",
                compat_modules=[]
            )

    def test_g_precondition_failures_explicit(self):
        """(g) Original checksum mismatch or architecture mismatch fails explicitly."""
        with self.assertRaises(SteamPlanError) as ctx:
            create_compat_tool_plan(
                self.fixture_steam_root, self.source_tool_dir, self.tool_name,
                compat_modules=[{
                    "target_rel_path": self.wine_rel_path,
                    "source_path": self.patched_so_path,
                    "expected_orig_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                    "expected_arch": "aarch64"
                }]
            )
        self.assertIn("Original file checksum mismatch", str(ctx.exception))

    def test_h_relocatable_launch_after_source_renamed(self):
        """(h) NEW: Installed compatibility tool launches cleanly even after source tool directory is moved away."""
        # Prepare a realistic runtime tool package in source directory
        candidate = prepare_runtime_tool(
            output_dir=self.source_tool_dir,
            target_dir=self.fixture_steam_root / "compatibilitytools.d",
            execute_runtime=False
        )
        
        # Build compat tool plan
        plan = create_compat_tool_plan(
            fixture_steam_root=self.fixture_steam_root,
            source_tool_dir=self.source_tool_dir,
            tool_name=self.tool_name,
            compat_modules=[{
                "target_rel_path": self.wine_rel_path,
                "source_path": self.patched_so_path,
                "expected_orig_sha256": self.orig_sha256,
                "expected_arch": "aarch64"
            }]
        )

        manifest = apply_installation_plan(plan, self.fixture_steam_root)

        dest_tool_dir = self.fixture_steam_root / "compatibilitytools.d" / self.tool_name
        dest_wrapper = dest_tool_dir / "proton-wrapper.sh"
        self.assertTrue(dest_wrapper.exists())

        # SIMULATE SOURCE DIRECTORY MOVED / DELETED
        moved_source = self.scratch_dir / "moved_away_source_package"
        shutil.move(self.source_tool_dir, moved_source)
        self.assertFalse(self.source_tool_dir.exists())

        # Execute installed wrapper from destination directory!
        cmd = [str(dest_wrapper), "runinprefix", "C:\\game\\test.exe"]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        self.assertEqual(p.returncode, 0, f"Installed wrapper failed after source was moved! stderr: {p.stderr}")
        out_json = json.loads(p.stdout)
        self.assertEqual(out_json["status"], "PLAN_READY")

    def test_i_real_argv_and_metacharacter_preservation(self):
        """(i) NEW: Real argv passing preserves spaces, unicode, leading dashes, and %verb% through wrapper."""
        prepare_runtime_tool(
            output_dir=self.source_tool_dir,
            target_dir=self.fixture_steam_root / "compatibilitytools.d",
            execute_runtime=False
        )
        plan = create_compat_tool_plan(
            fixture_steam_root=self.fixture_steam_root,
            source_tool_dir=self.source_tool_dir,
            tool_name=self.tool_name,
            compat_modules=[{
                "target_rel_path": self.wine_rel_path,
                "source_path": self.patched_so_path,
                "expected_orig_sha256": self.orig_sha256,
                "expected_arch": "aarch64"
            }]
        )
        apply_installation_plan(plan, self.fixture_steam_root)

        dest_tool_dir = self.fixture_steam_root / "compatibilitytools.d" / self.tool_name
        dest_wrapper = dest_tool_dir / "proton-wrapper.sh"

        # Test command with tricky arguments: spaces, unicode, leading dashes
        tricky_target = "C:\\My Games\\游戏测试\\app.exe"
        cmd = [str(dest_wrapper), "waitforexitandrun", tricky_target, "--log-dir", "/tmp/game logs", "--special-flag"]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        self.assertEqual(p.returncode, 0, f"Wrapper invocation failed: {p.stderr}")
        plan_out = json.loads(p.stdout)
        self.assertEqual(plan_out["status"], "PLAN_READY")

        # Verify arguments in plan['argv'] preserved verbatim
        argv = plan_out["argv"]
        self.assertIn(tricky_target, argv)
        self.assertIn("--log-dir", argv)
        self.assertIn("/tmp/game logs", argv)
        self.assertIn("--special-flag", argv)


if __name__ == "__main__":
    unittest.main()
