import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid

LAB = Path(__file__).resolve().parents[2]
ADAPTER = LAB / 'scripts/runtime/session_v2_round2/wine_adapter.py'
SHIM_BIN = LAB / 'sources/p0-session-round2/wineserver_shim'

class WineAdapterMockTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ADAPTER.exists(), "wine_adapter.py missing")
        self.assertTrue(SHIM_BIN.exists(), "wineserver_shim binary missing")
        import importlib.util
        spec = importlib.util.spec_from_file_location('wine_adapter', ADAPTER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_prefix_materialization_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / 'template'
            template.mkdir()
            (template / 'drive_c/windows/system32').mkdir(parents=True)
            (template / 'dosdevices').mkdir(parents=True)

            # Create real bundle mock target files for fixture
            bundle = tmp_path / 'bundle'
            bundle.mkdir()
            real_k32 = bundle / 'kernel32.dll'
            real_k32.write_bytes(b'MZ_REAL_FIXTURE_K32')
            real_nt = bundle / 'ntdll.dll'
            real_nt.write_bytes(b'MZ_REAL_FIXTURE_NT')

            # Core DLLs as symlinks pointing to real targets
            (template / 'drive_c/windows/system32/kernel32.dll').symlink_to(real_k32)
            (template / 'drive_c/windows/system32/ntdll.dll').symlink_to(real_nt)
            # Normal broken symlink
            (template / 'drive_c/windows/system32/other.dll').symlink_to('/broken/path/other.dll')
            # Normal file
            (template / 'drive_c/windows/system.ini').write_text('[wine]\n')
            # Directory symlink
            (template / 'dir_symlink').symlink_to(bundle)

            target = tmp_path / 'run_prefix'
            work = tmp_path / 'run_work'
            work.mkdir()

            manifest = self.m.copy_and_materialize_prefix(template, target, work)
            self.assertTrue(target.exists())
            self.assertTrue((target / 'prefix_manifest.json').exists())
            # 2 core DLLs materialized as regular files with real content
            self.assertTrue((target / 'drive_c/windows/system32/kernel32.dll').is_file())
            self.assertFalse((target / 'drive_c/windows/system32/kernel32.dll').is_symlink())
            self.assertEqual((target / 'drive_c/windows/system32/kernel32.dll').read_bytes(), b'MZ_REAL_FIXTURE_K32')
            self.assertTrue((target / 'drive_c/windows/system32/ntdll.dll').is_file())
            self.assertFalse((target / 'drive_c/windows/system32/ntdll.dll').is_symlink())
            # Broken link preserved as symlink
            self.assertTrue((target / 'drive_c/windows/system32/other.dll').is_symlink())
            # Directory symlink preserved and audited in manifest
            self.assertTrue((target / 'dir_symlink').is_symlink())
            self.assertIn('dir_symlink', manifest['dir_symlinks'])
            # dosdevices c: and z:
            self.assertEqual(os.readlink(target / 'dosdevices/c:'), '../drive_c')
            self.assertEqual(os.readlink(target / 'dosdevices/z:'), '/work')
            self.assertEqual(manifest['symlinks']['dosdevices/z:'], '/work')

    def test_missing_core_dll_target_fails_closed(self):
        # Strict fail-closed: if core DLL target does not exist, must raise FileNotFoundError
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / 'template'
            template.mkdir()
            (template / 'drive_c/windows/system32').mkdir(parents=True)
            (template / 'drive_c/windows/system32/kernel32.dll').symlink_to('/nonexistent/bundle/kernel32.dll')
            target = tmp_path / 'run_prefix'
            work = tmp_path / 'run_work'
            work.mkdir()
            with self.assertRaises(FileNotFoundError):
                self.m.copy_and_materialize_prefix(template, target, work)

    def test_server_socket_path_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            prefix = tmp_path / 'pfx'
            prefix.mkdir()
            st = prefix.stat()
            expected_socket = tmp_path / f".wine-{os.getuid()}" / f"server-{st.st_dev:x}-{st.st_ino:x}" / "socket"
            calc_socket = self.m.compute_server_socket_path(tmp_path, prefix)
            self.assertEqual(calc_socket, expected_socket)

    def test_mock_wine_session_flow_success(self):
        root = Path('/tmp') / ('r2-pfx-' + uuid.uuid4().hex[:6])
        try:
            prefix = root / 'prefix'
            work = root / 'work'
            (root / 'tmp').mkdir(parents=True)
            prefix.mkdir(parents=True)
            work.mkdir(parents=True)

            res = self.m.run_foreground_wine_session(root, prefix, work, fake_mode=True)
            self.assertTrue(res['server_ready'])
            self.assertEqual(res['wine_exit'], 0)
            self.assertIsNone(res['error'])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_mock_server_not_ready_blocks_pe(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sock_path = tmp_path / 'nonexistent/socket'
            ready = self.m.probe_server_socket_ready(sock_path, timeout=0.2)
            self.assertFalse(ready)

if __name__ == '__main__':
    unittest.main(verbosity=2)
