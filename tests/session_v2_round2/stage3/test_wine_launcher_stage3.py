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
STAGE3_LAUNCHER = LAB / 'scripts/runtime/session_v2_round2/stage3/wine_launcher_stage3.py'

class WineLauncherStage3Tests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(STAGE3_LAUNCHER.exists(), "wine_launcher_stage3.py missing")
        import importlib.util
        spec = importlib.util.spec_from_file_location('stage3_launcher', STAGE3_LAUNCHER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_semantic_marker_classifier(self):
        # 43 is PASS (NtTerminateProcess)
        c43 = self.m.classify_stage3_wine_outcome(43)
        self.assertEqual(c43['status'], 'PASS')
        self.assertEqual(c43['semantic_marker'], 'REACHED_PE_ENTRY_NT_TERMINATE_43')

        # 29 is UNKNOWN (loader failure before entry)
        c29 = self.m.classify_stage3_wine_outcome(29)
        self.assertEqual(c29['status'], 'UNKNOWN')
        self.assertEqual(c29['semantic_marker'], 'LOADER_FAILURE_EXIT_29')

        # Other exits are UNKNOWN
        c_other = self.m.classify_stage3_wine_outcome(1)
        self.assertEqual(c_other['status'], 'UNKNOWN')

    def test_exact_commands_stage3_budget_and_env(self):
        rt = self.m.base.WHITELIST['runtime_original']['path']
        sysroot = Path('/tmp/mock_sysroot_stage3')
        expected_user = f"{os.getuid()}:{os.getgid()}"

        server_cmd = self.m.build_wineserver_command_stage3(rt, sysroot)
        self.assertIn('--user', server_cmd)
        self.assertEqual(server_cmd[server_cmd.index('--user') + 1], expected_user)
        self.assertIn('--timeout', server_cmd)
        self.assertEqual(server_cmd[server_cmd.index('--timeout') + 1], '60')

        pe_cmd = self.m.build_wine_pe_command_stage3(rt, sysroot)
        self.assertIn('--user', pe_cmd)
        self.assertEqual(pe_cmd[pe_cmd.index('--user') + 1], expected_user)
        self.assertIn('--timeout', pe_cmd)
        self.assertEqual(pe_cmd[pe_cmd.index('--timeout') + 1], '60')

    def test_real_sysroot_stage3_closure_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_stage3'
            manifest = self.m.setup_real_sysroot_stage3(tmp_root)
            self.assertTrue((tmp_root / 'root_manifest.json').exists())
            self.assertIn('stage3_closure_deployed', manifest)

            # 1. Check wineboot.exe physically in system32
            wb_p = tmp_root / 'prefix/drive_c/windows/system32/wineboot.exe'
            self.assertTrue(wb_p.is_file())
            self.assertFalse(wb_p.is_symlink())
            self.assertEqual(self.m.sha256_file(wb_p), self.m.CLOSURE['wineboot_exe']['sha256'])

            # 2. Check all 10 DLLs physically in system32
            for dll_name, info in self.m.CLOSURE['dlls'].items():
                p = tmp_root / f'prefix/drive_c/windows/system32/{dll_name}'
                self.assertTrue(p.is_file(), f"{dll_name} must be physical file in system32")
                self.assertFalse(p.is_symlink(), f"{dll_name} must NOT be broken symlink")
                self.assertEqual(self.m.sha256_file(p), info['sha256'])

            # 3. Check NLS tables physically in wine/share/wine/nls
            for nls_name, info in self.m.CLOSURE['nls'].items():
                p = tmp_root / f'wine/share/wine/nls/{nls_name}'
                self.assertTrue(p.is_file())
                self.assertEqual(self.m.sha256_file(p), info['sha256'])

    def test_missing_closure_source_fails_closed(self):
        # Strict fail-closed: if closure DLL or NLS source is missing, setup_real_sysroot_stage3 must raise FileNotFoundError
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_stage3_fail'
            fake_closure = json.loads(json.dumps(self.m.CLOSURE))
            fake_closure['dlls']['kernel32.dll']['source'] = '/nonexistent/path/kernel32.dll'
            with patch.dict(self.m.CLOSURE, fake_closure):
                with self.assertRaises(FileNotFoundError):
                    self.m.setup_real_sysroot_stage3(tmp_root)

    def test_wrong_closure_sha_fails_closed(self):
        # Strict fail-closed: if closure SHA mismatch, validate_closure_sources must raise FileNotFoundError or ValueError
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot_stage3_shafail'
            fake_closure = json.loads(json.dumps(self.m.CLOSURE))
            fake_closure['wineboot_exe']['sha256'] = '0000000000000000000000000000000000000000000000000000000000000000'
            with patch.dict(self.m.CLOSURE, fake_closure):
                with self.assertRaises((FileNotFoundError, ValueError)):
                    self.m.setup_real_sysroot_stage3(tmp_root)

    def test_real_role_stage3_mock_pipeline_pass_at_43_from_non_repo_cwd(self):
        # Full end-to-end real role mock from NON-REPO cwd with Python wait 60s
        run_id = 'test-s3-mock-pass-' + uuid.uuid4().hex[:6]
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
            fake_wine.wait.return_value = 43  # PE exit code 43 must be PASS

            with patch.object(self.m, 'setup_real_sysroot_stage3', return_value={'mock': True}), \
                 patch.object(self.m.base, 'probe_readiness', return_value={'status': 'READY'}), \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]), \
                 patch('sys.argv', [str(STAGE3_LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']):
                
                # Run from inside non-repo working directory (work_dir)
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
                self.assertEqual(res['stage3_classification']['status'], 'PASS')
                self.assertEqual(res['stage3_classification']['semantic_marker'], 'REACHED_PE_ENTRY_NT_TERMINATE_43')
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_real_role_stage3_mock_pipeline_unknown_at_29_from_non_repo_cwd(self):
        # Full end-to-end real role mock from NON-REPO cwd with wine_exit = 29 (UNKNOWN/failure before entry)
        run_id = 'test-s3-mock-fail-' + uuid.uuid4().hex[:6]
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
            fake_wine.wait.return_value = 29  # Loader exit code 29 must be UNKNOWN

            with patch.object(self.m, 'setup_real_sysroot_stage3', return_value={'mock': True}), \
                 patch.object(self.m.base, 'probe_readiness', return_value={'status': 'READY'}), \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]), \
                 patch('sys.argv', [str(STAGE3_LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']):
                
                orig_cwd = os.getcwd()
                os.chdir(str(work_dir))
                try:
                    ret = self.m.main()
                finally:
                    os.chdir(orig_cwd)

                self.assertEqual(ret, 1)
                res_file = root_dir / 'work/wine-launcher-result.json'
                self.assertTrue(res_file.exists())
                res = json.loads(res_file.read_text())
                self.assertEqual(res['status'], 'UNKNOWN')
                self.assertEqual(res['wine_exit'], 29)
                self.assertEqual(res['stage3_classification']['status'], 'UNKNOWN')
                self.assertEqual(res['stage3_classification']['semantic_marker'], 'LOADER_FAILURE_EXIT_29')
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_derived_role_argv_structure_and_sha_validation(self):
        # 1. Verify exact argv equivalence between original and derived roles
        rt_orig = self.m.base.WHITELIST['runtime_original']['path']
        rt_der = self.m.base.WHITELIST['runtime_derived']['path']
        sysroot = Path('/tmp/mock_sysroot')

        cmd_orig_srv = self.m.build_wineserver_command_stage3(rt_orig, sysroot)
        cmd_der_srv = self.m.build_wineserver_command_stage3(rt_der, sysroot)
        # Identical structure except the runtime binary itself
        self.assertEqual(cmd_orig_srv[1:], cmd_der_srv[1:])
        self.assertEqual(cmd_der_srv[0], str(rt_der))

        cmd_orig_pe = self.m.build_wine_pe_command_stage3(rt_orig, sysroot)
        cmd_der_pe = self.m.build_wine_pe_command_stage3(rt_der, sysroot)
        self.assertEqual(cmd_orig_pe[1:], cmd_der_pe[1:])
        self.assertEqual(cmd_der_pe[0], str(rt_der))

        # 2. Verify wrong derived SHA fails closed
        with patch.dict(self.m.base.WHITELIST['runtime_derived'], {'sha256': '0000000000000000000000000000000000000000000000000000000000000000'}):
            with self.assertRaises((ValueError, RuntimeError)):
                self.m.verify_chosen_runtime('derived')

if __name__ == '__main__':
    unittest.main(verbosity=2)
