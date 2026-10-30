import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch, MagicMock

LAB = Path(__file__).resolve().parents[2]
FEX_PURE_LAUNCHER = LAB / 'scripts/runtime/wine_init_round3/wine_diagnostics_launcher_v3_fex_pure.py'

class WineDiagnosticsFexPureMockTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(FEX_PURE_LAUNCHER.exists(), "wine_diagnostics_launcher_v3_fex_pure.py missing")
        import importlib.util
        spec = importlib.util.spec_from_file_location('fex_pure_launcher', FEX_PURE_LAUNCHER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_fex_pure_manifest_within_32mib_and_hashes(self):
        manifest = self.m.CLOSURE_R3_FEX_PURE
        self.assertEqual(manifest['summary']['total_files'], 20)
        self.assertTrue(manifest['summary']['fits_under_32mib_budget'])
        self.assertEqual(manifest['summary']['total_bytes'], 27803632)
        self.assertIn('libstdc++.so.6', manifest['unix_libs'])
        self.assertIn('libm.so.6', manifest['unix_libs'])
        self.assertIn('libgcc_s.so.1', manifest['unix_libs'])
        # Verify sortdefault.nls is NOT in this pure FEX manifest
        self.assertNotIn('sortdefault.nls', manifest['nls'])

    def test_setup_real_sysroot_fex_pure_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_fex_pure'
            manifest = self.m.setup_real_sysroot_fex_pure(tmp_root)
            self.assertIn('r3_fex_unix_libs_deployed', manifest)

            # Check 3 libs in usr/lib
            for lib_name, info in self.m.CLOSURE_R3_FEX_PURE['unix_libs'].items():
                p = tmp_root / info['target']
                self.assertTrue(p.is_file(), f"{lib_name} must be in {info['target']}")
                self.assertEqual(self.m.sha256_file(p), info['sha256'])

            # Check sortdefault is NOT deployed
            self.assertFalse((tmp_root / 'wine/share/wine/nls/sortdefault.nls').exists())

    def test_mock_pipeline_fex_pure_launcher_pass_at_43(self):
        run_id = 'test-fex-pure-pass-' + uuid.uuid4().hex[:6]
        run_dir = LAB / 'logs/wine-init-round3' / run_id
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

            with patch.object(self.m, 'setup_real_sysroot_fex_pure', return_value={'mock': True}), \
                 patch.object(self.m.diag_base.base_s3v2.base, 'probe_readiness', return_value={'status': 'READY'}), \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]), \
                 patch('sys.argv', [str(FEX_PURE_LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']):
                
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
