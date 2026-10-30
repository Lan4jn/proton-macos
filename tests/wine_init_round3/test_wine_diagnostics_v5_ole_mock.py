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
V5_LAUNCHER = LAB / 'scripts/runtime/wine_init_round3/wine_diagnostics_launcher_v5_ole.py'

class WineDiagnosticsV5OleMockTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(V5_LAUNCHER.exists(), "wine_diagnostics_launcher_v5_ole.py missing")
        import importlib.util
        spec = importlib.util.spec_from_file_location('v5_launcher', V5_LAUNCHER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_v5_manifest_within_64mib_and_hashes(self):
        manifest = self.m.CLOSURE_R3_V5
        self.assertEqual(manifest['summary']['source_files_count'], 31)
        self.assertEqual(manifest['summary']['unique_source_count'], 31)
        self.assertTrue(manifest['summary']['fits_under_64mib_source_budget'])
        self.assertEqual(manifest['summary']['unique_source_bytes'], 57857252)
        self.assertEqual(manifest['summary']['deployed_target_selected_bytes'], 113923584)

        # 4 OLE DLLs
        for ole in ["ole32.dll", "combase.dll", "rpcrt4.dll", "coml2.dll"]:
            self.assertIn(ole, manifest['dlls'])
            self.assertEqual(manifest['dlls'][ole]['reason'], 'shell32_ole_delay_load_dependency')

        # 6 PE DLLs from v4
        for pe in ["shell32.dll", "user32.dll", "gdi32.dll", "win32u.dll", "shcore.dll", "shlwapi.dll"]:
            self.assertIn(pe, manifest['dlls'])

        # 3 Unix libs
        self.assertIn('libstdc++.so.6', manifest['unix_libs'])
        self.assertIn('libm.so.6', manifest['unix_libs'])
        self.assertIn('libgcc_s.so.1', manifest['unix_libs'])

        # sortdefault.nls
        self.assertIn('sortdefault.nls', manifest['nls'])

    def test_setup_real_sysroot_v5_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_v5'
            manifest = self.m.setup_real_sysroot_v5(tmp_root)
            self.assertIn('r3_v5_ole_dlls_deployed', manifest)

            # Check 4 OLE DLLs in prefix system32
            for ole_name in self.m.OLE_4_NAMES:
                p = tmp_root / f'prefix/drive_c/windows/system32/{ole_name}'
                self.assertTrue(p.is_file(), f"{ole_name} must be physical file in system32")
                self.assertFalse(p.is_symlink(), f"{ole_name} must not be symlink")
                self.assertEqual(self.m.sha256_file(p), self.m.CLOSURE_R3_V5['dlls'][ole_name]['sha256'])

            # Check 3 Unix libs in usr/lib
            for lib_name, info in self.m.CLOSURE_R3_V5['unix_libs'].items():
                p = tmp_root / info['target']
                self.assertTrue(p.is_file())

            # Check sortdefault in share and prefix
            self.assertTrue((tmp_root / 'wine/share/wine/nls/sortdefault.nls').is_file())

    def test_missing_ole_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_v5_fail'
            fake_closure = json.loads(json.dumps(self.m.CLOSURE_R3_V5))
            fake_closure['dlls']['ole32.dll']['source'] = 'fixtures/runtime/nonexistent/ole32.dll'
            with patch.dict(self.m.CLOSURE_R3_V5, fake_closure):
                with self.assertRaises(FileNotFoundError):
                    self.m.setup_real_sysroot_v5(tmp_root)

    def test_mock_pipeline_v5_launcher_pass_at_43_from_non_repo_cwd(self):
        run_id = 'test-v5-mock-pass-' + uuid.uuid4().hex[:6]
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

            with patch.object(self.m, 'setup_real_sysroot_v5', return_value={'mock': True}) as spy_setup, \
                 patch.object(self.m.v4_base.sort_base.diag_base.base_s3v2.base, 'probe_readiness', return_value={'status': 'READY'}), \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]), \
                 patch.object(self.m.v4_base, 'setup_real_sysroot_combined', side_effect=spy_setup), \
                 patch('sys.argv', [str(V5_LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']):
                
                orig_cwd = os.getcwd()
                os.chdir(str(work_dir))
                try:
                    ret = self.m.main()
                finally:
                    os.chdir(orig_cwd)

                self.assertEqual(ret, 0)
                spy_setup.assert_called_once_with(root_dir)
                res_file = root_dir / 'work/wine-launcher-result.json'
                self.assertTrue(res_file.exists())
                res = json.loads(res_file.read_text())
                self.assertEqual(res['status'], 'PASS')
                self.assertEqual(res['wine_exit'], 43)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

if __name__ == '__main__':
    unittest.main(verbosity=2)
