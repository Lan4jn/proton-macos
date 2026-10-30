#!/usr/bin/env python3
"""
test_runner.py - Pure unit and integration test suite for run_probe.py hardening.

Safety & Isolation Guarantees:
- All test fixtures are strictly created inside:
  /Users/mewcapoo/Projects/proton-macos-lab/logs/hvf-readonly-hardening/
- NO system /tmp usage.
- All compiler, codesign, and probe executions are mocked.
- NO real HVF / Hypervisor calls or binaries are executed.
"""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import run_probe
from run_probe import (
    LAB_DIR,
    create_seed_file,
    generate_report,
    preflight_check_outputs,
    run_probe_workflow,
    safe_decode,
    sha256_file,
    verify_path_boundary,
)

TEST_ROOT = LAB_DIR / "logs" / "hvf-readonly-hardening" / "test_fixtures"


class TestRunProbeHardening(unittest.TestCase):
    def setUp(self):
        # Create isolated fixture directory inside lab/logs/hvf-readonly-hardening
        self.fixture_dir = TEST_ROOT / f"run_{os.getpid()}_{id(self)}"
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        self.mock_scripts = self.fixture_dir / "scripts"
        self.mock_fixtures = self.fixture_dir / "fixtures"
        self.mock_logs = self.fixture_dir / "logs"
        self.mock_reports = self.fixture_dir / "reports"
        for d in (self.mock_scripts, self.mock_fixtures, self.mock_logs, self.mock_reports):
            d.mkdir(parents=True, exist_ok=True)

        # Create mock probe.c and entitlements.plist in fixture dir
        self.mock_probe_src = self.mock_scripts / "probe.c"
        self.mock_probe_src.write_text("// mock probe.c\n")
        self.mock_entitlements = self.mock_fixtures / "entitlements.plist"
        self.mock_entitlements.write_text("<plist></plist>\n")

    def tearDown(self):
        if self.fixture_dir.exists():
            shutil.rmtree(self.fixture_dir, ignore_errors=True)

    def _sample_probe_jsonl(self, case_b_success: bool = False, case_b_return: int = 0xFAE94001):
        lines = [
            json.dumps({"event": "vm_create", "hv_return": 0, "hv_return_hex": "0x0", "success": True}),
            json.dumps({
                "event": "case_result",
                "case_id": "A",
                "hv_map_success": True,
                "hv_map_return": 0,
                "hv_map_return_hex": "0x00000000",
                "unmap_called": True,
                "hv_unmap_return": 0,
                "hv_unmap_success": True,
                "munmap_return": 0,
                "status": "OK",
            }),
            json.dumps({
                "event": "case_result",
                "case_id": "B",
                "hv_map_success": case_b_success,
                "hv_map_return": 0 if case_b_success else case_b_return,
                "hv_map_return_hex": "0x00000000" if case_b_success else hex(case_b_return),
                "unmap_called": case_b_success,
                "hv_unmap_return": 0 if case_b_success else None,
                "hv_unmap_success": True if case_b_success else None,
                "munmap_return": 0,
                "status": "OK" if case_b_success else "MAP_FAILED",
            }),
            json.dumps({
                "event": "case_result",
                "case_id": "C",
                "hv_map_success": False,
                "hv_map_return": 0xFAE94001,
                "hv_map_return_hex": "0xfae94001",
                "unmap_called": False,
                "hv_unmap_return": None,
                "hv_unmap_success": None,
                "munmap_return": 0,
                "status": "MAP_FAILED",
            }),
            json.dumps({
                "event": "case_result",
                "case_id": "D",
                "hv_map_success": True,
                "hv_map_return": 0,
                "hv_map_return_hex": "0x00000000",
                "unmap_called": True,
                "hv_unmap_return": 0,
                "hv_unmap_success": True,
                "munmap_return": 0,
                "status": "OK",
            }),
            json.dumps({"event": "vm_destroy", "hv_return": 0, "hv_return_hex": "0x0", "success": True}),
        ]
        return "\n".join(lines) + "\n"

    # 1. Existing sentinel protection: must never delete/unlink
    def test_sentinel_exists_never_delete(self):
        sentinel = self.mock_fixtures / "backing_seed.bin"
        sentinel.write_bytes(b"EXISTING_SENTINEL_CONTENT_DO_NOT_DELETE")

        with self.assertRaises(FileExistsError):
            create_seed_file(sentinel, 65536, lab_dir=LAB_DIR)

        # Confirm content was not modified or truncated
        self.assertEqual(sentinel.read_bytes(), b"EXISTING_SENTINEL_CONTENT_DO_NOT_DELETE")

    # 2. Dangling symlink detection
    def test_dangling_symlink_rejected(self):
        dangling = self.mock_fixtures / "dangling_link.bin"
        nonexistent = self.mock_fixtures / "does_not_exist.bin"
        os.symlink(str(nonexistent), str(dangling))

        self.assertTrue(os.path.islink(str(dangling)))
        self.assertFalse(dangling.exists())

        with self.assertRaises((FileExistsError, PermissionError)):
            create_seed_file(dangling, 65536, lab_dir=LAB_DIR)

    # 3. Parent directory symlink detection
    def test_parent_symlink_rejected(self):
        real_target_dir = self.fixture_dir / "real_dir"
        real_target_dir.mkdir()
        symlink_dir = self.fixture_dir / "symlink_dir"
        os.symlink(str(real_target_dir), str(symlink_dir))

        nested_file = symlink_dir / "test.bin"
        with self.assertRaises(PermissionError):
            verify_path_boundary(nested_file, lab_dir=LAB_DIR)

    # 4. Outside lab boundary check
    def test_outside_lab_boundary_rejected(self):
        outside_path = Path("/tmp/outside_test.bin")
        with self.assertRaises(PermissionError):
            verify_path_boundary(outside_path, lab_dir=LAB_DIR)

    # 5. Normal seed creation with O_EXCL, fsync, and close
    def test_seed_creation_success_and_fsync(self):
        target = self.mock_fixtures / "new_seed.bin"
        create_seed_file(target, 65536, lab_dir=LAB_DIR)

        self.assertTrue(target.exists())
        self.assertEqual(target.stat().st_size, 65536)
        content = target.read_bytes()
        self.assertTrue(content.startswith(b"HVF_RO_PROBE_MAGIC_SEED_DATA_BLOCK_0x20000000\n"))

    # 6. Safe decoding of bytes, str, and None
    def test_timeout_bytes_handling_no_typeerror(self):
        self.assertEqual(safe_decode(None), "")
        self.assertEqual(safe_decode("hello"), "hello")
        self.assertEqual(safe_decode(b"hello_bytes"), "hello_bytes")
        # Ensure utf-8 errors are replaced, not raising
        self.assertIsInstance(safe_decode(b"\xff\xfe invalid"), str)

    # 7. Preflight check halts without compiling or running if outputs exist
    def test_preflight_existing_outputs_halts_without_compile(self):
        existing_bin = self.mock_fixtures / "probe"
        existing_bin.write_bytes(b"OLD_BINARY")

        mock_runner = MagicMock()
        result = run_probe_workflow(
            lab_dir=LAB_DIR,
            scripts_dir=self.mock_scripts,
            fixtures_dir=self.mock_fixtures,
            logs_dir=self.mock_logs,
            reports_dir=self.mock_reports,
            subproc_runner=mock_runner,
        )
        self.assertTrue(result["halted"])
        self.assertEqual(result["reason"], "EXISTING_OUTPUTS_DETECTED")
        mock_runner.assert_not_called()

    # 8. Non-zero exit code produces INCONCLUSIVE verdict in mock workflow
    def test_mock_workflow_exit_nonzero_inconclusive(self):
        mock_runner = MagicMock()

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "clang" in cmd_str:
                out_path = Path(cmd[cmd.index("-o") + 1])
                out_path.write_bytes(b"MOCK_COMPILED_BINARY_BYTES")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "codesign" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="com.apple.security.hypervisor", stderr="")
            # Probe execution returns exit code 1
            return subprocess.CompletedProcess(cmd, 1, stdout=self._sample_probe_jsonl(), stderr="Probe crashed")

        mock_runner.side_effect = side_effect

        result = run_probe_workflow(
            lab_dir=LAB_DIR,
            scripts_dir=self.mock_scripts,
            fixtures_dir=self.mock_fixtures,
            logs_dir=self.mock_logs,
            reports_dir=self.mock_reports,
            subproc_runner=mock_runner,
        )
        self.assertFalse(result["halted"])
        self.assertEqual(result["classification"]["verdict"], "INCONCLUSIVE")
        self.assertIn("PROBE_PROCESS_FAILED", result["classification"]["reason"])

    # 9. Process timeout with bytes output produces INCONCLUSIVE and no TypeError
    def test_mock_workflow_timeout_bytes_inconclusive(self):
        mock_runner = MagicMock()

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "clang" in cmd_str:
                out_path = Path(cmd[cmd.index("-o") + 1])
                out_path.write_bytes(b"MOCK_COMPILED_BINARY_BYTES")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "codesign" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="com.apple.security.hypervisor", stderr="")
            # TimeoutExpired with bytes stdout/stderr
            raise subprocess.TimeoutExpired(
                cmd=cmd,
                timeout=5.0,
                output=b'{"event":"vm_create","hv_return":0,"success":true}\n',
                stderr=b"Timeout exceeded\n",
            )

        mock_runner.side_effect = side_effect

        result = run_probe_workflow(
            lab_dir=LAB_DIR,
            scripts_dir=self.mock_scripts,
            fixtures_dir=self.mock_fixtures,
            logs_dir=self.mock_logs,
            reports_dir=self.mock_reports,
            subproc_runner=mock_runner,
        )
        self.assertFalse(result["halted"])
        self.assertEqual(result["classification"]["verdict"], "INCONCLUSIVE")
        self.assertIn("EXECUTION_TIMED_OUT", result["classification"]["reason"])

    # 10. Seed file modified during probe execution is caught as INCONCLUSIVE
    def test_mock_workflow_seed_hash_changed_inconclusive(self):
        mock_runner = MagicMock()
        seed_path = self.mock_fixtures / "backing_seed.bin"

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "clang" in cmd_str:
                out_path = Path(cmd[cmd.index("-o") + 1])
                out_path.write_bytes(b"MOCK_COMPILED_BINARY_BYTES")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "codesign" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="com.apple.security.hypervisor", stderr="")
            # Tamper seed file during probe run
            with open(seed_path, "wb") as f:
                f.write(b"CORRUPTED_SEED_CONTENT" * 1000)
            return subprocess.CompletedProcess(cmd, 0, stdout=self._sample_probe_jsonl(), stderr="")

        mock_runner.side_effect = side_effect

        result = run_probe_workflow(
            lab_dir=LAB_DIR,
            scripts_dir=self.mock_scripts,
            fixtures_dir=self.mock_fixtures,
            logs_dir=self.mock_logs,
            reports_dir=self.mock_reports,
            subproc_runner=mock_runner,
        )
        self.assertFalse(result["halted"])
        self.assertEqual(result["classification"]["verdict"], "INCONCLUSIVE")
        self.assertIn("SEED_HASH_MISMATCH", result["classification"]["reason"])

    # 11. Normal mock execution with Case B failure produces REJECTED with dynamic report
    def test_mock_workflow_normal_rejected_dynamic_report(self):
        mock_runner = MagicMock()

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "clang" in cmd_str:
                out_path = Path(cmd[cmd.index("-o") + 1])
                out_path.write_bytes(b"MOCK_COMPILED_BINARY_BYTES")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "codesign" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="com.apple.security.hypervisor", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout=self._sample_probe_jsonl(case_b_success=False), stderr="")

        mock_runner.side_effect = side_effect

        result = run_probe_workflow(
            lab_dir=LAB_DIR,
            scripts_dir=self.mock_scripts,
            fixtures_dir=self.mock_fixtures,
            logs_dir=self.mock_logs,
            reports_dir=self.mock_reports,
            subproc_runner=mock_runner,
        )
        self.assertFalse(result["halted"])
        self.assertEqual(result["classification"]["verdict"], "REJECTED")

        # Verify dynamic report was generated
        report_file = self.mock_reports / "hvf-readonly-probe.md"
        self.assertTrue(report_file.exists())
        content = report_file.read_text()
        self.assertIn("Admission Verdict: REJECTED", content)
        self.assertIn("Controls: Positive controls A & D succeeded", content)
        # Verify lines <= 12
        lines = [line for line in content.splitlines() if line.strip()]
        self.assertLessEqual(len(lines), 12)


if __name__ == "__main__":
    unittest.main()
