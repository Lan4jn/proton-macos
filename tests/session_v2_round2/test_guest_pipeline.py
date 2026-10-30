import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid
LAB=Path(__file__).resolve().parents[2]
BOOT=LAB/'scripts/runtime/session_v2_round2/guest_bootstrap.py'
class GuestPipeline(unittest.TestCase):
    def test_normal_and_outer_with_fake_runtime(self):
        self.assertTrue(BOOT.exists(),'guest bootstrap missing')
        for mode,exit_code in [('fake',0),('fake-outer',125)]:
            sentinel=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(60)'],start_new_session=True)
            try:
                run='gp-'+uuid.uuid4().hex
                p=subprocess.run([sys.executable,'-I',str(BOOT),'--'+mode,run],capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode,exit_code,p.stdout+p.stderr)
                root=LAB/'logs/session-v2-round2'/run
                receipt=json.loads((root/'receipt.json').read_text())
                pre=json.loads((root/'work/guest-pre.json').read_text())
                self.assertEqual(len(pre['snapshots'][0]),4)
                self.assertTrue(receipt['cleanup']['complete'])
                self.assertEqual(receipt['outer_timed_out'],mode=='fake-outer')
                self.assertTrue(sentinel.poll() is None)
                if mode=='fake':
                    out=json.loads((root/'work/guest-observer.json').read_text())
                    self.assertEqual(out['status'],'PASS')
                    self.assertEqual(out['runtime_exit'],0)
                    self.assertIn(b'runtime diagnostic', (root/'work/guest-raw.log').read_bytes())
                    self.assertTrue((root/'work/guest-raw.log').read_bytes().endswith(b'tail diagnostic\xff'))
                    self.assertEqual(out['stdout_coverage'],'complete')
                    self.assertEqual(len(out['raw_snapshots']),2)
                    self.assertGreater(len(out['raw_snapshots'][0]),len(out['snapshots'][0]))
            finally:
                if sentinel.poll() is None: sentinel.terminate()
                sentinel.wait(timeout=3)

    def test_real_mode_locked_without_token(self):
        run='lock-'+uuid.uuid4().hex
        p=subprocess.run([sys.executable,'-I',str(BOOT),'--real-original',run],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('guest execution locked',p.stderr)

    def test_invalid_run_id_rejected_before_mkdir(self):
        env = dict(os.environ, GUEST_LOCK_TOKEN='test_token')
        cases = [
            ('--real-original', '../escape_fixture', (LAB / 'sources/escape_fixture')),
            ('--real-original', '/tmp/abs_fixture', (Path('/tmp/abs_fixture'))),
            ('--real-original', '', None),
            ('--fake', '../escape_fake', (LAB / 'sources/escape_fake')),
            ('--fake', '/tmp/abs_fake', (Path('/tmp/abs_fake'))),
            ('--fake', '', None),
        ]
        for mode, bad_run, target_path in cases:
            p = subprocess.run([sys.executable, '-I', str(BOOT), mode, bad_run], env=env, capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0, f"Expected non-zero exit for {mode} {bad_run}")
            self.assertIn('Invalid run-id', p.stderr, f"Expected 'Invalid run-id' in stderr for {mode} {bad_run}")
            if target_path:
                self.assertFalse(target_path.exists(), f"Path {target_path} should not have been created")
        self.assertFalse((LAB / 'sources/p0-session-round2/guest-fixture-..').exists())
if __name__=='__main__': unittest.main(verbosity=2)
