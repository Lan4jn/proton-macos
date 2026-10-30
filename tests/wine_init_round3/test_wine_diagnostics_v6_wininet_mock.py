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
V6_LAUNCHER = LAB / 'scripts/runtime/wine_init_round3/wine_diagnostics_launcher_v6_wininet.py'

class WineDiagnosticsV6WininetMockTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(V6_LAUNCHER.exists(), "wine_diagnostics_launcher_v6_wininet.py missing")
        import importlib.util
        spec = importlib.util.spec_from_file_location('v6_launcher', V6_LAUNCHER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_v6_manifest_within_64mib_and_hashes(self):
        manifest = self.m.CLOSURE_R3_V6
        self.assertEqual(manifest['summary']['source_files_count'], 33)
        self.assertEqual(manifest['summary']['unique_source_count'], 33)
        self.assertTrue(manifest['summary']['fits_under_64mib_source_budget'])
        self.assertEqual(manifest['summary']['unique_source_bytes'], 60085476)
        self.assertEqual(manifest['summary']['deployed_target_selected_bytes'], 118380032)

        # 2 Wininet DLLs
        for w in ["wininet.dll", "mpr.dll"]:
            self.assertIn(w, manifest['dlls'])
            self.assertEqual(manifest['dlls'][w]['reason'], 'wineboot_internet_delay_load_dependency')

        # 4 OLE DLLs from v5
        for ole in ["ole32.dll", "combase.dll", "rpcrt4.dll", "coml2.dll"]:
            self.assertIn(ole, manifest['dlls'])

        # 6 PE DLLs from v4
        for pe in ["shell32.dll", "user32.dll", "gdi32.dll", "win32u.dll", "shcore.dll", "shlwapi.dll"]:
            self.assertIn(pe, manifest['dlls'])

        # 3 Unix libs
        self.assertIn('libstdc++.so.6', manifest['unix_libs'])
        self.assertIn('libm.so.6', manifest['unix_libs'])
        self.assertIn('libgcc_s.so.1', manifest['unix_libs'])

        # sortdefault.nls
        self.assertIn('sortdefault.nls', manifest['nls'])

    def test_setup_real_sysroot_v6_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_v6'
            manifest = self.m.setup_real_sysroot_v6(tmp_root)
            self.assertIn('r3_v6_wininet_dlls_deployed', manifest)

            # Check 2 Wininet DLLs in prefix system32
            for wininet_name in self.m.WININET_2_NAMES:
                p = tmp_root / f'prefix/drive_c/windows/system32/{wininet_name}'
                self.assertTrue(p.is_file(), f"{wininet_name} must be physical file in system32")
                self.assertFalse(p.is_symlink(), f"{wininet_name} must not be symlink")
                self.assertEqual(self.m.sha256_file(p), self.m.CLOSURE_R3_V6['dlls'][wininet_name]['sha256'])

            # Check 4 OLE DLLs in prefix system32
            for ole_name in ["ole32.dll", "combase.dll", "rpcrt4.dll", "coml2.dll"]:
                p = tmp_root / f'prefix/drive_c/windows/system32/{ole_name}'
                self.assertTrue(p.is_file())

            # Check 3 Unix libs in usr/lib
            for lib_name, info in self.m.CLOSURE_R3_V6['unix_libs'].items():
                p = tmp_root / info['target']
                self.assertTrue(p.is_file())

            # Check sortdefault in share and prefix
            self.assertTrue((tmp_root / 'wine/share/wine/nls/sortdefault.nls').is_file())

    def test_missing_wininet_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_v6_fail'
            fake_closure = json.loads(json.dumps(self.m.CLOSURE_R3_V6))
            fake_closure['dlls']['wininet.dll']['source'] = 'fixtures/runtime/nonexistent/wininet.dll'
            with patch.dict(self.m.CLOSURE_R3_V6, fake_closure):
                with self.assertRaises(FileNotFoundError):
                    self.m.setup_real_sysroot_v6(tmp_root)

    def test_mock_pipeline_v6_launcher_pass_at_43_from_non_repo_cwd(self):
        run_id = 'test-v6-mock-pass-' + uuid.uuid4().hex[:6]
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

            with patch.object(self.m, 'setup_real_sysroot_v6', return_value={'mock': True}) as spy_setup, \
                 patch.object(self.m.v5_base.v4_base.sort_base.diag_base.base_s3v2.base, 'probe_readiness', return_value={'status': 'READY'}), \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]), \
                 patch.object(self.m.v5_base.v4_base, 'setup_real_sysroot_combined', side_effect=spy_setup), \
                 patch('sys.argv', [str(V6_LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']):
                
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
