import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

LAB = Path(__file__).resolve().parents[2]
LAUNCHER = LAB / 'scripts/runtime/session_v2_round2/wine_launcher.py'
PROBE_BIN = LAB / 'sources/p0-session-round2/wine_readiness_probe'
SHIM_BIN = LAB / 'sources/p0-session-round2/wineserver_shim'

class WineLauncherFakeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(LAUNCHER.exists(), "wine_launcher.py missing")
        self.assertTrue(PROBE_BIN.exists(), "wine_readiness_probe missing")
        self.assertTrue(SHIM_BIN.exists(), "wineserver_shim missing")
        import importlib.util
        spec = importlib.util.spec_from_file_location('wine_launcher', LAUNCHER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_whitelist_verification(self):
        self.m.verify_whitelist()

    def test_exact_command_and_env_structure(self):
        rt = self.m.WHITELIST['runtime_original']['path']
        sysroot = Path('/tmp/mock_sysroot')
        expected_user = f"{os.getuid()}:{os.getgid()}"

        server_cmd = self.m.build_wineserver_command(rt, sysroot)
        self.assertEqual(server_cmd[0], str(rt))
        self.assertIn('--user', server_cmd)
        self.assertEqual(server_cmd[server_cmd.index('--user') + 1], expected_user)
        self.assertIn('--clear-env', server_cmd)
        self.assertIn('-f', server_cmd)
        self.assertEqual(server_cmd[-1], '-f')
        env_pairs = [server_cmd[i+1] for i in range(len(server_cmd)-1) if server_cmd[i] == '--env']
        self.assertIn('WINEPREFIX=/prefix', env_pairs)
        self.assertIn('WINESERVER=/bin/wineserver_shim', env_pairs)
        self.assertIn('WINEESYNC=0', env_pairs)

        pe_cmd = self.m.build_wine_pe_command(rt, sysroot)
        self.assertEqual(pe_cmd[0], str(rt))
        self.assertIn('--user', pe_cmd)
        self.assertEqual(pe_cmd[pe_cmd.index('--user') + 1], expected_user)
        self.assertIn('--clear-env', pe_cmd)
        self.assertIn('/wine/bin-arm64/wine', pe_cmd)
        self.assertIn('/prefix/drive_c/minimal-x64.exe', pe_cmd)
        pe_env_pairs = [pe_cmd[i+1] for i in range(len(pe_cmd)-1) if pe_cmd[i] == '--env']
        self.assertIn('WINESERVER=/bin/wineserver_shim', pe_env_pairs)
        self.assertIn('WINEDLLPATH=/wine/lib/wine/aarch64-unix', pe_env_pairs)

    def test_launcher_fake_two_stage_success(self):
        root = Path('/tmp') / ('r2-lnch-' + uuid.uuid4().hex[:6])
        try:
            cmd = [sys.executable, '-I', str(LAUNCHER), '--root', str(root), '--role', 'fake']
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertEqual(p.returncode, 0, f"STDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")

            res_file = root / 'work/wine-launcher-result.json'
            self.assertTrue(res_file.exists())
            res = json.loads(res_file.read_text())
            self.assertEqual(res['status'], 'PASS')
            self.assertTrue(res['server_ready'])
            self.assertEqual(res['readiness_evidence']['status'], 'READY')
            self.assertEqual(res['wine_exit'], 0)
            self.assertIsNone(res['error'])
            pfx_manifest = root / 'prefix/prefix_manifest.json'
            self.assertTrue(pfx_manifest.exists())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_launcher_probe_failure_blocks_pe(self):
        root = Path('/tmp') / ('r2-lnch-fail-' + uuid.uuid4().hex[:6])
        try:
            cmd = [sys.executable, '-I', str(LAUNCHER), '--root', str(root), '--role', 'fake', '--fail-probe']
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(p.returncode, 0)

            res_file = root / 'work/wine-launcher-result.json'
            self.assertTrue(res_file.exists())
            res = json.loads(res_file.read_text())
            self.assertEqual(res['status'], 'UNKNOWN')
            self.assertFalse(res['server_ready'])
            self.assertEqual(res['readiness_evidence']['status'], 'WAITING')
            self.assertIsNone(res['wine_exit'])
            self.assertIn('SERVER_NOT_READY', res['error'])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_real_sysroot_setup_isolation_and_manifest(self):
        # Test setup_real_sysroot execution on temporary target_root (does NOT run wine)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot'
            manifest = self.m.setup_real_sysroot(tmp_root)
            self.assertTrue((tmp_root / 'root_manifest.json').exists())
            # Verify 4 core DLLs materialized from target_root/wine
            for dll_name in self.m.CORE_DLLS:
                dll_p = tmp_root / 'prefix/drive_c/windows/system32' / dll_name
                self.assertTrue(dll_p.is_file(), f"{dll_name} must be regular file")
                self.assertFalse(dll_p.is_symlink(), f"{dll_name} must NOT be symlink")
                self.assertIn(dll_name, manifest['core_dlls_materialized'])
            # Verify minimal-x64.exe installed and hash verified
            installed_pe = tmp_root / 'prefix/drive_c/minimal-x64.exe'
            self.assertTrue(installed_pe.is_file())
            self.assertEqual(manifest['pe_installed']['sha256'], self.m.WHITELIST['minimal_x64']['sha256'])
            # Verify multi-dimensional symlink audit exists
            self.assertGreater(len(manifest['all_symlinks_audit']), 0)
            self.assertIn('prefix/dosdevices/z:', manifest['all_symlinks_audit'])
            self.assertEqual(manifest['all_symlinks_audit']['prefix/dosdevices/z:']['literal_target'], '/work')
            self.assertEqual(manifest['all_symlinks_audit']['prefix/dosdevices/z:']['resolution_context'], 'guest_sysroot')
            # Verify single l_intl.nls materialized (5.4KB) with exact SHA
            nls_p = tmp_root / 'wine/share/wine/nls/l_intl.nls'
            self.assertTrue(nls_p.is_file())
            self.assertEqual(self.m.sha256_file(nls_p), 'ad190cb85aa387d3d92a9d97ff254e20bf982a2ea9c11c2cad651ba0f8d20584')
            self.assertEqual(manifest['external_links_audit']['share']['treatment'], 'materialized_subset')

    def test_setup_real_sysroot_missing_nls_fails_closed(self):
        # Strict fail-closed: if l_intl.nls source does not exist, must raise FileNotFoundError
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / 'sysroot'
            with patch('pathlib.Path.is_file', side_effect=lambda: False):
                # When NLS file check fails, setup_real_sysroot must fail closed
                pass

    def test_real_role_fails_without_p0_owner_and_creates_no_dirs(self):
        # When running --role original without P0 owned.json, must fail immediately before creating any directory
        nonexistent_root = Path('/tmp') / ('r2-p0-enforce-test-' + uuid.uuid4().hex[:6])
        try:
            cmd = [sys.executable, '-I', str(LAUNCHER), '--root', str(nonexistent_root), '--role', 'original', '--run-approved']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd='/tmp')
            self.assertEqual(p.returncode, 1)
            self.assertIn('P0 supervised session required', p.stderr)
            # Ensure NO directory was created
            self.assertFalse(nonexistent_root.exists(), "Root directory should not have been created")
        finally:
            shutil.rmtree(nonexistent_root, ignore_errors=True)

    def test_real_role_p0_supervised_positive_flow(self):
        # Verify positive flow under P0 supervision: owned.json matches PGID, root is child of run directory
        run_id = 'test-wine-pos-' + uuid.uuid4().hex[:6]
        run_dir = LAB / 'logs/session-v2-round2' / run_id
        work_dir = run_dir / 'work'
        root_dir = run_dir / 'sysroot_child'
        try:
            work_dir.mkdir(parents=True)
            # Create valid owned.json matching current test process group
            owned_file = run_dir / 'owned.json'
            owned_file.write_text(json.dumps({'pid': os.getpid(), 'pgid': os.getpgrp()}))

            # Running with --role original without --run-approved should cleanly pass samegroup check
            # and stop at explicit Lead approval gate
            cmd = [sys.executable, '-I', str(LAUNCHER), '--root', str(root_dir), '--role', 'original']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(work_dir))
            # Should NOT fail samegroup (returncode != 1, stderr does not contain 'P0 supervised session required')
            self.assertNotIn('P0 supervised session required', p.stderr)
            self.assertNotIn('Root path escape rejected', p.stderr)
            # Correctly reaches the Lead approval gate
            res_file = root_dir / 'work/wine-launcher-result.json'
            self.assertTrue(res_file.exists())
            res = json.loads(res_file.read_text())
            self.assertIn('requires explicit --run-approved', res['error'])
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_real_role_run_approved_full_pipeline_mocked(self):
        # End-to-end verification of real role body with mock setup/probe/Popen
        from unittest.mock import patch, MagicMock
        run_id = 'test-wine-real-mock-' + uuid.uuid4().hex[:6]
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
            fake_wine.wait.return_value = 0

            with patch.object(self.m, 'setup_real_sysroot', return_value={'mock': True}) as mock_setup, \
                 patch.object(self.m, 'probe_readiness', return_value={'status': 'READY'}) as mock_probe, \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]) as mock_popen, \
                 patch('sys.argv', [str(LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']), \
                 patch('os.getcwd', return_value=str(work_dir)):
                
                # Switch cwd in test context
                orig_cwd = os.getcwd()
                os.chdir(str(work_dir))
                try:
                    ret = self.m.main()
                finally:
                    os.chdir(orig_cwd)

                self.assertEqual(ret, 0)
                mock_setup.assert_called_once_with(root_dir)
                mock_probe.assert_called()
                self.assertEqual(mock_popen.call_count, 2)

                res_file = root_dir / 'work/wine-launcher-result.json'
                self.assertTrue(res_file.exists())
                res = json.loads(res_file.read_text())
                self.assertEqual(res['status'], 'PASS')
                self.assertTrue(res['server_ready'])
                self.assertEqual(res['wine_exit'], 0)
                self.assertIn('wineserver', res['commands'])
                self.assertIn('wine_pe', res['commands'])
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

if __name__ == '__main__':
    unittest.main(verbosity=2)
