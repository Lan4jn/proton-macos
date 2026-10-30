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
SORT_LAUNCHER = LAB / 'scripts/runtime/wine_init_round3/wine_diagnostics_launcher_v2_sort.py'

class WineDiagnosticsSortMockTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SORT_LAUNCHER.exists(), "wine_diagnostics_launcher_v2_sort.py missing")
        import importlib.util
        spec = importlib.util.spec_from_file_location('sort_launcher', SORT_LAUNCHER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_sort_manifest_within_30mb_and_hashes(self):
        manifest = self.m.CLOSURE_R3_SORT
        self.assertEqual(manifest['summary']['total_files'], 18)
        self.assertTrue(manifest['summary']['fits_under_30mb_budget'])
        self.assertIn('sortdefault.nls', manifest['nls'])
        sort_info = manifest['nls']['sortdefault.nls']
        self.assertEqual(sort_info['sha256'], '2e58e6165d423c8764af40ebd30a9567e4ca710e230f93817e36df7bed3fd433')
        self.assertEqual(sort_info['bytes'], 3380468)

    def test_setup_real_sysroot_sort_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_sort'
            manifest = self.m.setup_real_sysroot_sort(tmp_root)
            self.assertIn('r3_sort_deployed', manifest)

            # Check sortdefault.nls in bundle wine/share/wine/nls/
            dst_bundle_sort = tmp_root / 'wine/share/wine/nls/sortdefault.nls'
            self.assertTrue(dst_bundle_sort.is_file())
            self.assertFalse(dst_bundle_sort.is_symlink())
            self.assertEqual(self.m.sha256_file(dst_bundle_sort), '2e58e6165d423c8764af40ebd30a9567e4ca710e230f93817e36df7bed3fd433')

            # Check sortdefault.nls in prefix globalization sorting
            dst_pfx_sort = tmp_root / 'prefix/drive_c/windows/globalization/sorting/sortdefault.nls'
            self.assertTrue(dst_pfx_sort.is_file())
            self.assertFalse(dst_pfx_sort.is_symlink())

    def test_mock_pipeline_sort_launcher_pass_at_43(self):
        run_id = 'test-sort-mock-pass-' + uuid.uuid4().hex[:6]
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

            with patch.object(self.m, 'setup_real_sysroot_sort', return_value={'mock': True}), \
                 patch.object(self.m.diag_base.base_s3v2.base, 'probe_readiness', return_value={'status': 'READY'}), \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]), \
                 patch('sys.argv', [str(SORT_LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']):
                
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
