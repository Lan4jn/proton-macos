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
COMBINED_LAUNCHER = LAB / 'scripts/runtime/wine_init_round3/wine_diagnostics_launcher_v4_combined.py'

class WineDiagnosticsCombinedMockTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(COMBINED_LAUNCHER.exists(), "wine_diagnostics_launcher_v4_combined.py missing")
        import importlib.util
        spec = importlib.util.spec_from_file_location('combined_launcher', COMBINED_LAUNCHER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_combined_manifest_within_64mib_and_hashes(self):
        manifest = self.m.CLOSURE_R3_COMBINED
        self.assertEqual(manifest['summary']['source_files_count'], 27)
        self.assertEqual(manifest['summary']['unique_source_count'], 27)
        self.assertTrue(manifest['summary']['fits_under_64mib_source_budget'])
        self.assertEqual(manifest['summary']['unique_source_bytes'], 51369188)
        self.assertEqual(manifest['summary']['deployed_target_selected_bytes'], 100947456)

        # Budget policy check
        self.assertEqual(manifest['summary']['budget_policy']['authorized_logical_source_budget_bytes'], 67108864)

        # 6 PE DLLs
        for pe in ["shell32.dll", "user32.dll", "gdi32.dll", "win32u.dll", "shcore.dll", "shlwapi.dll"]:
            self.assertIn(pe, manifest['dlls'])
            self.assertEqual(manifest['dlls'][pe]['reason'], 'wineboot_shgetfolderpath_dependency')

        # 3 Unix libs
        self.assertIn('libstdc++.so.6', manifest['unix_libs'])
        self.assertIn('libm.so.6', manifest['unix_libs'])
        self.assertIn('libgcc_s.so.1', manifest['unix_libs'])

        # sortdefault.nls
        self.assertIn('sortdefault.nls', manifest['nls'])

    def test_setup_real_sysroot_combined_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_combined'
            manifest = self.m.setup_real_sysroot_combined(tmp_root)
            self.assertIn('r3_combined_deployed', manifest)

            # Check 3 Unix libs in usr/lib
            for lib_name, info in self.m.CLOSURE_R3_COMBINED['unix_libs'].items():
                p = tmp_root / info['target']
                self.assertTrue(p.is_file(), f"{lib_name} must be physical file in {info['target']}")
                self.assertEqual(self.m.sha256_file(p), info['sha256'])

            # Check 6 PE DLLs in prefix system32
            for pe_name in self.m.PE_6_NAMES:
                p = tmp_root / f'prefix/drive_c/windows/system32/{pe_name}'
                self.assertTrue(p.is_file(), f"{pe_name} must be physical file in system32")
                self.assertFalse(p.is_symlink(), f"{pe_name} must not be symlink")
                self.assertEqual(self.m.sha256_file(p), self.m.CLOSURE_R3_COMBINED['dlls'][pe_name]['sha256'])

            # Check sortdefault in share and prefix
            self.assertTrue((tmp_root / 'wine/share/wine/nls/sortdefault.nls').is_file())
            self.assertTrue((tmp_root / 'prefix/drive_c/windows/globalization/sorting/sortdefault.nls').is_file())

    def test_mock_pipeline_combined_launcher_pass_at_43(self):
        run_id = 'test-comb-mock-pass-' + uuid.uuid4().hex[:6]
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

            with patch.object(self.m, 'setup_real_sysroot_combined', return_value={'mock': True}), \
                 patch.object(self.m.sort_base.diag_base.base_s3v2.base, 'probe_readiness', return_value={'status': 'READY'}), \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]), \
                 patch('sys.argv', [str(COMBINED_LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']):
                
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
