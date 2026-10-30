import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/p1_a_copy_round2'))
WRAPPER=ROOT/'scripts/p1_a_copy_round2/runner.py'
LOGS=ROOT/'logs/p1-a-copy-round2'

class Governance(unittest.TestCase):
    def test_outer_timeout_cleans_owned_group_without_killing_sentinel(self):
        self.assertTrue(WRAPPER.is_file(),'round2 P0 parent wrapper missing')
        label='test-'+uuid.uuid4().hex[:10]
        sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        try:
            command=[sys.executable,str(WRAPPER),'--run-id',label,'--timeout','10',
                     '--outer-timeout','1','--fixture-short-outer','--',sys.executable,
                     '-c','import time;time.sleep(30)']
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=12)
            receipt=json.loads((LOGS/label/'receipt.json').read_text())
            self.assertEqual(result.returncode,125)
            self.assertTrue(receipt['outer_timed_out'])
            self.assertTrue(receipt['cleanup']['complete'])
            self.assertIsNone(sentinel.poll())
        finally:
            sentinel.terminate();sentinel.wait(timeout=3)

    def test_outer_timeout_reaps_probe_and_host_in_same_group(self):
        import os
        label='group-'+uuid.uuid4().hex[:10]
        root=LOGS/label
        code=('import os,pathlib,subprocess,sys,time;'
              'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);'
              'pathlib.Path(sys.argv[1]).write_text(str(os.getpid())+" "+str(p.pid)+" "+str(os.getpgrp()));'
              'time.sleep(30)')
        command=[sys.executable,str(WRAPPER),'--run-id',label,'--timeout','10',
                 '--outer-timeout','2','--fixture-short-outer','--',sys.executable,'-c',code,str(root/'roles')]
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=12)
        receipt=json.loads((root/'receipt.json').read_text())
        probe,host,pgid=map(int,(root/'roles').read_text().split())
        self.assertEqual(result.returncode,125)
        self.assertEqual(pgid,receipt['owned']['pgid'])
        self.assertTrue(receipt['cleanup']['complete'])
        self.assertTrue({probe,host}.issubset({row['pid'] for row in receipt['cleanup']['observed']}))
        for pid in (probe,host):
            check=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
            self.assertTrue(not check.stdout.strip() or check.stdout.strip().startswith('Z'))

    def test_inner_timeout_is_distinct_and_existing_run_rejected(self):
        label='inner-'+uuid.uuid4().hex[:10]
        cmd=[sys.executable,str(WRAPPER),'--run-id',label,'--timeout','.3',
             '--outer-timeout','4','--',sys.executable,'-c','import time;time.sleep(20)']
        result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=10)
        receipt=json.loads((LOGS/label/'receipt.json').read_text())
        self.assertEqual(result.returncode,124)
        self.assertTrue(receipt['inner_timed_out'])
        self.assertFalse(receipt['outer_timed_out'])
        self.assertTrue(receipt['cleanup']['complete'])
        before=(LOGS/label/'receipt.json').read_bytes()
        duplicate=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=5)
        self.assertNotEqual(duplicate.returncode,0)
        self.assertEqual((LOGS/label/'receipt.json').read_bytes(),before)

class HostProbe(unittest.TestCase):
    def test_probe_has_help_without_launching_host(self):
        path=ROOT/'scripts/p1_a_copy_round2/probe.py'
        self.assertTrue(path.is_file(),'round2 governed host probe missing')
        r=subprocess.run([sys.executable,'-B',str(path),'--help'],capture_output=True,text=True,timeout=5)
        self.assertEqual(r.returncode,0)
        self.assertIn('scenario',r.stdout)

    def test_probe_rejects_direct_unsupervised_launch(self):
        path=ROOT/'scripts/p1_a_copy_round2/probe.py'
        r=subprocess.run([sys.executable,'-B',str(path),'correctness'],capture_output=True,text=True,timeout=5)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('P0 supervised session required',r.stderr)

    def test_controlled_probe_completes_frame_with_fake_host(self):
        label='fake-'+uuid.uuid4().hex[:10]
        fake=ROOT/'tests/p1_a_copy_round2/fake_host.py'
        self.assertTrue(fake.is_file(),'fake host fixture missing')
        root=LOGS/label
        command=[sys.executable,str(WRAPPER),'--run-id',label,'--timeout','5','--outer-timeout','9',
                 '--',sys.executable,'-B',str(ROOT/'scripts/p1_a_copy_round2/probe.py'),
                 '--fixture-host',str(fake),'smoke']
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        receipt=json.loads((root/'receipt.json').read_text())
        self.assertTrue(receipt['cleanup']['complete'])
        self.assertEqual(json.loads((root/'work'/'result.json').read_text())['displayed'],1)

    def test_fixture_multiple_frames_preserve_unique_ack(self):
        label='multi-'+uuid.uuid4().hex[:10]
        fake=ROOT/'tests/p1_a_copy_round2/fake_host.py'
        cmd=[sys.executable,str(WRAPPER),'--run-id',label,'--timeout','8','--outer-timeout','12',
             '--',sys.executable,'-B',str(ROOT/'scripts/p1_a_copy_round2/probe.py'),
             '--fixture-host',str(fake),'--frames','3','smoke']
        result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        record=json.loads((LOGS/label/'work'/'result.json').read_text())
        self.assertEqual(record['displayed'],3)
        self.assertEqual([x['seq'] for x in record['terminal']], [1,2,3])

    def test_fixture_realtime_collects_all_terminal_ack(self):
        label='rt-'+uuid.uuid4().hex[:10]
        fake=ROOT/'tests/p1_a_copy_round2/fake_host.py'
        cmd=[sys.executable,str(WRAPPER),'--run-id',label,'--timeout','8','--outer-timeout','12',
             '--',sys.executable,'-B',str(ROOT/'scripts/p1_a_copy_round2/probe.py'),
             '--fixture-host',str(fake),'--frames','3','throughput']
        result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        record=json.loads((LOGS/label/'work'/'result.json').read_text())
        self.assertEqual(len(record['terminal']),3)
        self.assertEqual({x['seq'] for x in record['terminal']},{1,2,3})

    def test_fixture_rejects_invalid_slot_or_disposition(self):
        import subprocess, tempfile
        mutant_code = '''
import json, socket, struct, sys
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.bind(sys.argv[1]);s.listen(1);c,_=s.accept()
def exact(n):
    d=b''
    while len(d)<n:
        p=c.recv(n-len(d));if not p:raise EOFError();d+=p
    return d
def recv():
    t=struct.unpack('!I',exact(4))[0];jl=struct.unpack('!I',exact(4))[0]
    return json.loads(exact(jl)),exact(t-4-jl)
def send(h):
    r=json.dumps(h).encode();c.sendall(struct.pack('!II',len(r)+4,len(r))+r)
recv();send(dict(v=1,type='ACK',ack_for='CREATE',stage='CONFIGURED',sid=1,gen=1))
h,_=recv()
a=dict(v=1,type='ACK',ack_for='FRAME',sid=1,gen=1,seq=h['seq'],slot=99,crc32=h['crc32'])
send(dict(a,stage='RECEIVED'));send(dict(a,stage='CONSUMED',disposition='displayed',capture_match=True))
recv();send(dict(v=1,type='ACK',ack_for='CLOSE',stage='CLOSED'))
c.close();s.close()
'''
        with tempfile.NamedTemporaryFile(suffix='.py', mode='w') as f:
            f.write(mutant_code); f.flush()
            label='mut-'+uuid.uuid4().hex[:10]
            cmd=[sys.executable,str(WRAPPER),'--run-id',label,'--timeout','5','--outer-timeout','8',
                 '--',sys.executable,'-B',str(ROOT/'scripts/p1_a_copy_round2/probe.py'),
                 '--fixture-host',f.name,'smoke']
            result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)

class WireContract(unittest.TestCase):
    def test_packet_send_then_missing_ack_has_bounded_error(self):
        import importlib.util
        import socket
        import time
        self.assertIsNotNone(importlib.util.find_spec('wire'),'bounded wire client missing')
        import wire
        a,b=socket.socketpair()
        try:
            wire.send_packet(a,{'v':1,'type':'TEST'},b'hello',time.monotonic()+1)
            self.assertGreater(len(b.recv(1024)),5)
            with self.assertRaises(TimeoutError):wire.receive_packet(a,time.monotonic()+.2)
        finally:a.close();b.close()

    def test_connect_unix_nonblocking_and_deadline(self):
        import deadline_io
        import socket
        import time
        with tempfile.TemporaryDirectory() as d:
            path=str(pathlib.Path(d)/'s')
            listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            listener.bind(path);listener.listen(1)
            client=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            try:
                deadline_io.connect_unix(client,path,time.monotonic()+1)
                self.assertFalse(client.getblocking())
                accepted,_=listener.accept();accepted.close()
            finally:client.close();listener.close()

class RoleRegistration(unittest.TestCase):
    def test_child_role_registered_with_identity_and_parent_group(self):
        import importlib.util
        import os
        self.assertIsNotNone(importlib.util.find_spec('roles'),'role identity registry missing')
        import roles
        with tempfile.TemporaryDirectory() as d:
            child=roles.spawn('host',[sys.executable,'-c','import time;time.sleep(.4)'],pathlib.Path(d))
            try:
                record=json.loads((pathlib.Path(d)/'host.identity.json').read_text())
                self.assertEqual(record['pid'],child.pid)
                self.assertEqual(record['pgid'],os.getpgrp())
                self.assertTrue(record['identity'])
            finally:
                child.terminate();child.wait(timeout=3)

    def test_role_that_exits_before_identity_is_unknown(self):
        import roles
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            with patch.object(roles.subprocess,'run',side_effect=OSError('identity failed')):
                with self.assertRaises(OSError):
                    roles.spawn('host',[sys.executable,'-c','pass'],pathlib.Path(d))
            self.assertFalse((pathlib.Path(d)/'host.identity.json').exists())

class IODeadline(unittest.TestCase):
    def test_backpressure_hits_write_deadline(self):
        import importlib.util
        import socket
        import time
        self.assertIsNotNone(importlib.util.find_spec('deadline_io'),'nonblocking deadline I/O missing')
        import deadline_io
        left,right=socket.socketpair()
        try:
            left.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,4096)
            start=time.monotonic()
            with self.assertRaises(TimeoutError):
                deadline_io.send_all(left,b'x'*(8*1024*1024),start+.2)
            self.assertLess(time.monotonic()-start,2)
        finally:left.close();right.close()

    def test_partial_packet_no_eof_hits_read_deadline(self):
        import deadline_io
        import socket
        import time
        a,b=socket.socketpair()
        try:
            a.sendall(b'\x00\x00')
            start=time.monotonic()
            with self.assertRaises(TimeoutError):
                deadline_io.read_exact(b,4,start+.2)
            self.assertLess(time.monotonic()-start,2)
        finally:a.close();b.close()

    def test_no_ack_on_open_socket_hits_read_deadline(self):
        import deadline_io
        import socket
        import time
        a,b=socket.socketpair()
        try:
            with self.assertRaises(TimeoutError):deadline_io.read_exact(b,4,time.monotonic()+.2)
        finally:a.close();b.close()

if __name__=='__main__':unittest.main()
