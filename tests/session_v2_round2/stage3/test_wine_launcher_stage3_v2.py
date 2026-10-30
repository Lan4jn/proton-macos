import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch, MagicMock

LAB = Path(__file__).resolve().parents[3]
STAGE3_V2_LAUNCHER = LAB / 'scripts/runtime/session_v2_round2/stage3/wine_launcher_stage3_v2.py'

class WineLauncherStage3V2Tests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(STAGE3_V2_LAUNCHER.exists(), "wine_launcher_stage3_v2.py missing")
        import importlib.util
        spec = importlib.util.spec_from_file_location('stage3_v2_launcher', STAGE3_V2_LAUNCHER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_semantic_marker_classifier_v2(self):
        # 43 is PASS
        c43 = self.m.classify_stage3_v2_wine_outcome(43)
        self.assertEqual(c43['status'], 'PASS')
        self.assertEqual(c43['semantic_marker'], 'REACHED_PE_ENTRY_NT_TERMINATE_43')

        # 29 is UNKNOWN per Lead instruction with exact reason string
        c29 = self.m.classify_stage3_v2_wine_outcome(29)
        self.assertEqual(c29['status'], 'UNKNOWN')
        self.assertEqual(c29['semantic_marker'], 'LOADER_FAILURE_EXIT_29')
        self.assertEqual(c29['reason'], 'PE entry execution unverified; Wine exit 29')

        # Other exits are UNKNOWN
        c_other = self.m.classify_stage3_v2_wine_outcome(1)
        self.assertEqual(c_other['status'], 'UNKNOWN')

    def test_v2_closure_manifest_loaded(self):
        self.assertTrue(self.m.CLOSURE_V2['summary']['fits_under_30mb_budget'])
        self.assertIn('cryptbase.dll', self.m.CLOSURE_V2['dlls'])
        self.assertIn('cryptsp.dll', self.m.CLOSURE_V2['dlls'])

    def test_real_sysroot_v2_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_stage3_v2'
            manifest = self.m.setup_real_sysroot_stage3_v2(tmp_root)
            self.assertTrue((tmp_root / 'root_manifest.json').exists())
            self.assertIn('stage3_v2_closure_deployed', manifest)

            # Check cryptbase.dll and cryptsp.dll physically in system32
            for d in ('cryptbase.dll', 'cryptsp.dll'):
                p = tmp_root / f'prefix/drive_c/windows/system32/{d}'
                self.assertTrue(p.is_file(), f"{d} must be physical file in system32")
                self.assertFalse(p.is_symlink())
                self.assertEqual(self.m.sha256_file(p), self.m.CLOSURE_V2['dlls'][d]['sha256'])

    def test_real_role_stage3_v2_mock_pipeline_pass_at_43(self):
        run_id = 'test-s3v2-mock-pass-' + uuid.uuid4().hex[:6]
        run_dir = LAB / 'logs/session-v2-round2' / run_id
        work_dir = run_dir / 'work'
        root_dir = run_dir / 'sysroot_child'
        try:
            work_dir.mkdir(parents=True)
            owned_file = run_dir / 'owned.json'
            owned_file.write_text(json.dumps({'pid': os.getpid(), 'pgid': os.getpgrp()}))

            fake_server = MagicMock()
            fake_server.poll.return_value = None
            fake_server.returncode = 0
            fake_wine = MagicMock()
            fake_wine.poll.return_value = None
            fake_wine.wait.return_value = 43

            with patch.object(self.m, 'setup_real_sysroot_stage3_v2', return_value={'mock': True}), \
                 patch.object(self.m.base, 'probe_readiness', return_value={'status': 'READY'}), \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]), \
                 patch('sys.argv', [str(STAGE3_V2_LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']):
                
                orig_cwd = os.getcwd()
                os.chdir(str(work_dir))
                try:
                    ret = self.m.main()
                finally:
                    os.chdir(orig_cwd)

                self.assertEqual(ret, 0)
                res_file = root_dir / 'work/wine-launcher-result.json'
                self.assertTrue(res_file.exists())
                res = json.loads(res_file.read_text())
                self.assertEqual(res['status'], 'PASS')
                self.assertEqual(res['wine_exit'], 43)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

if __name__ == '__main__':
    unittest.main(verbosity=2)
