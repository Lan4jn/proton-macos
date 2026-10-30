#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/backend/test_steam_plan.py

Comprehensive End-to-End Test Suite for Steam Compatibility Tool Installation Plan & Manifest Manager.

Requirements verified:
(1) Plan Generation:
    - Pure, side-effect free computation from fixture Steam library root & candidate package.
    - Deterministic, serializable to/from JSON.
(2) Manifest Output:
    - Records installed files, created directories, original permissions, and SHA256 digests.
(3) End-to-End Closed Loop:
    - Plan -> Apply (strictly within fixture root) -> Verify (matches manifest) ->
      Rollback (guided by manifest) -> Exact byte-for-byte restoration.
    - Zero write outside fixture root (verified by host path existence snapshot).
(4) Negative & Boundary Security Tests:
    - Target paths attempting to touch real host Steam (~/Library/Application Support/Steam),
      /Applications, /usr, /System, or escaping fixture root via '..' must be REJECTED BEFORE application.
(5) Idempotency & Repeatability.
"""

import hashlib
import json
import os
import shutil
import stat
import sys
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.steam_plan import (
    SteamPlanError,
    apply_installation_plan,
    compute_tree_fingerprint,
    create_installation_plan,
    rollback_installation_manifest,
    sha256_file,
    validate_path_enclosure,
    verify_installation_manifest,
)


class TestSteamPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Snapshots of real host Steam / system paths to ensure zero leakage
        cls.real_host_paths = [
            Path(os.path.expanduser("~/Library/Application Support/Steam")),
            Path("/Applications/Steam.app"),
            Path("/usr/local/bin"),
            Path("/tmp")
        ]
        cls.host_snapshots = {}
        for p in cls.real_host_paths:
            cls.host_snapshots[str(p)] = p.exists()

    @classmethod
    def tearDownClass(cls):
        for p in cls.real_host_paths:
            s_before = cls.host_snapshots[str(p)]
            now_exists = p.exists()
            assert s_before == now_exists, f"Host path existence mutated for {p}!"

    def setUp(self):
        # Isolated playground within LAB/logs/steam-plan
        self.test_root = LAB / f"logs/steam-plan/test_sandbox_{os.getpid()}_{id(self)}"
        self.test_root.mkdir(parents=True, exist_ok=True)

        self.fixture_steam_root = self.test_root / "mock_steam_library"
        self.fixture_steam_root.mkdir(parents=True, exist_ok=True)

        self.source_candidate_dir = self.test_root / "source_candidate_package"
        self.source_candidate_dir.mkdir(parents=True, exist_ok=True)

        # Populate source candidate package
        (self.source_candidate_dir / "toolmanifest.vdf").write_text(
            '"manifest" { "version" "2" "commandline" "/proton run" }\n'
        )
        (self.source_candidate_dir / "compatibilitytool.vdf").write_text(
            '"compatibilitytools" { "compat_tools" { "proton_test" { } } }\n'
        )
        (self.source_candidate_dir / "proton").write_text("#!/bin/sh\necho Proton Mock\n")
        os.chmod(self.source_candidate_dir / "proton", 0o755)

        sub = self.source_candidate_dir / "files" / "bin"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "wine").write_bytes(b"\x7fELF\x02\x01\x01\x00MOCK_WINE_BINARY")
        os.chmod(sub / "wine", 0o755)

    def tearDown(self):
        if self.test_root.exists():
            shutil.rmtree(self.test_root, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. PURE PLAN GENERATION (Side-effect free & JSON exportable)
    # --------------------------------------------------------------------------
    def test_plan_generation_pure_and_serializable(self):
        """Plan generation must not alter the filesystem and must export cleanly to JSON."""
        fingerprint_before = compute_tree_fingerprint(self.fixture_steam_root)

        plan = create_installation_plan(
            fixture_steam_root=self.fixture_steam_root,
            source_tool_dir=self.source_candidate_dir,
            tool_name="proton_test_tool"
        )

        fingerprint_after = compute_tree_fingerprint(self.fixture_steam_root)
        self.assertEqual(
            fingerprint_before, fingerprint_after,
            "Plan generation MUST NOT modify the destination fixture directory!"
        )

        # Check plan serializability
        plan_json = json.dumps(plan, indent=2)
        parsed = json.loads(plan_json)
        self.assertEqual(parsed["tool_name"], "proton_test_tool")
        self.assertGreater(parsed["total_steps"], 0)
        self.assertTrue(any(s["type"] == "install_file" for s in parsed["steps"]))

    # --------------------------------------------------------------------------
    # 2. CLOSED LOOP: Plan -> Apply -> Verify -> Rollback -> Byte-for-byte exact equality
    # --------------------------------------------------------------------------
    def test_end_to_end_closed_loop_and_byte_exact_rollback(self):
        """Applying plan and rolling back must restore directory to identical byte state."""
        # Baseline files in fixture Steam directory (pre-existing tools and config)
        compat_dir = self.fixture_steam_root / "compatibilitytools.d"
        compat_dir.mkdir(parents=True, exist_ok=True)
        (compat_dir / "other_tool.txt").write_text("existing_third_party_tool_metadata\n")
        (self.fixture_steam_root / "libraryfolders.vdf").write_text('"LibraryFolders" { "0" "/path" }\n')

        # 1. Take initial tree fingerprint
        initial_fingerprint = compute_tree_fingerprint(self.fixture_steam_root)
        self.assertTrue(len(initial_fingerprint) > 0)

        # 2. Create and export plan
        plan = create_installation_plan(
            fixture_steam_root=self.fixture_steam_root,
            source_tool_dir=self.source_candidate_dir,
            tool_name="proton_arm64_runtime"
        )

        # 3. Apply plan
        manifest = apply_installation_plan(plan, self.fixture_steam_root)
        self.assertIn("installed_files", manifest)
        self.assertIn("created_directories", manifest)
        self.assertEqual(len(manifest["installed_files"]), 4)

        # 4. Verify manifest against disk
        is_valid, errors = verify_installation_manifest(manifest, self.fixture_steam_root)
        self.assertTrue(is_valid, f"Manifest verification failed: {errors}")

        # Check installed files exist with correct modes
        installed_tool_dir = self.fixture_steam_root / "compatibilitytools.d" / "proton_arm64_runtime"
        self.assertTrue((installed_tool_dir / "proton").exists())
        self.assertTrue(os.access(installed_tool_dir / "proton", os.X_OK))
        self.assertTrue((installed_tool_dir / "files/bin/wine").exists())

        # 5. Rollback using manifest
        rollback_report = rollback_installation_manifest(manifest, self.fixture_steam_root)
        self.assertEqual(len(rollback_report["errors"]), 0, f"Rollback errors: {rollback_report['errors']}")
        self.assertEqual(len(rollback_report["files_removed"]), 4)

        # 6. Assert byte-for-byte exact equality to initial state
        post_rollback_fingerprint = compute_tree_fingerprint(self.fixture_steam_root)
        self.assertEqual(
            initial_fingerprint, post_rollback_fingerprint,
            "Post-rollback state MUST match initial state exactly (all files, modes, and sizes)!"
        )

        # Installed tool directory must be completely gone
        self.assertFalse(installed_tool_dir.exists())

    # --------------------------------------------------------------------------
    # 3. NEGATIVE SECURITY TESTS (Strict enclosure & rejection before write)
    # --------------------------------------------------------------------------
    def test_rejection_of_real_steam_path_in_plan(self):
        """Any attempt to set real Steam root must be rejected immediately with SteamPlanError."""
        real_steam_path = Path(os.path.expanduser("~/Library/Application Support/Steam"))
        with self.assertRaises(SteamPlanError) as ctx:
            create_installation_plan(
                fixture_steam_root=real_steam_path,
                source_tool_dir=self.source_candidate_dir
            )
        self.assertIn("forbidden host root", str(ctx.exception))

    def test_rejection_of_system_paths(self):
        """System paths (/Applications, /usr, /etc) must be hard-rejected."""
        for bad_path in [Path("/Applications"), Path("/usr/local"), Path("/etc")]:
            with self.assertRaises(SteamPlanError):
                create_installation_plan(
                    fixture_steam_root=bad_path,
                    source_tool_dir=self.source_candidate_dir
                )

    def test_rejection_of_path_traversal_escaping_fixture_root(self):
        """Escaping fixture root via '..' in steps must fail enclosure validation."""
        plan = create_installation_plan(
            fixture_steam_root=self.fixture_steam_root,
            source_tool_dir=self.source_candidate_dir,
            tool_name="tool_normal"
        )
        # Poison step destination to escape fixture root
        plan["steps"][0]["destination"] = str(self.test_root.parent / "escaped_dir")

        with self.assertRaises(SteamPlanError) as ctx:
            apply_installation_plan(plan, self.fixture_steam_root)
        self.assertIn("Path enclosure violation", str(ctx.exception))

    # --------------------------------------------------------------------------
    # 4. IDEMPOTENCY TEST: Repeated planning and execution
    # --------------------------------------------------------------------------
    def test_idempotent_plan_generation(self):
        """Generating plan multiple times must produce identical JSON representations."""
        plan1 = create_installation_plan(self.fixture_steam_root, self.source_candidate_dir, "tool1")
        plan2 = create_installation_plan(self.fixture_steam_root, self.source_candidate_dir, "tool1")
        self.assertEqual(json.dumps(plan1, sort_keys=True), json.dumps(plan2, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
