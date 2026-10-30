#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Candidate VDF Generator (scripts/steam/candidate/generate_candidate.py)

Validates:
- Generation of compatibilitytool.vdf and toolmanifest.vdf with exact Valve syntax
- Inclusion of '-- %verb%' in commandline to preserve Steam verb and protect game flags
- Quoting and escaping of paths containing spaces
- Real Python executable verification
- Simulated Steam launch ensuring game-level --log-dir is not swallowed
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(LAB_ROOT))

from scripts.steam.candidate.generate_candidate import (
    generate_candidate_vdfs,
    format_vdf_arg,
    LAB_ROOT,
    PROBE_PY,
    LOG_DIR,
)


class TestCandidateVdfGenerator(unittest.TestCase):
    def setUp(self):
        self.test_scratch = (
            LAB_ROOT / "logs" / "steam" / f"test_candidate_scratch_{os.getpid()}_{id(self)}"
        )
        self.test_scratch.mkdir(parents=True, exist_ok=True)
        self.output_dir = self.test_scratch / "candidate_out"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.test_scratch.exists():
            shutil.rmtree(self.test_scratch, ignore_errors=True)

    def test_default_generation_structure(self):
        """Test default candidate generation creates files with required fields."""
        paths = generate_candidate_vdfs(output_dir=self.output_dir)

        compat_file = Path(paths["compatibilitytool_vdf"])
        manifest_file = Path(paths["toolmanifest_vdf"])

        self.assertTrue(compat_file.exists())
        self.assertTrue(manifest_file.exists())

        compat_content = compat_file.read_text(encoding="utf-8")
        manifest_content = manifest_file.read_text(encoding="utf-8")

        # Check compatibilitytool.vdf content
        self.assertIn('"compat_tools"', compat_content)
        self.assertIn('"proton_macos_probe"', compat_content)
        self.assertIn('"from_oslist"', compat_content)
        self.assertIn('"windows"', compat_content)
        self.assertIn('"to_oslist"', compat_content)
        self.assertIn('"macos"', compat_content)

        # Check toolmanifest.vdf content
        self.assertIn('"version" "2"', manifest_content)
        self.assertIn('"use_sessions" "1"', manifest_content)

        # Check commandline contains -- %verb%
        self.assertIn("-- %verb%", manifest_content)
        self.assertIn(str(PROBE_PY), manifest_content)
        self.assertIn("--log-dir", manifest_content)
        self.assertIn(str(LOG_DIR), manifest_content)

    def test_format_vdf_arg_quoting(self):
        """Test that paths with spaces or special characters are properly quoted and escaped."""
        plain_path = "/usr/bin/python3"
        space_path = "/Users/test/My Lab/scripts/probe.py"
        quote_space_path = '/Users/test/Dir "With" Quotes/logs'

        self.assertEqual(format_vdf_arg(plain_path), "/usr/bin/python3")
        self.assertEqual(format_vdf_arg(space_path), '\\"/Users/test/My Lab/scripts/probe.py\\"')
        self.assertEqual(
            format_vdf_arg(quote_space_path),
            '\\"/Users/test/Dir \\"With\\" Quotes/logs\\"',
        )

    def test_generation_with_spaces_in_paths(self):
        """Test candidate generation when paths contain spaces."""
        mock_py = Path("/Applications/My Python App/bin/python3")
        mock_probe = Path("/Users/test/My Projects/lab/probe.py")
        mock_log = Path("/Users/test/My Logs/steam")

        paths = generate_candidate_vdfs(
            output_dir=self.output_dir,
            python_exe=mock_py,
            probe_py=mock_probe,
            log_dir=mock_log,
        )

        manifest_content = Path(paths["toolmanifest_vdf"]).read_text(encoding="utf-8")

        # Escaped quotes should wrap the paths with spaces
        self.assertIn('\\"/Applications/My Python App/bin/python3\\"', manifest_content)
        self.assertIn('\\"/Users/test/My Projects/lab/probe.py\\"', manifest_content)
        self.assertIn('\\"/Users/test/My Logs/steam\\"', manifest_content)

        # -- %verb% must be preserved unquoted at the end of commandline
        self.assertTrue(manifest_content.strip().endswith('-- %verb%"\n  "version" "2"\n  "use_sessions" "1"\n}'))

    def test_python_executable_exists_and_usable(self):
        """Verify the Python interpreter used in candidate is existing and functional."""
        py_exe = Path(sys.executable).resolve()
        self.assertTrue(py_exe.exists(), f"Python executable does not exist: {py_exe}")
        self.assertTrue(os.access(str(py_exe), os.X_OK), f"Python executable is not executable: {py_exe}")

    def test_simulated_steam_verb_substitution_and_game_log_dir(self):
        """
        Simulate Steam executing commandline by substituting %verb% with
        'waitforexitandrun /path/to/game.exe --log-dir /game/internal/logs -fullscreen'.
        Verify probe captures the verb and game arguments without swallowing game's --log-dir.
        """
        paths = generate_candidate_vdfs(output_dir=self.output_dir)
        manifest_content = Path(paths["toolmanifest_vdf"]).read_text(encoding="utf-8")

        # Extract the commandline template from VDF
        # format: "commandline" "<cmd>"
        import re
        m = re.search(r'"commandline"\s+"(.*)"', manifest_content)
        self.assertIsNotNone(m, "commandline not found in toolmanifest.vdf")
        cmd_template = m.group(1)

        self.assertIn("%verb%", cmd_template)
        self.assertIn("-- %verb%", cmd_template)

        # Steam performs substitution of %verb% with:
        # verb + game args
        simulated_verb_and_game_args = [
            "waitforexitandrun",
            "/SteamLibrary/steamapps/common/Game/game.exe",
            "--log-dir",
            "/game/internal/logs",
            "-fullscreen",
            "-novid",
        ]

        # In real execution, probe.py is invoked with:
        # [python3, probe.py, --log-dir, <LOG_DIR>, --, waitforexitandrun, game.exe, --log-dir, ...]
        test_log_dir = self.test_scratch / "probe_logs"
        test_log_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(PROBE_PY),
            "--log-dir",
            str(test_log_dir),
            "--",
        ] + simulated_verb_and_game_args

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, f"Probe run failed: {proc.stderr}")

        log_files = list(test_log_dir.glob("*.json"))
        self.assertEqual(len(log_files), 1)

        with open(log_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        # Crucial assertion: waitforexitandrun (the Steam verb) is recorded,
        # AND game's --log-dir /game/internal/logs is preserved verbatim as game argument!
        self.assertEqual(data["argv"][0], "waitforexitandrun")
        self.assertEqual(data["argv"][1], "/SteamLibrary/steamapps/common/Game/game.exe")
        self.assertEqual(data["argv"][2], "--log-dir")
        self.assertEqual(data["argv"][3], "/game/internal/logs")
        self.assertEqual(data["argv"][4], "-fullscreen")
        self.assertEqual(data["argv"][5], "-novid")


if __name__ == "__main__":
    unittest.main()
