#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for scripts/backend/steam_handoff.py
Ensures:
- Default prepare is strictly plan-only (applied=False, execute_runtime=False)
- Explicit --execute-runtime enables execution mode in candidate wrapper
- Arguments with Unicode, spaces, percent signs, leading dashes are preserved verbatim
- Shell metacharacters ($USER, *.*, ;, etc.) are never expanded
- Malicious environment variables (WINEPREFIX, LD_PRELOAD) cannot override fixed lab prefix
- Unknown Steam verbs are rejected with clear error and non-zero exit
- Mock Steam target directory is never modified (applied=False)
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.steam_handoff import prepare_runtime_tool, execute_from_config, KNOWN_STEAM_VERBS


class TestSteamHandoff(unittest.TestCase):
    def setUp(self):
        self.test_dir = LAB / f"logs/steam-handoff/test_scratch_{os.getpid()}_{id(self)}"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.candidate_out = self.test_dir / "candidate"
        self.mock_target = self.test_dir / "mock_compattools_d"

    def tearDown(self):
        if self.test_dir.exists():
            import shutil
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_default_prepare_is_plan_only(self):
        """Default prepare_runtime_tool must create candidate in plan-only mode (applied=False)."""
        res = prepare_runtime_tool(self.candidate_out, self.mock_target)
        self.assertEqual(res["applied"], False)
        self.assertEqual(res["execute_runtime"], False)

        wrapper = self.candidate_out / "proton-wrapper.sh"
        self.assertTrue(wrapper.is_file())
        self.assertTrue(os.access(str(wrapper), os.X_OK))

        manifest_file = self.candidate_out / "toolmanifest.vdf"
        self.assertTrue(manifest_file.is_file())
        compat_file = self.candidate_out / "compatibilitytool.vdf"
        self.assertTrue(compat_file.is_file())

        plan_file = self.candidate_out / "install-plan.json"
        self.assertTrue(plan_file.is_file())
        plan_data = json.loads(plan_file.read_text())
        self.assertFalse(plan_data["applied"])
        self.assertFalse(plan_data["execute_runtime"])
        self.assertFalse(self.mock_target.exists(), "Target directory must not be created or applied")

        # Invoke wrapper: default plan-only mode must output PLAN_READY and not execute
        cmd = [str(wrapper), "runinprefix", "C:\\hello-x64.exe"]
        p = subprocess.run(cmd, cwd=LAB, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"Wrapper invocation failed: {p.stderr}")
        data = json.loads(p.stdout)
        self.assertEqual(data["status"], "PLAN_READY")
        self.assertFalse(data["execution_performed"])
        self.assertIn("hello-x64.exe", " ".join(data["argv"]))

    def test_explicit_execute_runtime_activation(self):
        """Passing execute_runtime=True activates execution mode in candidate wrapper config."""
        res = prepare_runtime_tool(self.candidate_out, self.mock_target, execute_runtime=True)
        self.assertEqual(res["applied"], False)
        self.assertEqual(res["execute_runtime"], True)

        plan_data = json.loads((self.candidate_out / "install-plan.json").read_text())
        self.assertTrue(plan_data["execute_runtime"])
        self.assertFalse(plan_data["applied"])

    def test_unsupported_steam_verb_rejected(self):
        """Passing an unrecognized Steam verb must exit non-zero and refuse execution."""
        prepare_runtime_tool(self.candidate_out, self.mock_target)
        wrapper = self.candidate_out / "proton-wrapper.sh"

        cmd = [str(wrapper), "invalid_unsupported_verb", "C:\\game.exe"]
        p = subprocess.run(cmd, cwd=LAB, capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("unsupported", p.stderr.lower())

    def test_argument_boundary_preservation(self):
        """Spaces, Unicode, percent signs, and leading dashes must be preserved verbatim in argv."""
        prepare_runtime_tool(self.candidate_out, self.mock_target)
        wrapper = self.candidate_out / "proton-wrapper.sh"

        target_args = [
            "runinprefix",
            "C:\\Games\\黑神话 悟空\\game.exe",
            "-option%name",
            "--custom-flag=val with spaces",
            "--",
            "-game_flag",
        ]
        cmd = [str(wrapper)] + target_args
        p = subprocess.run(cmd, cwd=LAB, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"Wrapper failed: {p.stderr}")
        data = json.loads(p.stdout)
        self.assertEqual(data["status"], "PLAN_READY")

        plan_argv = data["argv"]
        self.assertIn("C:\\Games\\黑神话 悟空\\game.exe", plan_argv)
        self.assertIn("-option%name", plan_argv)
        self.assertIn("--custom-flag=val with spaces", plan_argv)
        self.assertIn("-game_flag", plan_argv)

    def test_shell_metacharacters_not_expanded(self):
        """Shell metacharacters like $USER, *.*, ;, & must remain literal strings."""
        prepare_runtime_tool(self.candidate_out, self.mock_target)
        wrapper = self.candidate_out / "proton-wrapper.sh"

        raw_args = ["runinprefix", "C:\\app.exe", "$USER", "*.*", "; echo evil", "&& rm -rf"]
        cmd = [str(wrapper)] + raw_args
        p = subprocess.run(cmd, cwd=LAB, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"Wrapper failed: {p.stderr}")
        data = json.loads(p.stdout)
        self.assertEqual(data["status"], "PLAN_READY")

        plan_argv = data["argv"]
        self.assertIn("$USER", plan_argv)
        self.assertIn("*.*", plan_argv)
        self.assertIn("; echo evil", plan_argv)
        self.assertIn("&& rm -rf", plan_argv)

    def test_malicious_env_cannot_override_lab_prefix(self):
        """Caller setting WINEPREFIX or LD_PRELOAD in environment cannot override fixed lab prefix."""
        prepare_runtime_tool(self.candidate_out, self.mock_target)
        wrapper = self.candidate_out / "proton-wrapper.sh"

        malicious_env = os.environ.copy()
        malicious_env["WINEPREFIX"] = "/tmp/evil_external_prefix"
        malicious_env["LD_PRELOAD"] = "/tmp/evil.so"
        malicious_env["STEAM_COMPAT_DATA_PATH"] = "/tmp/evil_data"

        cmd = [str(wrapper), "runinprefix", "C:\\hello-x64.exe"]
        p = subprocess.run(cmd, cwd=LAB, env=malicious_env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"Wrapper failed: {p.stderr}")
        data = json.loads(p.stdout)
        self.assertEqual(data["status"], "PLAN_READY")

        # The plan's WINEPREFIX must remain strictly the lab prefix
        self.assertIn("steam-shaped", data["env"]["WINEPREFIX"])
        self.assertNotIn("/tmp/evil", data["env"]["WINEPREFIX"])

    def test_wrapper_invoked_from_outside_lab_cwd(self):
        """Steam or user launches wrapper from an external directory (e.g. /tmp).
        Wrapper must not depend on cwd and must execute successfully."""
        prepare_runtime_tool(self.candidate_out, self.mock_target)
        wrapper = self.candidate_out / "proton-wrapper.sh"

        cmd = [str(wrapper), "runinprefix", "C:\\hello-x64.exe"]
        p = subprocess.run(cmd, cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"Wrapper failed from /tmp cwd: {p.stderr}")
        data = json.loads(p.stdout)
        self.assertEqual(data["status"], "PLAN_READY")

    def test_candidate_directory_with_shell_metacharacters(self):
        """Candidate directory path containing $() or quotes must not be expanded by wrapper shell."""
        tricky_dir = self.test_dir / "dir with $(echo evil) and 'quotes'"
        prepare_runtime_tool(tricky_dir, self.mock_target)
        wrapper = tricky_dir / "proton-wrapper.sh"

        cmd = [str(wrapper), "runinprefix", "C:\\hello-x64.exe"]
        p = subprocess.run(cmd, cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"Wrapper failed with tricky path: {p.stderr}")
        data = json.loads(p.stdout)
        self.assertEqual(data["status"], "PLAN_READY")

    def test_frozen_hash_mismatch_blocks_execution_with_exit_20(self):
        """If config.json recorded hash differs from actual elfuse candidate binary,
        wrapper execution must be BLOCKED and exit with returncode 20 without running."""
        prepare_runtime_tool(self.candidate_out, self.mock_target, execute_runtime=True)
        config_file = self.candidate_out / "config.json"
        cfg = json.loads(config_file.read_text())
        # Corrupt the expected hash
        cfg["elfuse_sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
        config_file.write_text(json.dumps(cfg, indent=2))

        wrapper = self.candidate_out / "proton-wrapper.sh"
        cmd = [str(wrapper), "runinprefix", "C:\\hello-x64.exe"]
        p = subprocess.run(cmd, cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(p.returncode, 20, f"Expected exit 20, got {p.returncode}: {p.stdout} / {p.stderr}")
        data = json.loads(p.stdout)
        self.assertEqual(data["status"], "BLOCKED")
        self.assertIn("mismatch", data["reason"].lower())
        self.assertFalse(data.get("execution_performed", True))


    def test_guest_env_injected_into_elfuse_argv(self):
        """guest_env configured in prepare_runtime_tool is injected into elfuse --env arguments."""
        custom_guest_env = {
            "LD_LIBRARY_PATH": "/usr/local/guest_lib",
            "TEST_VAR": "test_val"
        }
        prepare_runtime_tool(
            self.candidate_out,
            self.mock_target,
            execute_runtime=False,
            guest_env=custom_guest_env
        )
        wrapper = self.candidate_out / "proton-wrapper.sh"
        cmd = [str(wrapper), "runinprefix", "C:\\hello-x64.exe"]
        p = subprocess.run(cmd, cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"Wrapper failed: {p.stderr}")
        data = json.loads(p.stdout)
        self.assertEqual(data["status"], "PLAN_READY")

        argv = data["argv"]
        self.assertIn("--env", argv)
        self.assertIn("LD_LIBRARY_PATH=/usr/local/guest_lib", argv)
        self.assertIn("TEST_VAR=test_val", argv)

        # Injected immediately before the guest executable (linux_python)
        py_str = str(data["argv"][-3])
        py_idx = argv.index(py_str)
        env_idx = argv.index("LD_LIBRARY_PATH=/usr/local/guest_lib")
        self.assertLess(env_idx, py_idx)

    def test_guest_env_validation_rejects_invalid_inputs(self):
        """guest_env rejects non-dict, non-str keys/values, '=' in keys, and NUL bytes."""
        # Non-dict
        with self.assertRaises(TypeError):
            prepare_runtime_tool(self.candidate_out, self.mock_target, guest_env=["NOT_A_DICT"])
        with self.assertRaises(TypeError):
            prepare_runtime_tool(self.candidate_out, self.mock_target, guest_env="NOT_A_DICT")

        # Key containing '='
        with self.assertRaises(ValueError):
            prepare_runtime_tool(self.candidate_out, self.mock_target, guest_env={"FOO=BAR": "VAL"})

        # Key containing NUL
        with self.assertRaises(ValueError):
            prepare_runtime_tool(self.candidate_out, self.mock_target, guest_env={"FOO\0BAR": "VAL"})

        # Empty key
        with self.assertRaises(ValueError):
            prepare_runtime_tool(self.candidate_out, self.mock_target, guest_env={"": "VAL"})

        # Non-string key
        with self.assertRaises(TypeError):
            prepare_runtime_tool(self.candidate_out, self.mock_target, guest_env={123: "VAL"})

        # Non-string value
        with self.assertRaises(TypeError):
            prepare_runtime_tool(self.candidate_out, self.mock_target, guest_env={"FOO": 123})

        # Value containing NUL
        with self.assertRaises(ValueError):
            prepare_runtime_tool(self.candidate_out, self.mock_target, guest_env={"FOO": "VAL\0HERE"})

    def test_guest_env_bidirectional_isolation(self):
        """Verify host env does not receive guest_env, and host loader variables remain blocked."""
        custom_guest_env = {
            "LD_LIBRARY_PATH": "/guest/path/only"
        }
        prepare_runtime_tool(
            self.candidate_out,
            self.mock_target,
            execute_runtime=False,
            guest_env=custom_guest_env
        )
        wrapper = self.candidate_out / "proton-wrapper.sh"
        cmd = [str(wrapper), "runinprefix", "C:\\hello-x64.exe"]
        p = subprocess.run(cmd, cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        data = json.loads(p.stdout)

        # Host environment plan['env'] MUST NOT contain LD_LIBRARY_PATH
        self.assertNotIn("LD_LIBRARY_PATH", data["env"])

        # If user attempts to inject LD_LIBRARY_PATH into diagnostic_env (which runs on host), process.py blocks it
        cfg_file = self.candidate_out / "config.json"
        cfg = json.loads(cfg_file.read_text())
        cfg["execute_runtime"] = True
        cfg["diagnostic_env"] = {"LD_LIBRARY_PATH": "/illegal/host/path"}
        cfg_file.write_text(json.dumps(cfg, indent=2))

        p2 = subprocess.run(cmd, cwd="/tmp", capture_output=True, text=True)
        self.assertNotEqual(p2.returncode, 0)
        self.assertIn("Host loader injection variables are excluded", p2.stderr)

    def test_guest_env_preserves_spaces_and_unicode_verbatim(self):
        """guest_env preserves spaces, unicode, and path separators in values."""
        custom_guest_env = {
            "CUSTOM_GAME_PATH": "C:\\游戏测试\\path with spaces\\game.exe",
            "CUSTOM_FLAGS": "--flag1 --flag2=value"
        }
        prepare_runtime_tool(
            self.candidate_out,
            self.mock_target,
            execute_runtime=False,
            guest_env=custom_guest_env
        )
        wrapper = self.candidate_out / "proton-wrapper.sh"
        cmd = [str(wrapper), "runinprefix", "C:\\hello-x64.exe"]
        p = subprocess.run(cmd, cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        data = json.loads(p.stdout)
        argv = data["argv"]

        self.assertIn("CUSTOM_GAME_PATH=C:\\游戏测试\\path with spaces\\game.exe", argv)
        self.assertIn("CUSTOM_FLAGS=--flag1 --flag2=value", argv)

    def test_empty_guest_env_preserves_legacy_argv(self):
        """Empty guest_env ({}, None) preserves exact legacy argv without injecting --env."""
        out_none = self.test_dir / "out_none"
        prepare_runtime_tool(out_none, self.mock_target, execute_runtime=False, guest_env=None)
        cmd_none = [str(out_none / "proton-wrapper.sh"), "runinprefix", "C:\\hello-x64.exe"]
        p_none = subprocess.run(cmd_none, cwd="/tmp", capture_output=True, text=True)
        data_none = json.loads(p_none.stdout)

        out_empty = self.test_dir / "out_empty"
        prepare_runtime_tool(out_empty, self.mock_target, execute_runtime=False, guest_env={})
        cmd_empty = [str(out_empty / "proton-wrapper.sh"), "runinprefix", "C:\\hello-x64.exe"]
        p_empty = subprocess.run(cmd_empty, cwd="/tmp", capture_output=True, text=True)
        data_empty = json.loads(p_empty.stdout)

        self.assertEqual(data_none["argv"], data_empty["argv"])
        self.assertNotIn("--env", data_none["argv"])


    def test_guest_env_unmatched_interpreter_blocks_with_exit_20(self):
        """When guest_env is configured but linux_python cannot be located in argv, execution blocks with exit 20."""
        from unittest.mock import patch
        import io

        prepare_runtime_tool(
            self.candidate_out,
            self.mock_target,
            execute_runtime=False,
            guest_env={"MY_VAR": "val"}
        )
        cfg_file = self.candidate_out / "config.json"

        # Mock build_plan to return a plan where argv does not contain the configured linux_python
        with patch("scripts.backend.steam_handoff.build_plan") as mock_bp:
            mock_bp.return_value = {
                "status": "PLAN_READY",
                "argv": ["/mock/elfuse", "--user", "501:20", "/mock/unrelated_bin"],
                "env": {},
                "provenance": "MOCK"
            }
            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                rc = execute_from_config(cfg_file, ["runinprefix", "C:\\hello-x64.exe"])

            self.assertEqual(rc, 20)
            data = json.loads(stdout_capture.getvalue())
            self.assertEqual(data["status"], "BLOCKED")
            self.assertIn("not found in plan argv", data["reason"])
            self.assertFalse(data.get("execution_performed", True))


if __name__ == "__main__":
    unittest.main()
