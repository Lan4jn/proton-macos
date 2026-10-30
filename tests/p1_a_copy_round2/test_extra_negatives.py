import json
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT=pathlib.Path(__file__).resolve().parents[2]
WRAPPER=ROOT/'scripts/p1_a_copy_round2/runner.py'
EXTRA_SCRIPT=ROOT/'scripts/p1_a_copy_round2/scenario_extra.py'
LOGS=ROOT/'logs/p1-a-copy-round2'

class ExtraNegativeTests(unittest.TestCase):
    def test_missing_terminal_fails_latest(self):
        # 变异 host：只返回 99 个 terminal，应该触发 ValueError
        fake_code = '''
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
count = 0
while True:
    h,data=recv()
    if h['type']=='CLOSE':
        send(dict(v=1,type='ACK',ack_for='CLOSE',stage='CLOSED'));break
    count += 1
    a=dict(v=1,type='ACK',ack_for='FRAME',sid=1,gen=1,seq=h['seq'],slot=0,crc32=h['crc32'])
    send(dict(a,stage='RECEIVED'))
    if count < 100:  # 故意漏发第 100 个 terminal
        send(dict(a,stage='CONSUMED',disposition='displayed',capture_match=True))
c.close();s.close()
'''
        with tempfile.NamedTemporaryFile(suffix='.py', mode='w') as f:
            f.write(fake_code); f.flush()
            label='neg-lat-'+uuid.uuid4().hex[:8]
            cmd=[sys.executable,str(WRAPPER),'--run-id',label,'--timeout','10','--outer-timeout','14',
                 '--',sys.executable,'-B',str(EXTRA_SCRIPT),'--fixture-host',f.name,'latest']
            result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=16)
            self.assertNotEqual(result.returncode,0)

    def test_stale_gen_not_rejected_fails_resize(self):
        # 变异 host：故意不对旧 gen=1 报错（正常返回 ACK），此时 scenario_extra 必须断言失败（预期 host 报错）
        fake_code = '''
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
# seq 1
h,_=recv()
a=dict(v=1,type='ACK',ack_for='FRAME',sid=1,gen=1,seq=1,slot=0,crc32=h['crc32'])
send(dict(a,stage='RECEIVED'));send(dict(a,stage='CONSUMED',disposition='displayed',capture_match=True))
# RESIZE
recv();send(dict(v=1,type='ACK',ack_for='RESIZE',stage='CONFIGURED',sid=1,gen=2))
# seq 2
h,_=recv()
a=dict(v=1,type='ACK',ack_for='FRAME',sid=1,gen=2,seq=2,slot=0,crc32=h['crc32'])
send(dict(a,stage='RECEIVED'));send(dict(a,stage='CONSUMED',disposition='displayed',capture_match=True))
# seq 3 (旧gen=1): 错误地返回正常 ACK 而非 ERROR
h,_=recv()
a=dict(v=1,type='ACK',ack_for='FRAME',sid=1,gen=1,seq=3,slot=0,crc32=h['crc32'])
send(dict(a,stage='RECEIVED'));send(dict(a,stage='CONSUMED',disposition='displayed',capture_match=True))
c.close();s.close()
'''
        with tempfile.NamedTemporaryFile(suffix='.py', mode='w') as f:
            f.write(fake_code); f.flush()
            label='neg-res-'+uuid.uuid4().hex[:8]
            cmd=[sys.executable,str(WRAPPER),'--run-id',label,'--timeout','8','--outer-timeout','12',
                 '--',sys.executable,'-B',str(EXTRA_SCRIPT),'--fixture-host',f.name,'resize']
            result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)

    def test_handled_outside_busy_window_fails(self):
        # 变异 host：立即返回 HANDLED，在 busy_begin 之前就被接收到，断言失败
        fake_code = '''
import json, socket, struct, sys, time
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
a=dict(v=1,type='ACK',ack_for='FRAME',sid=1,gen=1,seq=1,slot=0,crc32=h['crc32'])
send(dict(a,stage='RECEIVED'));send(dict(a,stage='CONSUMED',disposition='displayed',capture_match=True))
recv() # ARM
send(dict(v=1,type='ACK',ack_for='ARM',stage='ARMED'))
# 故意不等待，瞬间发 HANDLED，使得 observed_ns 位于 busy_begin 之前
send(dict(v=1,type='ACK',ack_for='EVENT',stage='HANDLED',event='ui_event'))
c.close();s.close()
'''
        with tempfile.NamedTemporaryFile(suffix='.py', mode='w') as f:
            f.write(fake_code); f.flush()
            label='neg-busy-'+uuid.uuid4().hex[:8]
            cmd=[sys.executable,str(WRAPPER),'--run-id',label,'--timeout','8','--outer-timeout','12',
                 '--',sys.executable,'-B',str(EXTRA_SCRIPT),'--fixture-host',f.name,'busy']
            result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)

if __name__=='__main__':unittest.main()
