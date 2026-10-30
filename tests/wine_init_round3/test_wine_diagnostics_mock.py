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
DIAG_LAUNCHER = LAB / 'scripts/runtime/wine_init_round3/wine_diagnostics_launcher.py'

class WineDiagnosticsLauncherMockTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DIAG_LAUNCHER.exists(), "wine_diagnostics_launcher.py missing")
        import importlib.util
        spec = importlib.util.spec_from_file_location('diag_launcher', DIAG_LAUNCHER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_single_variable_winedebug_injection_in_pe_command(self):
        rt = self.m.base_s3v2.base.WHITELIST['runtime_original']['path']
        sysroot = Path('/tmp/mock_sysroot')

        pe_cmd = self.m.build_wine_pe_command_r3(rt, sysroot)
        self.assertIn('--env', pe_cmd)
        env_pairs = [pe_cmd[i+1] for i in range(len(pe_cmd)-1) if pe_cmd[i] == '--env']
        self.assertIn('WINEDEBUG=+timestamp,+pid,+module,+seh,+loaddll', env_pairs)
        self.assertIn('WINEPREFIX=/prefix', env_pairs)
        self.assertIn('WINESERVER=/bin/wineserver_shim', env_pairs)
        self.assertIn('WINEESYNC=0', env_pairs)
        self.assertIn('PROTON_NO_ESYNC=1', env_pairs)

    def test_diagnostics_stderr_parser(self):
        sample_stderr = """
0030:trace:loaddll:load_builtin_dll Loaded L"C:\\windows\\system32\\ntdll.dll" at 0x7bc00000: builtin
0030:trace:module:MODULE_InitDLL (0x7bc00000 L"ntdll.dll", DLL_PROCESS_ATTACH, 0x1) - CALL
0030:trace:module:MODULE_InitDLL (0x7bc00000 L"ntdll.dll", DLL_PROCESS_ATTACH, 0x1) - RETURN 1
0030:trace:module:MODULE_InitDLL (0x7b400000 L"kernel32.dll", DLL_PROCESS_ATTACH, 0x1) - CALL
0030:err:module:loader_init Initializing system dll for L"C:\\windows\\system32\\wineboot.exe" failed, status c0000005
0028:err:seh:NtRaiseException Unhandled exception code c000001d flags 0 addr 0xdfffbc6610
"""
        findings = self.m.parse_diagnostics_from_stderr(sample_stderr)
        self.assertEqual(findings['trace_lines_count'], 2)
        self.assertIn('kernel32.dll', findings['last_call_module_candidate'])
        self.assertIn('wineboot.exe', findings['image_load_failure_log'])
        self.assertIn('c000001d', findings['exception_code_candidate'])
        self.assertIn('raw candidate traces', findings['limitations'])

    def test_stderr_cap_monitor_exceeded_terminates_proc(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_f = Path(tmp) / 'test_stderr.log'
            log_f.write_bytes(b'x' * 100)
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None

            monitor = self.m.StderrCapMonitor(log_f, soft_threshold_bytes=50, check_interval=0.05)
            monitor.start(mock_proc)
            time.sleep(0.15)
            monitor.stop()

            self.assertTrue(monitor.exceeded)
            self.assertEqual(monitor.observed_bytes, 100)
            mock_proc.terminate.assert_called_once()

    def test_real_role_diag_mock_pipeline_pass_at_43_from_non_repo_cwd(self):
        run_id = 'test-diag-mock-pass-' + uuid.uuid4().hex[:6]
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

            with patch.object(self.m.base_s3v2, 'setup_real_sysroot_stage3_v2', return_value={'mock': True}), \
                 patch.object(self.m.base_s3v2.base, 'probe_readiness', return_value={'status': 'READY'}), \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]), \
                 patch('sys.argv', [str(DIAG_LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']):
                
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
                self.assertIn('WINEDEBUG=+timestamp,+pid,+module,+seh,+loaddll', res['commands']['wine_pe'])
                self.assertEqual(res['stderr_cap']['soft_threshold_bytes'], 32 * 1024 * 1024)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_real_role_diag_mock_pipeline_unknown_at_29_from_non_repo_cwd(self):
        run_id = 'test-diag-mock-fail-' + uuid.uuid4().hex[:6]
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
            fake_wine.wait.return_value = 29

            with patch.object(self.m.base_s3v2, 'setup_real_sysroot_stage3_v2', return_value={'mock': True}), \
                 patch.object(self.m.base_s3v2.base, 'probe_readiness', return_value={'status': 'READY'}), \
                 patch('subprocess.Popen', side_effect=[fake_server, fake_wine]), \
                 patch('sys.argv', [str(DIAG_LAUNCHER), '--root', str(root_dir), '--role', 'original', '--run-approved']):
                
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
                self.assertEqual(res['r3_classification']['semantic_marker'], 'LOADER_FAILURE_EXIT_29')
                self.assertEqual(res['r3_classification']['reason'], 'PE entry execution unverified; Wine exit 29')
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

if __name__ == '__main__':
    unittest.main(verbosity=2)
