#!/usr/bin/env python3
"""
Unit and CLI integration tests for check_prerequisites.py.
Verifies return codes:
  20 : Official direct Steam acquisition blocked
  10 : Public redistribution verified, but full Proton / x64 execution NOT VERIFIED (in-progress)
   1 : elfuse baseline execution FAILED or missing
   0 : All integration checks passed (ELF + Proton package + x64 execution VERIFIED)
   2 : CLI argument / usage error or missing file
Also verifies dynamic conclusion text, strict state isolation, and provenance reporting.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure script dir and lab root are in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
LAB_ROOT = SCRIPT_DIR.parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from check_prerequisites import (
    evaluate_prerequisites,
    evaluate_public_manifest,
    generate_conclusion,
    generate_public_conclusion,
)


class TestIntegrationPrerequisites(unittest.TestCase):
    def test_missing_package_blocked(self):
        mock_identity = {
            "artifact_name": "Proton Experimental (ARM64)",
            "app_id": 4427310,
            "depot_id": 4427311,
            "acquisition_status": "metadata-only",
            "download_blocked": True,
            "local_package_path": None,
            "sha256": None,
        }
        res = evaluate_prerequisites(mock_identity, elfuse_verified=True)
        self.assertEqual(res["elfuse_status"], "VERIFIED")
        self.assertEqual(res["package_status"], "BLOCKED")
        self.assertEqual(res["wine_execution_status"], "NOT_RUN")
        self.assertEqual(res["fex_execution_status"], "NOT_RUN")
        self.assertIn("official package missing", res["blocker_reason"].lower())

    def test_empty_string_package_path_blocked(self):
        mock_identity = {
            "local_package_path": "   ",
            "download_blocked": False,
        }
        res = evaluate_prerequisites(mock_identity, elfuse_verified=True)
        self.assertEqual(res["package_status"], "BLOCKED")
        self.assertEqual(res["wine_execution_status"], "NOT_RUN")

    def test_nonexistent_local_path_blocked(self):
        mock_identity = {
            "acquisition_status": "downloaded",
            "download_blocked": False,
            "local_package_path": "/path/to/nonexistent/directory",
            "sha256": "abcdef",
        }
        res = evaluate_prerequisites(mock_identity, elfuse_verified=True)
        self.assertEqual(res["package_status"], "BLOCKED")
        self.assertEqual(res["wine_execution_status"], "NOT_RUN")
        self.assertIn("does not exist", res["blocker_reason"])

    def test_local_path_present_unverified(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            mock_identity = {
                "acquisition_status": "downloaded",
                "download_blocked": False,
                "local_package_path": tmp_dir,
                "sha256": None,  # unverified
            }
            res = evaluate_prerequisites(mock_identity, elfuse_verified=True)
            self.assertEqual(res["package_status"], "LOCAL_PATH_PRESENT_UNVERIFIED")
            self.assertEqual(res["wine_execution_status"], "NOT_RUN")
            self.assertEqual(res["fex_execution_status"], "NOT_RUN")
            self.assertIn("not been verified", res["blocker_reason"])

    def test_unverified_elfuse_marks_elfuse_failed(self):
        mock_identity = {
            "local_package_path": None,
            "download_blocked": True,
        }
        res = evaluate_prerequisites(mock_identity, elfuse_verified=False)
        self.assertEqual(res["elfuse_status"], "FAILED")
        self.assertEqual(res["wine_execution_status"], "NOT_RUN")
        self.assertEqual(res["fex_execution_status"], "NOT_RUN")

    def test_elfuse_failed_even_if_package_ready(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            mock_identity = {
                "acquisition_status": "verified",
                "download_blocked": False,
                "local_package_path": tmp_dir,
                "sha256": "real_sha256_hash",
            }
            res = evaluate_prerequisites(mock_identity, elfuse_verified=False)
            self.assertEqual(res["elfuse_status"], "FAILED")
            self.assertEqual(res["package_status"], "READY")
            # CRITICAL: Wine/FEX must NOT be PENDING_EXECUTION if elfuse is FAILED!
            self.assertEqual(res["wine_execution_status"], "NOT_RUN")
            self.assertEqual(res["fex_execution_status"], "NOT_RUN")

    def test_dynamic_conclusions(self):
        res_blocked = {
            "elfuse_status": "VERIFIED",
            "package_status": "BLOCKED",
        }
        text_blocked = generate_conclusion(res_blocked)
        self.assertIn("blocked at official package acquisition (Exit 20)", text_blocked)
        self.assertIn("Wine / FEX tests NOT RUN", text_blocked)

        res_elfuse_fail = {
            "elfuse_status": "FAILED",
            "package_status": "READY",
        }
        text_elfuse_fail = generate_conclusion(res_elfuse_fail)
        self.assertIn("elfuse) FAILED", text_elfuse_fail)
        self.assertIn("CANNOT RUN", text_elfuse_fail)

        res_unverified = {
            "elfuse_status": "VERIFIED",
            "package_status": "LOCAL_PATH_PRESENT_UNVERIFIED",
        }
        text_unverified = generate_conclusion(res_unverified)
        self.assertIn("UNVERIFIED (Exit 20)", text_unverified)

    def test_cli_exit_code_real_lab_root_returns_20(self):
        lab_root = Path(__file__).resolve().parent.parent.parent
        script_path = lab_root / "scripts" / "integration" / "check_prerequisites.py"

        env = os.environ.copy()
        env["HOME"] = str(lab_root / "fixtures" / "integration" / "steamcmd_home")
        env["TMPDIR"] = str(lab_root / "fixtures" / "integration" / "tmp")

        proc = subprocess.run(
            [sys.executable, str(script_path), "--lab-root", str(lab_root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 20)
        self.assertIn("Execution blocked at official package acquisition (Exit 20)", proc.stdout)

    def test_cli_exit_code_missing_identity_returns_2(self):
        with tempfile.TemporaryDirectory() as empty_lab:
            script_path = Path(__file__).resolve().parent / "check_prerequisites.py"
            proc = subprocess.run(
                [sys.executable, str(script_path), "--lab-root", empty_lab],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(proc.returncode, 2)

    # --- New tests for task-15: --public-manifest support ---

    def test_evaluate_public_manifest_classifications(self):
        lab_root = Path(__file__).resolve().parent.parent.parent
        manifest_path = lab_root / "artifacts" / "public-proton" / "bundle.json"

        res = evaluate_public_manifest(manifest_path, elfuse_verified=True, lab_root=lab_root)
        self.assertEqual(res["elfuse_status"], "VERIFIED")
        self.assertEqual(res["package_status"], "PUBLIC_REDISTRIBUTION_VERIFIED")
        self.assertEqual(res["full_proton_status"], "FULL_PROTON_NOT_VALIDATED")
        # Ensure checker does not falsely claim component execution
        self.assertEqual(res["wine_execution_status"], "COMPONENT_EXECUTION_NOT_CHECKED")
        self.assertEqual(res["x64_execution_status"], "X64_NOT_VERIFIED")
        self.assertFalse(res["independent_valve_signature_verified"])
        self.assertIn("The412Banner/winlator-contents", res["publisher"])
        self.assertEqual(res["provenance"], "PUBLIC_REDISTRIBUTOR_CHECKSUM_VERIFIED_VALVE_ORIGIN_CLAIMED")

        conclusion = generate_public_conclusion(res)
        self.assertIn("PUBLIC_REDISTRIBUTION_VERIFIED", conclusion)
        self.assertIn("FULL_PROTON_NOT_VALIDATED", conclusion)
        self.assertIn("COMPONENT_EXECUTION_NOT_CHECKED", conclusion)
        self.assertIn("X64_NOT_VERIFIED", conclusion)
        self.assertIn("Exit 10", conclusion)

    def test_cli_public_manifest_real_returns_10(self):
        lab_root = Path(__file__).resolve().parent.parent.parent
        script_path = lab_root / "scripts" / "integration" / "check_prerequisites.py"
        manifest_path = lab_root / "artifacts" / "public-proton" / "bundle.json"

        proc = subprocess.run(
            [sys.executable, str(script_path), "--lab-root", str(lab_root), "--public-manifest", str(manifest_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(proc.returncode, 10, f"Expected exit code 10, got {proc.returncode}. Output:\n{proc.stdout}")
        self.assertIn("PUBLIC_REDISTRIBUTION_VERIFIED", proc.stdout)
        self.assertIn("COMPONENT_EXECUTION_NOT_CHECKED", proc.stdout)
        self.assertIn("FULL_PROTON_NOT_VALIDATED", proc.stdout)
        self.assertIn("X64_NOT_VERIFIED", proc.stdout)
        self.assertNotIn("COMPONENTS_TESTED", proc.stdout)
        self.assertIn("Valve origin claimed but NOT independently signed by Valve", proc.stdout)

    def test_public_manifest_corrupted_has_accurate_detail_and_exit_20(self):
        lab_root = Path(__file__).resolve().parent.parent.parent
        script_path = lab_root / "scripts" / "integration" / "check_prerequisites.py"

        with tempfile.TemporaryDirectory() as tmp_dir:
            bad_manifest = Path(tmp_dir) / "corrupt_bundle.json"
            bad_manifest.write_text(json.dumps({
                "schema": 1,
                "bundle": str(Path(tmp_dir) / "nonexistent_bundle"),
                "critical_files": {"files/bin-arm64/wine": "fake_sha"}
            }))

            res = evaluate_public_manifest(bad_manifest, elfuse_verified=True, lab_root=lab_root)
            self.assertEqual(res["package_status"], "CORRUPTED")
            self.assertIn("verification failed", res["package_detail"].lower())
            # Crucial: Must NOT claim checksums verified when bundle is corrupted
            self.assertNotIn("checksums verified", res["package_detail"].lower())

            proc = subprocess.run(
                [sys.executable, str(script_path), "--lab-root", str(lab_root), "--public-manifest", str(bad_manifest)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(proc.returncode, 20)
            self.assertIn("Public bundle verification FAILED", proc.stdout)

    def test_cli_public_manifest_missing_returns_2(self):
        lab_root = Path(__file__).resolve().parent.parent.parent
        script_path = lab_root / "scripts" / "integration" / "check_prerequisites.py"

        proc = subprocess.run(
            [sys.executable, str(script_path), "--lab-root", str(lab_root), "--public-manifest", "/nonexistent/bundle.json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Missing public manifest", proc.stderr)

    def test_public_manifest_elfuse_failed_returns_1(self):
        lab_root = Path(__file__).resolve().parent.parent.parent
        manifest_path = lab_root / "artifacts" / "public-proton" / "bundle.json"

        res = evaluate_public_manifest(manifest_path, elfuse_verified=False, lab_root=lab_root)
        self.assertEqual(res["elfuse_status"], "FAILED")
        self.assertEqual(res["package_status"], "PUBLIC_REDISTRIBUTION_VERIFIED")
        self.assertEqual(res["x64_execution_status"], "NOT_RUN")

        conclusion = generate_public_conclusion(res)
        self.assertIn("elfuse) FAILED", conclusion)


if __name__ == "__main__":
    unittest.main()
