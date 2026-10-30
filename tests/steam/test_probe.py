#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for scripts/steam/probe.py
Ensures offline Steam probe adapter satisfies:
- Unicode & space preservation in argv
- Sensitive argv redaction (tokens, passwords, tickets, URLs with auth)
- Strictly whitelisted Steam environment capture
- Exclusion of general env and sensitive Steam env vars (token/ticket/cookie/password/auth)
- JSON validity
- Atomic/exclusive log creation under concurrency without collisions
- Path and argument error handling with non-zero exit codes
- Never executing the target game or accessing network
- All temporary directories and logs strictly isolated inside lab directory
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Paths within lab
LAB_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_STEAM = LAB_ROOT / "scripts" / "steam"
PROBE_PY = SCRIPTS_STEAM / "probe.py"
LOGS_STEAM = LAB_ROOT / "logs" / "steam"


class TestSteamProbe(unittest.TestCase):
    def setUp(self):
        # Create an isolated test scratch directory inside lab's logs/steam
        self.test_scratch = LOGS_STEAM / f"test_scratch_{os.getpid()}_{id(self)}"
        self.test_scratch.mkdir(parents=True, exist_ok=True)
        self.log_dir = self.test_scratch / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.isolated_home = self.test_scratch / "home"
        self.isolated_home.mkdir(parents=True, exist_ok=True)
        self.isolated_tmp = self.test_scratch / "tmp"
        self.isolated_tmp.mkdir(parents=True, exist_ok=True)

        self.base_env = {
            "HOME": str(self.isolated_home),
            "TMPDIR": str(self.isolated_tmp),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": str(LAB_ROOT),
        }

    def tearDown(self):
        if self.test_scratch.exists():
            shutil.rmtree(self.test_scratch, ignore_errors=True)

    def run_probe(self, args, extra_env=None, check=False):
        cmd = [sys.executable, str(PROBE_PY)] + args
        env = dict(self.base_env)
        if extra_env:
            env.update(extra_env)

        proc = subprocess.run(
            cmd,
            env=env,
            cwd=str(self.test_scratch),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if check and proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr
            )
        return proc

    def test_unicode_and_spaces_in_argv(self):
        """Test that Chinese characters and spaces in parameters are preserved verbatim."""
        test_argv = [
            "waitforexitandrun",
            "/SteamLibrary/steamapps/common/黑神话 悟空/b1.exe",
            "-lang",
            "zh-CN",
            "带 空格 和 中文 的 启动参数",
        ]
        proc = self.run_probe(["--log-dir", str(self.log_dir)] + test_argv, check=True)
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        with open(log_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["argv"], test_argv)
        self.assertIn("黑神话 悟空", data["argv"][1])
        self.assertEqual(data["argv"][4], "带 空格 和 中文 的 启动参数")

    def test_sensitive_argv_redaction(self):
        """Test that sensitive tokens, passwords, tickets, and URLs are redacted."""
        sensitive_argv = [
            "/path/to/game.exe",
            "--connect-token=super_secret_token_12345",
            "-auth_ticket=ticket_xyz_999",
            "session_ticket=deadbeef_ticket_data",
            "password=P@ssw0rd!123",
            "--password",
            "secret_cleartext_password",
            "-token",
            "bearer_cleartext_token_abc",
            "--api-key=secret_api_key_456",
            "https://alice:supersecretpass@steamcommunity.com/login?token=sensitive_query_token&auth=secret_auth#anchor",
            "普通保留参数",
            "normal_arg_without_sensitive_words",
        ]
        proc = self.run_probe(
            ["--log-dir", str(self.log_dir)] + sensitive_argv, check=True
        )
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        content = log_files[0].read_text(encoding="utf-8")
        data = json.loads(content)

        # Ensure secrets do not appear anywhere in the raw content
        self.assertNotIn("super_secret_token_12345", content)
        self.assertNotIn("ticket_xyz_999", content)
        self.assertNotIn("deadbeef_ticket_data", content)
        self.assertNotIn("P@ssw0rd!123", content)
        self.assertNotIn("secret_cleartext_password", content)
        self.assertNotIn("bearer_cleartext_token_abc", content)
        self.assertNotIn("secret_api_key_456", content)
        self.assertNotIn("supersecretpass", content)
        self.assertNotIn("alice", content)
        self.assertNotIn("sensitive_query_token", content)
        self.assertNotIn("secret_auth", content)

        # Check expected redaction structure in data["argv"]
        logged_argv = data["argv"]
        self.assertEqual(logged_argv[0], "/path/to/game.exe")
        self.assertEqual(logged_argv[1], "--connect-token=[REDACTED]")
        self.assertEqual(logged_argv[2], "-auth_ticket=[REDACTED]")
        self.assertEqual(logged_argv[3], "session_ticket=[REDACTED]")
        self.assertEqual(logged_argv[4], "password=[REDACTED]")
        self.assertEqual(logged_argv[5], "--password")
        self.assertEqual(logged_argv[6], "[REDACTED]")
        self.assertEqual(logged_argv[7], "-token")
        self.assertEqual(logged_argv[8], "[REDACTED]")
        self.assertEqual(logged_argv[9], "--api-key=[REDACTED]")

        # Check redacted URL (userinfo entirely redacted)
        self.assertIn("https://[REDACTED]@steamcommunity.com", logged_argv[10])
        self.assertIn("token=[REDACTED]", logged_argv[10])
        self.assertIn("auth=[REDACTED]", logged_argv[10])

        # Normal arguments must remain intact
        self.assertEqual(logged_argv[11], "普通保留参数")
        self.assertEqual(logged_argv[12], "normal_arg_without_sensitive_words")

    def test_normal_argv_preserved(self):
        """Test that regular gaming and Steam command-line options are never falsely redacted."""
        normal_argv = [
            "/Applications/Steam.app/steamapps/common/TestGame/game.exe",
            "-novid",
            "-high",
            "-fullscreen",
            "-width",
            "1920",
            "-height",
            "1080",
            "+fps_max",
            "144",
            "+connect",
            "192.168.1.100:27015",
            "--game-option=fast_render",
            "normal_argument",
        ]
        proc = self.run_probe(["--log-dir", str(self.log_dir)] + normal_argv, check=True)
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        with open(log_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["argv"], normal_argv)

    def test_env_whitelist(self):
        """Test strict Steam environment whitelisting: only safe Steam keys captured, general env dropped."""
        custom_env = {
            "STEAM_COMPAT_CLIENT_INSTALL_PATH": "/Users/test/Library/Application Support/Steam",
            "STEAM_COMPAT_DATA_PATH": "/Users/test/SteamLibrary/steamapps/compatdata/12345",
            "STEAM_COMPAT_TOOL_PATHS": "/Users/test/Library/Application Support/Steam/compatibilitytools.d/probe",
            "STEAM_COMPAT_APP_ID": "12345",
            "SteamAppId": "12345",
            "SteamGameId": "12345",
            "STEAM_RUNTIME": "0",
            # General env vars that must NOT be logged
            "USER": "attacker",
            "SHELL": "/bin/zsh",
            "SSH_AUTH_SOCK": "/tmp/ssh.sock",
            "AWS_SECRET_ACCESS_KEY": "AKIAEXAMPLESECRET",
            "GITHUB_TOKEN": "ghp_examplesecrettoken",
            "MY_CUSTOM_VAR": "custom_value",
        }
        proc = self.run_probe(
            ["--log-dir", str(self.log_dir), "run", "game.exe"],
            extra_env=custom_env,
            check=True,
        )
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        with open(log_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        logged_env = data["env"]

        # Whitelisted safe vars are present
        self.assertEqual(
            logged_env.get("STEAM_COMPAT_CLIENT_INSTALL_PATH"),
            "/Users/test/Library/Application Support/Steam",
        )
        self.assertEqual(
            logged_env.get("STEAM_COMPAT_DATA_PATH"),
            "/Users/test/SteamLibrary/steamapps/compatdata/12345",
        )
        self.assertEqual(logged_env.get("STEAM_COMPAT_APP_ID"), "12345")
        self.assertEqual(logged_env.get("SteamAppId"), "12345")
        self.assertEqual(logged_env.get("SteamGameId"), "12345")
        self.assertEqual(logged_env.get("STEAM_RUNTIME"), "0")

        # General vars must NOT be present
        self.assertNotIn("USER", logged_env)
        self.assertNotIn("SHELL", logged_env)
        self.assertNotIn("SSH_AUTH_SOCK", logged_env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", logged_env)
        self.assertNotIn("GITHUB_TOKEN", logged_env)
        self.assertNotIn("MY_CUSTOM_VAR", logged_env)
        self.assertNotIn("PATH", logged_env)
        self.assertNotIn("HOME", logged_env)

    def test_env_sensitive_steam_vars_excluded(self):
        """Test that sensitive Steam-prefixed variables are excluded even if they look like Steam env."""
        sensitive_steam_env = {
            "STEAM_COMPAT_APP_ID": "54321",
            "STEAM_TOKEN": "steam_login_token_secret",
            "STEAM_AUTH_TICKET": "steam_auth_ticket_secret",
            "STEAM_PASSWORD": "steam_user_password_secret",
            "STEAM_COOKIE": "sessionid=12345; steamRememberLogin=true",
            "STEAM_AUTH_HEADER": "Bearer steam_auth_token",
            "STEAM_SECRET_KEY": "super_secret_steam_key",
        }
        proc = self.run_probe(
            ["--log-dir", str(self.log_dir), "run", "game.exe"],
            extra_env=sensitive_steam_env,
            check=True,
        )
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        raw_content = log_files[0].read_text(encoding="utf-8")
        data = json.loads(raw_content)
        logged_env = data["env"]

        # STEAM_COMPAT_APP_ID is safe and captured
        self.assertEqual(logged_env.get("STEAM_COMPAT_APP_ID"), "54321")

        # None of the sensitive keys or values must appear
        self.assertNotIn("STEAM_TOKEN", logged_env)
        self.assertNotIn("STEAM_AUTH_TICKET", logged_env)
        self.assertNotIn("STEAM_PASSWORD", logged_env)
        self.assertNotIn("STEAM_COOKIE", logged_env)
        self.assertNotIn("STEAM_AUTH_HEADER", logged_env)
        self.assertNotIn("STEAM_SECRET_KEY", logged_env)

        self.assertNotIn("steam_login_token_secret", raw_content)
        self.assertNotIn("steam_auth_ticket_secret", raw_content)
        self.assertNotIn("steam_user_password_secret", raw_content)

    def test_json_validity_and_schema(self):
        """Test that log file is strictly valid JSON containing timestamp, pid, cwd, argv, env."""
        proc = self.run_probe(
            ["--log-dir", str(self.log_dir), "run", "game.exe", "--test"], check=True
        )
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        with open(log_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("timestamp", data)
        self.assertIn("pid", data)
        self.assertIn("cwd", data)
        self.assertIn("argv", data)
        self.assertIn("env", data)

        self.assertIsInstance(data["timestamp"], str)
        self.assertIsInstance(data["pid"], int)
        self.assertIsInstance(data["cwd"], str)
        self.assertIsInstance(data["argv"], list)
        self.assertIsInstance(data["env"], dict)

    def test_exclusive_creation_and_concurrency(self):
        """Test that concurrent invocations create exclusive log files without collision or overwriting."""
        concurrency = 15
        args_list = [
            (["--log-dir", str(self.log_dir), "run", f"game_{i}.exe", f"arg_{i}"], i)
            for i in range(concurrency)
        ]

        def invoke(item):
            args, idx = item
            return self.run_probe(args)

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(executor.map(invoke, args_list))

        for res in results:
            self.assertEqual(res.returncode, 0, f"Process failed: {res.stderr}")

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(
            len(log_files),
            concurrency,
            f"Expected {concurrency} exclusive log files, found {len(log_files)}",
        )

        # Verify each log file is valid JSON and has distinct content
        game_names_found = set()
        for lf in log_files:
            with open(lf, "r", encoding="utf-8") as f:
                d = json.load(f)
            game_names_found.add(d["argv"][1])

        expected_game_names = {f"game_{i}.exe" for i in range(concurrency)}
        self.assertEqual(game_names_found, expected_game_names)

    def test_path_error_nonexistent_dir(self):
        """Test that invalid or non-existent log directory returns non-zero error."""
        nonexistent_dir = self.test_scratch / "no_such_dir" / "subdir"
        proc = self.run_probe(["--log-dir", str(nonexistent_dir), "run", "game.exe"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error", proc.stderr.lower())

    def test_path_error_missing_log_dir(self):
        """Test that omitting --log-dir returns non-zero error."""
        proc = self.run_probe(["run", "game.exe"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--log-dir", proc.stderr)

    def test_game_not_executed(self):
        """Test that probe only logs and NEVER executes the target executable or shell script."""
        marker_file = self.test_scratch / "marker_should_never_be_created.txt"
        if marker_file.exists():
            marker_file.unlink()

        # Create a malicious payload script that would create marker_file if executed
        payload_script = self.test_scratch / "payload.sh"
        payload_script.write_text(f"#!/bin/sh\ntouch '{marker_file}'\n", encoding="utf-8")
        payload_script.chmod(0o755)

        proc = self.run_probe(
            ["--log-dir", str(self.log_dir), str(payload_script), "some_arg"], check=True
        )
        self.assertEqual(proc.returncode, 0)

        # Assert marker file was NOT created!
        self.assertFalse(
            marker_file.exists(),
            "Security violation: probe executed the target command!",
        )

    def test_double_dash_delimiter_preserves_game_log_dir(self):
        """Test that '--' delimiter protects game-level --log-dir flags from being consumed by probe."""
        proc = self.run_probe(
            [
                "--log-dir",
                str(self.log_dir),
                "--",
                "game.exe",
                "--log-dir",
                "/game/internal/logs",
                "-option",
                "val",
            ],
            check=True,
        )
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        with open(log_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(
            data["argv"],
            ["game.exe", "--log-dir", "/game/internal/logs", "-option", "val"],
        )

    def test_auth_flag_with_dash_prefixed_secret(self):
        """Test that sensitive flags like --auth redacts values even if they start with a dash."""
        proc = self.run_probe(
            [
                "--log-dir",
                str(self.log_dir),
                "game.exe",
                "--auth",
                "-secret_dash_token_xyz",
            ],
            check=True,
        )
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        content = log_files[0].read_text(encoding="utf-8")
        self.assertNotIn("-secret_dash_token_xyz", content)

        data = json.loads(content)
        self.assertEqual(data["argv"], ["game.exe", "--auth", "[REDACTED]"])

    def test_authorization_headers(self):
        """Test that Authorization, Cookie, and sensitive HTTP headers are redacted."""
        proc = self.run_probe(
            [
                "--log-dir",
                str(self.log_dir),
                "game.exe",
                "-H",
                "Authorization: Bearer my_top_secret_bearer_token",
                "--header",
                "Cookie: sessionid=secret_session_data_123",
                "Authorization: Basic dXNlcjpwYXNz",
                "X-Api-Key: secret_api_key_header_789",
            ],
            check=True,
        )
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        content = log_files[0].read_text(encoding="utf-8")
        self.assertNotIn("my_top_secret_bearer_token", content)
        self.assertNotIn("secret_session_data_123", content)
        self.assertNotIn("dXNlcjpwYXNz", content)
        self.assertNotIn("secret_api_key_header_789", content)

        data = json.loads(content)
        logged_argv = data["argv"]
        self.assertEqual(logged_argv[0], "game.exe")
        self.assertEqual(logged_argv[1], "-H")
        self.assertIn("[REDACTED]", logged_argv[2])
        self.assertEqual(logged_argv[3], "--header")
        self.assertIn("[REDACTED]", logged_argv[4])
        self.assertIn("[REDACTED]", logged_argv[5])
        self.assertIn("[REDACTED]", logged_argv[6])

    def test_url_userinfo_fragment_and_encoded_keys(self):
        """Test URL sanitization: userinfo username/pass, fragment tokens, accessToken, and percent-encoded keys."""
        test_url1 = "https://alice:supersecretpass@example.com/oauth#accessToken=frag_secret_123&scope=read"
        test_url2 = "https://example.com/api?access%5Ftoken=encoded_secret_456&normalKey=preserveVal"
        proc = self.run_probe(
            ["--log-dir", str(self.log_dir), "game.exe", test_url1, test_url2],
            check=True,
        )
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        content = log_files[0].read_text(encoding="utf-8")
        self.assertNotIn("supersecretpass", content)
        self.assertNotIn("alice", content)  # userinfo username redacted
        self.assertNotIn("frag_secret_123", content)
        self.assertNotIn("encoded_secret_456", content)

        data = json.loads(content)
        url1_logged = data["argv"][1]
        url2_logged = data["argv"][2]

        self.assertIn("https://[REDACTED]@example.com/oauth", url1_logged)
        self.assertIn("accessToken=[REDACTED]", url1_logged)
        self.assertIn("scope=read", url1_logged)

        self.assertIn("access%5Ftoken=[REDACTED]", url2_logged)
        self.assertIn("normalKey=preserveVal", url2_logged)

    def test_file_permission_0600(self):
        """Test that created log file has secure 0600 file permissions."""
        proc = self.run_probe(
            ["--log-dir", str(self.log_dir), "game.exe"], check=True
        )
        self.assertEqual(proc.returncode, 0)

        log_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)
        mode = log_files[0].stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)



if __name__ == "__main__":
    unittest.main()
