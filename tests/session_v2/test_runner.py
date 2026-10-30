import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
import uuid

LAB = Path(__file__).resolve().parents[2]
RUNNER = LAB / 'scripts/runtime/session_v2/run.py'
LOGS = LAB / 'logs/session-v2'

class RunnerTests(unittest.TestCase):
    def invoke(self, code, *, inner=2, outer=6, extra=(), rid=None, inherited=None):
        rid = rid or 'test-' + uuid.uuid4().hex
        cmd = [sys.executable, '-I', str(RUNNER), '--run-id', rid,
               '--timeout', str(inner), '--outer-timeout', str(outer),
               '--module', 'fixture=' + str(Path(__file__).resolve()), *extra,
               '--', sys.executable, '-I', '-c', code]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=outer + 8,
                           env=inherited)
        receipt = LOGS / rid / 'receipt.json'
        self.assertTrue(receipt.exists(), f'missing receipt: {p.stderr}')
        return p, json.loads(receipt.read_text()), LOGS / rid

    def test_exit_and_hashes(self):
        p, r, d = self.invoke("import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(r['target_exit'], 7)
        self.assertEqual(r['runner_exit'], 1)
        self.assertFalse(r['inner_timed_out'])
        self.assertFalse(r['outer_timed_out'])
        self.assertEqual(r['artifacts']['stdout.log'], hashlib.sha256((d/'stdout.log').read_bytes()).hexdigest())
        self.assertEqual(r['modules']['fixture']['sha256'], hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.assertTrue(r['cleanup']['complete'])

    def test_refuses_existing_directory(self):
        rid = 'test-' + uuid.uuid4().hex
        p, r, d = self.invoke('pass', rid=rid)
        before = {str(f.relative_to(d)): hashlib.sha256(f.read_bytes()).hexdigest() for f in d.rglob('*') if f.is_file()}
        q = subprocess.run([sys.executable, '-I', str(RUNNER), '--run-id', rid,
                            '--', sys.executable, '-c', 'pass'], capture_output=True)
        self.assertEqual(q.returncode, 2)
        after = {str(f.relative_to(d)): hashlib.sha256(f.read_bytes()).hexdigest() for f in d.rglob('*') if f.is_file()}
        self.assertEqual(before, after)

    def test_inner_timeout_preserves_unrelated_sentinel(self):
        sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            p, r, _ = self.invoke('import time; time.sleep(60)', inner=.25)
            self.assertEqual(p.returncode, 124)
            self.assertTrue(r['inner_timed_out'])
            self.assertFalse(r['outer_timed_out'])
            self.assertIsNone(sentinel.poll())
            self.assertTrue(r['cleanup']['complete'])
            self.assertTrue(r['cleanup']['signals'])
            self.assertTrue(all(x['pgid'] == r['owned']['pgid'] for x in r['cleanup']['observed']))
            self.assertNotIn(sentinel.pid, [x['pid'] for x in r['cleanup']['observed']])
        finally:
            sentinel.terminate(); sentinel.wait(timeout=3)

    def test_outer_timeout_uses_stopped_worker_fixture(self):
        p, r, _ = self.invoke('import os, signal, time; os.kill(os.getppid(), signal.SIGSTOP); time.sleep(60)',
                              inner=10, outer=.5, extra=('--fixture-short-outer',))
        self.assertEqual(p.returncode, 125)
        self.assertTrue(r['outer_timed_out'])
        self.assertFalse(r['inner_timed_out'])
        self.assertTrue(r['cleanup']['complete'])

    def test_orphan_ignoring_term_is_cleaned(self):
        code = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print(123,flush=True); time.sleep(60)']); import time; time.sleep(.2)"
        p, r, _ = self.invoke(code)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(r['target_exit'], 0)
        self.assertTrue(r['cleanup']['complete'])
        self.assertGreaterEqual(len(r['cleanup']['observed']), 2)
        self.assertTrue(any(x['signal'] == 'SIGKILL' for x in r['cleanup']['signals']))

    def test_exec_failure_receipt(self):
        rid = 'test-' + uuid.uuid4().hex
        p = subprocess.run([sys.executable, '-I', str(RUNNER), '--run-id', rid, '--', '/missing/session-v2-executable'], capture_output=True, timeout=10)
        rpath = LOGS/rid/'receipt.json'
        self.assertTrue(rpath.exists())
        r = json.loads(rpath.read_text())
        self.assertEqual(p.returncode, 70)
        self.assertIsNone(r['target_exit'])
        self.assertIn('FileNotFoundError', r['error'])
        self.assertTrue(r['cleanup']['complete'])

    def test_parent_signal_cleans_owned_group(self):
        rid = 'test-' + uuid.uuid4().hex
        p = subprocess.Popen([sys.executable, '-I', str(RUNNER), '--run-id', rid,
                              '--timeout', '8', '--outer-timeout', '12', '--', sys.executable,
                              '-c', 'import time; print("ready",flush=True); time.sleep(60)'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic()+5
            while time.monotonic()<deadline:
                path = LOGS/rid/'stdout.log'
                if path.exists() and 'ready' in path.read_text(): break
                time.sleep(.02)
            else: self.fail('target readiness missing')
            p.send_signal(signal.SIGTERM)
            p.communicate(timeout=5)
            r = json.loads((LOGS/rid/'receipt.json').read_text())
            self.assertEqual(p.returncode, 143)
            self.assertTrue(r['cleanup']['complete'])
        finally:
            if p.poll() is None: p.terminate(); p.communicate(timeout=5)

    def test_worker_crash_is_not_timeout(self):
        p, r, _ = self.invoke('import os, signal, time; os.kill(os.getppid(), signal.SIGKILL); time.sleep(60)')
        self.assertEqual(p.returncode, 70)
        self.assertFalse(r['outer_timed_out'])
        self.assertIn('worker exited before result', r['error'])
        self.assertTrue(r['cleanup']['complete'])

    def test_initial_identity_snapshot_failure_aborts_before_exec(self):
        rid = 'test-' + uuid.uuid4().hex
        script = ("import importlib.util,sys; "
                  "s=importlib.util.spec_from_file_location('session_v2',sys.argv[1]); "
                  "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                  "m.snapshot=lambda: (_ for _ in ()).throw(RuntimeError('injected snapshot failure')); "
                  "sys.argv=[sys.argv[1], '--run-id',sys.argv[2], '--',sys.executable,'-c','print(123)']; "
                  "sys.exit(m.main())")
        sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            p = subprocess.run([sys.executable, '-I', '-c', script, str(RUNNER), rid], capture_output=True, timeout=8)
            self.assertIsNone(sentinel.poll())
        finally:
            sentinel.terminate(); sentinel.wait(timeout=3)
        ready = json.loads((LOGS/rid/'ready.json').read_text())
        with self.assertRaises(ProcessLookupError): os.kill(ready['pid'], 0)
        r = json.loads((LOGS/rid/'receipt.json').read_text())
        self.assertEqual(p.returncode, 70)
        self.assertIn('injected snapshot failure', r['error'])
        self.assertTrue(r['cleanup'] and r['cleanup']['complete'])
        self.assertTrue(r['cleanup']['pre_exec_aborted'])
        self.assertEqual(r['cleanup']['signals'], [])
        self.assertFalse(r['target_exit_observed'])
        self.assertIsNone(r['owned'])
        self.assertFalse((LOGS/rid/'stdout.log').exists())

    def test_environment_isolated(self):
        env = dict(os.environ, ELFUSE_DIAG_SESSION_SHARED='1', ELFUSE_INPROC_PRESENT='1')
        p, r, d = self.invoke("import os,json; print(json.dumps(dict(os.environ)))", inherited=env)
        childenv = json.loads((d/'stdout.log').read_text())
        self.assertNotIn('ELFUSE_DIAG_SESSION_SHARED', childenv)
        self.assertNotIn('ELFUSE_INPROC_PRESENT', childenv)
        self.assertEqual(childenv['WINEPREFIX'], str(d/'prefix'))
        self.assertEqual(p.returncode, 0)

if __name__ == '__main__': unittest.main(verbosity=2)
