import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT=pathlib.Path(__file__).resolve().parents[2]
LAUNCHER=ROOT/'scripts/p1_a_copy_round2/guest_launcher.py'
WRAPPER=ROOT/'scripts/p1_a_copy_round2/runner.py'
LOGS=ROOT/'logs/p1-a-copy-round2'

class GuestLauncherTests(unittest.TestCase):
    def test_launcher_help_and_direct_unsupervised_rejection(self):
        self.assertTrue(LAUNCHER.is_file(), 'guest_launcher.py missing')
        r = subprocess.run([sys.executable, '-B', str(LAUNCHER), '--help'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn('--scenario', r.stdout)
        # 确认 choices 严格仅限 smoke
        self.assertIn('{smoke}', r.stdout)

        # 未在 P0 监督组下启动必须立即报错
        r2 = subprocess.run([sys.executable, '-B', str(LAUNCHER), '--scenario', 'smoke'], capture_output=True, text=True)
        self.assertNotEqual(r2.returncode, 0)
        self.assertIn('P0 supervised session required', r2.stderr)

    def test_launcher_with_fake_host_controlled_run(self):
        label = 'g-lnch-' + uuid.uuid4().hex[:8]
        cmd = [
            sys.executable, str(WRAPPER),
            '--run-id', label,
            '--timeout', '8',
            '--outer-timeout', '12',
            '--',
            sys.executable, '-B', str(LAUNCHER),
            '--fixture-fake-host',
            '--scenario', 'smoke'
        ]
        res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(res.returncode, 0, res.stderr)
        root = LOGS / label
        receipt = json.loads((root / 'receipt.json').read_text())
        self.assertTrue(receipt['cleanup']['complete'])
        res_data = json.loads((root / 'work' / 'result.json').read_text())
        self.assertEqual(res_data['host_exit'], 0)
        # 确认短 socket 路径严格 < 104
        self.assertLess(len(res_data['sock_path'].encode('utf-8')), 104)

    def test_launcher_missing_host_fails(self):
        label = 'g-miss-' + uuid.uuid4().hex[:8]
        cmd = [
            sys.executable, str(WRAPPER),
            '--run-id', label,
            '--timeout', '8',
            '--outer-timeout', '12',
            '--',
            sys.executable, '-B', str(LAUNCHER),
            '--fixture-missing-host',
            '--scenario', 'smoke'
        ]
        res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(res.returncode, 0)

    def test_launcher_host_early_exit_fails(self):
        # 变异测试：host 瞬间退出触发 UNKNOWN 报错
        label = 'g-early-' + uuid.uuid4().hex[:8]
        cmd = [
            sys.executable, str(WRAPPER),
            '--run-id', label,
            '--timeout', '8',
            '--outer-timeout', '12',
            '--',
            sys.executable, '-B', str(LAUNCHER),
            '--fixture-host-early-exit',
            '--scenario', 'smoke'
        ]
        res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(res.returncode, 0)

if __name__=='__main__':unittest.main()
