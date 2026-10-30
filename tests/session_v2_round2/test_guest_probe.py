import pathlib
import subprocess
import tempfile
import time
import json
import unittest

LAB=pathlib.Path(__file__).resolve().parents[2]
class GuestProbeTests(unittest.TestCase):
    def test_native_probe_barriers_and_setsid(self):
        src=LAB/'sources/p0-session-round2/session_probe.c'
        with tempfile.TemporaryDirectory(dir=LAB/'logs/session-v2-round2') as tmp:
            root=pathlib.Path(tmp); binary=root/'native_probe'
            build=subprocess.run(['/usr/bin/clang','-std=c11','-Wall','-Wextra','-Werror',str(src),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            token='a'*32
            p=subprocess.Popen([str(binary),str(root),token],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                events=[]
                for phase in ('parent','pre','post','child_exit'):
                    line=p.stdout.readline(); self.assertTrue(line,phase)
                    event=json.loads(line); events.append(event)
                    self.assertEqual(event['phase'],phase)
                    self.assertEqual(event['token'],token)
                    if phase in ('pre','post'): (root/(phase+'.ack')).write_text(token)
                _,err=p.communicate(timeout=5)
                self.assertEqual(p.returncode,0,err)
                self.assertEqual(events[2]['result'],events[2]['pid'])
                self.assertEqual(events[2]['sid'],events[2]['pid'])
                self.assertEqual(events[3]['result'],0)
            finally:
                if p.poll() is None: p.kill(); p.communicate(timeout=3)

if __name__ == '__main__': unittest.main(verbosity=2)
