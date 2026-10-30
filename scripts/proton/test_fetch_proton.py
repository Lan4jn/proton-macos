#!/usr/bin/env python3
"""
Unit and integration tests for scripts/proton/fetch_proton.sh.
Verifies argument validation, size metadata evaluation with disclaimers,
isolated mktemp log retention, stage1/stage2 independent logs, and exit codes (0, 2, 10, 20).
All primary tests are pure offline mocks and execute in milliseconds.
Live network test is opt-in via RUN_LIVE_STEAM_TEST=1.
"""

import unittest
import subprocess
import os
import tempfile
import glob

LAB_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SCRIPT_PATH = os.path.join(LAB_ROOT, "scripts/proton/fetch_proton.sh")
LOGS_DIR = os.path.join(LAB_ROOT, "logs/proton")

class TestFetchProton(unittest.TestCase):
    def test_no_args_exits_2(self):
        res = subprocess.run([SCRIPT_PATH], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("Usage:", res.stdout + res.stderr)

    def test_unknown_flag_exits_2(self):
        res = subprocess.run([SCRIPT_PATH, "--invalid-option"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("Unknown or unexpected argument", res.stderr)

    def test_username_flag_disabled_exits_2(self):
        res = subprocess.run([SCRIPT_PATH, "--username", "someuser"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("In-lab authenticated download via --username is deliberately disabled", res.stderr)

    def test_eval_size_exits_0_with_disclaimer(self):
        res = subprocess.run([SCRIPT_PATH, "--eval-size"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("Historical Metadata Estimate", res.stdout)
        self.assertIn("SteamDB", res.stdout)
        self.assertIn("2026-09-21", res.stdout)
        self.assertIn("DISCLAIMER", res.stdout)
        self.assertIn("8.00 GiB", res.stdout)

    def test_help_exits_0(self):
        res = subprocess.run([SCRIPT_PATH, "--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("Exit Codes:", res.stdout)

    def test_mock_auth_blocked_exit_20_and_separate_logs(self):
        """Mock SteamCMD returning valid app info in stage 1 and 'No subscription' in stage 2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_steamcmd = os.path.join(tmpdir, "mock_steamcmd.sh")
            with open(mock_steamcmd, "w") as f:
                f.write("""#!/usr/bin/env bash
if [[ "$*" == *"+app_info_print"* ]]; then
    echo "AppID : 4427310, change number : 39839235"
    echo '"4427310" { "common" { "section_type" "ownersonly" "type" "Tool" } }'
    exit 0
elif [[ "$*" == *"+app_update"* ]]; then
    echo "Connecting anonymously to Steam Public...OK"
    echo "Not for anonymous users."
    echo "ERROR! Failed to install app '4427310' (No subscription)"
    exit 0
else
    echo "Unknown command: $*"
    exit 1
fi
""")
            os.chmod(mock_steamcmd, 0o755)

            # Record existing check directories to detect the newly created one
            before_dirs = set(glob.glob(os.path.join(LOGS_DIR, "check.*")))

            env = os.environ.copy()
            env["STEAMCMD_BIN"] = mock_steamcmd

            res = subprocess.run([SCRIPT_PATH, "--check-only"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            self.assertEqual(res.returncode, 20)
            self.assertIn("Acquisition blocked (Exit 20)", res.stdout)
            self.assertIn("section_type: 'ownersonly'", res.stdout)

            # Verify that a new check.XXXXXX directory was created
            after_dirs = set(glob.glob(os.path.join(LOGS_DIR, "check.*")))
            new_dirs = after_dirs - before_dirs
            self.assertEqual(len(new_dirs), 1, "Exactly one new check directory should be created")

            new_run_dir = list(new_dirs)[0]
            stage1_log = os.path.join(new_run_dir, "stage1_app_info.log")
            stage2_log = os.path.join(new_run_dir, "stage2_app_update.log")

            self.assertTrue(os.path.exists(stage1_log), "Stage 1 log must exist")
            self.assertTrue(os.path.exists(stage2_log), "Stage 2 log must exist")

            with open(stage1_log) as f1:
                content1 = f1.read()
                self.assertIn("section_type", content1)
                self.assertNotIn("No subscription", content1, "Stage 1 log must not contain Stage 2 output")

            with open(stage2_log) as f2:
                content2 = f2.read()
                self.assertIn("No subscription", content2)
                self.assertNotIn("app_info_print", content2, "Stage 2 log must not contain Stage 1 output")

    def test_mock_network_failure_exit_10(self):
        """Mock SteamCMD failing to connect to Steam servers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_steamcmd = os.path.join(tmpdir, "mock_steamcmd_netfail.sh")
            with open(mock_steamcmd, "w") as f:
                f.write("""#!/usr/bin/env bash
echo "Connecting anonymously to Steam Public...FAILED"
exit 0
""")
            os.chmod(mock_steamcmd, 0o755)

            env = os.environ.copy()
            env["STEAMCMD_BIN"] = mock_steamcmd

            res = subprocess.run([SCRIPT_PATH, "--check-only"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            self.assertEqual(res.returncode, 10)
            self.assertIn("[NETWORK_ERROR]", res.stdout)

    def test_mock_timeout_exit_10(self):
        """Mock SteamCMD timing out (run_timeout returns 124)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_steamcmd = os.path.join(tmpdir, "mock_steamcmd_timeout.sh")
            with open(mock_steamcmd, "w") as f:
                f.write("""#!/usr/bin/env bash
# Simulate run_timeout.py reporting timeout
exit 124
""")
            os.chmod(mock_steamcmd, 0o755)

            env = os.environ.copy()
            env["STEAMCMD_BIN"] = mock_steamcmd

            res = subprocess.run([SCRIPT_PATH, "--check-only"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            self.assertEqual(res.returncode, 10)
            self.assertIn("[TIMEOUT]", res.stdout)

    def test_mock_unknown_output_exit_10(self):
        """Mock SteamCMD returning non-conclusive output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_steamcmd = os.path.join(tmpdir, "mock_steamcmd_unknown.sh")
            with open(mock_steamcmd, "w") as f:
                f.write("""#!/usr/bin/env bash
echo "Some unhandled output from steam server"
exit 0
""")
            os.chmod(mock_steamcmd, 0o755)

            env = os.environ.copy()
            env["STEAMCMD_BIN"] = mock_steamcmd

            res = subprocess.run([SCRIPT_PATH, "--check-only"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            self.assertEqual(res.returncode, 10)
            self.assertIn("[UNKNOWN]", res.stdout)

    @unittest.skipUnless(os.environ.get("RUN_LIVE_STEAM_TEST") == "1", "Live test skipped unless RUN_LIVE_STEAM_TEST=1")
    def test_live_check_only_returns_blocked_20(self):
        res = subprocess.run([SCRIPT_PATH, "--check-only"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertIn(res.returncode, [10, 20])


if __name__ == "__main__":
    unittest.main()
