import json
import ast
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

LAB=Path(__file__).resolve().parents[2]
BOOT=LAB/'scripts/runtime/session_v2_round2/bootstrap.py'
WRAP=LAB/'scripts/runtime/session_v2_round2/guest_wrapper.py'
class FullPath(unittest.TestCase):
    def setUp(self):
        tree=ast.parse((LAB/'scripts/runtime/session_v2_round2/standin.py').read_text())
        calls=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertFalse(set(calls)&{'setsid','setpgid','execv','execve','execvp','execl','execlp','execle','execvpe'})
        self.sentinel=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(60)'], start_new_session=True)
        self.addCleanup(self.reap_sentinel)
    def reap_sentinel(self):
        alive=self.sentinel.poll() is None
        if alive: self.sentinel.terminate()
        self.sentinel.wait(timeout=3)
        self.assertTrue(alive, 'sentinel died during fixture')
        self.assertIsNotNone(self.sentinel.returncode)
    def test_pure_host_group_mismatch_is_rejected(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('wrapper', WRAP)
        sys.path.insert(0,str(WRAP.parent))
        m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        rows=[{'pid':1,'ppid':0,'pgid':1,'identity':'owner','state':'S'},
              {'pid':2,'ppid':1,'pgid':1,'identity':'wrapper','state':'S'},
              {'pid':3,'ppid':2,'pgid':1,'identity':'parent','state':'S'},
              {'pid':4,'ppid':3,'pgid':4,'identity':'child','state':'S'}]
        with self.assertRaisesRegex(ValueError,'group mismatch'):
            m.inspect(rows,rows[0],2,3)

    def test_bootstrap_wrapper_native_barriers_and_cleanup(self):
        self.assertTrue(BOOT.exists() and WRAP.exists(), 'bootstrap or wrapper missing')
        run='full-'+uuid.uuid4().hex
        p=subprocess.run([sys.executable,'-I',str(BOOT),'--fixture',run],capture_output=True,text=True,timeout=38)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        root=LAB/'logs/session-v2-round2'/run
        receipt=json.loads((root/'receipt.json').read_text())
        result=json.loads((root/'work/observer.json').read_text())
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['runtime_exit'],0)
        self.assertTrue(receipt['cleanup']['complete'])
        self.assertFalse(receipt['outer_timed_out'])
        self.assertEqual(len(result['snapshots']),2)
        self.assertEqual(result['guest_evidence'],'SIMULATED')
        self.assertNotEqual(result['events'][1]['pgid'],result['events'][2]['pgid'])
        self.assertNotEqual(result['events'][2]['pgid'],result['snapshots'][1][-1]['pgid'])
        self.assertEqual(result['snapshots'][0][-1]['pgid'],result['snapshots'][1][-1]['pgid'])
    def test_outer_watchdog_expires_stalled_observer(self):
        self.assertTrue(BOOT.exists() and WRAP.exists(), 'bootstrap or wrapper missing')
        run='outer-'+uuid.uuid4().hex
        p=subprocess.run([sys.executable,'-I',str(BOOT),'--stall-fixture',run],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,125,p.stdout+p.stderr)
        receipt=json.loads((LAB/'logs/session-v2-round2'/run/'receipt.json').read_text())
        self.assertTrue(receipt['outer_timed_out'])
        self.assertTrue(receipt['cleanup']['complete'])
        self.assertIsNone(receipt['target_exit'])
        pre=json.loads((LAB/'logs/session-v2-round2'/run/'work/observer-pre.json').read_text())
        self.assertEqual(len(pre['snapshots'][0]),4)
        self.assertEqual(pre['guest_evidence'],'SIMULATED')
if __name__=='__main__': unittest.main(verbosity=2)
