#!/usr/bin/env python3
"""Supplementary scenarios for P1 A-copy round2 within P0-owned process group."""
import argparse
import ctypes
import hashlib
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
import zlib

import roles
import deadline_io
import wire

ROOT=pathlib.Path(__file__).resolve().parents[2]
HOST=ROOT/'logs/p1-a-copy-v2/run-4e2a63efe2f2/presenter'
HOST_SHA='b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb'
BUSY_SRC=ROOT/'sources/p1-a-copy-v2/busy.c'


def compile_busy_dylib(dest):
    subprocess.run(['clang','-O2','-dynamiclib',str(BUSY_SRC),'-o',str(dest)],check=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('scenario',metavar='scenario',choices=['latest','resize','busy','busy-close','disconnect'])
    p.add_argument('--fixture-host',default=None)
    args=p.parse_args()
    root=pathlib.Path.cwd()
    try:
        owner=json.loads((root.parent/'owned.json').read_text())
        if owner['pgid']!=os.getpgrp():raise ValueError('group mismatch')
    except (OSError,ValueError,KeyError):raise SystemExit('P0 supervised session required')

    override=args.fixture_host
    host=pathlib.Path(override) if override else HOST
    digest=hashlib.sha256(host.read_bytes()).hexdigest()
    if not override and digest!=HOST_SHA:raise SystemExit('frozen host SHA mismatch')

    sockpath=root/'s'
    if len(str(sockpath).encode())>=104:raise SystemExit('socket path too long')
    hz='10' if args.scenario=='latest' else '120'
    argv=([sys.executable,str(host)] if override else [str(host)])+[str(sockpath),hz]
    child=roles.spawn('host',argv,root)

    ps=subprocess.run(['/bin/ps','-p',str(os.getpid()),'-o','pid=,ppid=,pgid=,lstart='],capture_output=True,text=True,check=True)
    fields=ps.stdout.strip().split(None,3)
    if len(fields)!=4 or int(fields[2])!=owner['pgid']:raise RuntimeError('producer identity missing')
    (root/'producer.identity.json').write_text(json.dumps(dict(pid=int(fields[0]),ppid=int(fields[1]),pgid=int(fields[2]),identity=fields[3])))

    deadline=time.monotonic()+4
    while True:
        sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:deadline_io.connect_unix(sock,str(sockpath),deadline);break
        except (FileNotFoundError,ConnectionRefusedError):
            sock.close()
            if time.monotonic()>deadline:raise TimeoutError('host connect')
            time.sleep(.01)

    def send(header,data=b''):wire.send_packet(sock,header,data,time.monotonic()+3)
    def recv():
        h,data=wire.receive_packet(sock,time.monotonic()+4)
        if data:raise ValueError('unexpected ack payload')
        return h

    shape=dict(v=1,sid=1,gen=1,w=64,h=64,pitch=256,format='RGBA8')
    send(dict(shape,type='CREATE'))
    ack=recv()
    if ack.get('ack_for')!='CREATE' or ack.get('stage')!='CONFIGURED':raise ValueError('create ack')

    started=time.monotonic()
    result_data={}

    if args.scenario=='disconnect':
        sock.shutdown(socket.SHUT_RDWR)
        sock.close()
        rc=child.wait(timeout=4)
        result_data=dict(scenario=args.scenario,host_exit=rc,status='disconnected')

    elif args.scenario=='resize':
        # 4 帧测试：第1帧gen1，第2帧尝试发旧gen1必须被拒绝并报错断开；或正常resize后gen2
        # 按协议合同：seq1 gen1，seq2 发 RESIZE gen=2，接着seq3 gen=2正常绘制，seq4 尝试旧gen=1被拒
        terminals=[];received_acks=[]
        # seq 1: gen 1
        payload1=bytes((1,2,3,255))*(64*64);crc1=zlib.crc32(payload1)
        send(dict(shape,type='FRAME',seq=1,payload_bytes=len(payload1),crc32=crc1,capture=True),payload1)
        r1=recv();t1=recv()
        for a in (r1,t1):
            if a.get('sid')!=1 or a.get('gen')!=1 or a.get('seq')!=1 or a.get('crc32')!=crc1 or a.get('slot') not in (0,1):
                raise ValueError('resize seq 1 identity mismatch')
        if t1.get('disposition')!='displayed' or not t1.get('capture_match'):raise ValueError('display mismatch')
        received_acks.append(r1);terminals.append(t1)

        # RESIZE to gen 2 (32x48)
        send(dict(v=1,sid=1,gen=2,w=32,h=48,pitch=128,format='RGBA8',type='RESIZE'))
        rack=recv()
        if rack.get('ack_for')!='RESIZE' or rack.get('stage')!='CONFIGURED' or rack.get('gen')!=2:
            raise ValueError('resize ack failed')

        # seq 2: gen 2 (32x48)
        shape2=dict(v=1,sid=1,gen=2,w=32,h=48,pitch=128,format='RGBA8')
        payload2=bytes((4,5,6,255))*(32*48);crc2=zlib.crc32(payload2)
        send(dict(shape2,type='FRAME',seq=2,payload_bytes=len(payload2),crc32=crc2,capture=True),payload2)
        r2=recv();t2=recv()
        for a in (r2,t2):
            if a.get('sid')!=1 or a.get('gen')!=2 or a.get('seq')!=2 or a.get('crc32')!=crc2 or a.get('slot') not in (0,1):
                raise ValueError('resize seq 2 identity mismatch')
        if t2.get('disposition')!='displayed' or not t2.get('capture_match'):raise ValueError('display mismatch')
        received_acks.append(r2);terminals.append(t2)

        # seq 3: 旧 gen 1 违规测试，断言 host 拒绝发送 ERROR
        payload_stale=bytes((7,8,9,255))*(64*64);crc_stale=zlib.crc32(payload_stale)
        send(dict(shape,type='FRAME',seq=3,payload_bytes=len(payload_stale),crc32=crc_stale,capture=False),payload_stale)
        err=recv()
        if err.get('type')!='ERROR' or err.get('reason')!='frame_shape_identity':
            raise ValueError('stale generation was not rejected with ERROR')

        sock.close();rc=child.wait(timeout=3)
        result_data=dict(scenario=args.scenario,displayed=2,host_exit=rc,
                         stale_rejected=True,error_observed=err,
                         received=received_acks,terminal=terminals)

    elif args.scenario=='latest':
        count=100
        terminals=[];received_acks=[];sent={};reader_errors=[]
        def collect_latest():
            try:
                while len(terminals)<count:
                    ack,data=wire.receive_packet(sock,time.monotonic()+5)
                    if data:raise ValueError('unexpected ack payload in latest')
                    if ack.get('stage')=='RECEIVED':received_acks.append(ack)
                    elif ack.get('stage')=='CONSUMED':terminals.append(ack)
                    else:raise ValueError('unexpected ack stage: '+str(ack))
            except Exception as e:
                reader_errors.append(repr(e))
        reader=threading.Thread(target=collect_latest)
        reader.start()
        for seq in range(1,count+1):
            payload=bytes((seq&255,(seq>>8)&255,(seq*17)&255,255))*(64*64);crc=zlib.crc32(payload)
            sent[seq]=crc
            send(dict(shape,type='FRAME',seq=seq,payload_bytes=len(payload),crc32=crc,capture=False),payload)
            time.sleep(0.001)
        reader.join(timeout=8)
        if reader.is_alive() or reader_errors:
            raise RuntimeError('latest reader incomplete or errored: '+repr(reader_errors))
        send(dict(v=1,sid=1,type='CLOSE'))
        close_ack=recv()
        if close_ack.get('stage')!='CLOSED':raise ValueError('close ack missing')
        sock.close();rc=child.wait(timeout=3)

        # 严密断言
        if len(received_acks)!=count:raise ValueError(f'received count mismatch: {len(received_acks)} != {count}')
        if len(terminals)!=count:raise ValueError(f'terminal count mismatch: {len(terminals)} != {count}')
        for g in (received_acks,terminals):
            if {a['seq'] for a in g}!=set(sent):raise ValueError('missing/duplicate seq in ACK')
            if any(a.get('sid')!=1 or a.get('gen')!=1 or a.get('crc32')!=sent[a['seq']] for a in g):
                raise ValueError('ACK identity error')
            if any(a.get('slot') not in (0,1) for a in g):raise ValueError('invalid slot')
        recv_slot={a['seq']:a['slot'] for a in received_acks}
        if any(recv_slot[a['seq']]!=a['slot'] for a in terminals):raise ValueError('slot mismatch')
        
        replaced=[a['seq'] for a in terminals if a.get('disposition')=='replaced']
        displayed=sum(a.get('disposition')=='displayed' for a in terminals)
        if displayed + len(replaced) != count:
            raise ValueError(f'terminal disposition sum mismatch: displayed({displayed}) + replaced({len(replaced)}) != {count}')
        if not replaced and not override:
            raise ValueError('latest-frame-wins failed: zero frames replaced')

        result_data=dict(scenario=args.scenario,count=count,displayed=displayed,
                         replaced=replaced,host_exit=rc,
                         received=received_acks,terminal=terminals)

    elif args.scenario in ('busy','busy-close'):
        busy_dylib=root/'busy.dylib'
        compile_busy_dylib(busy_dylib)
        lib=ctypes.CDLL(str(busy_dylib))
        lib.busy_ns.argtypes=[ctypes.c_uint64];lib.busy_ns.restype=ctypes.c_uint64

        payload=bytes((1,2,3,255))*(64*64);crc=zlib.crc32(payload)
        send(dict(shape,type='FRAME',seq=1,payload_bytes=len(payload),crc32=crc,capture=True),payload)
        r=recv();t=recv()

        is_close=args.scenario=='busy-close'
        send(dict(v=1,sid=1,type='ARM',close=is_close))
        armed=recv()
        if armed.get('stage')!='ARMED':raise ValueError('arm ack')

        # 独立线程在忙算期间等待接收 host 发来的 HANDLED ACK
        handled_holder=[]
        handled_err=[]
        def wait_handled():
            try:
                h,data=wire.receive_packet(sock,time.monotonic()+4)
                if data:raise ValueError('handled ack with payload')
                h['observed_ns']=time.monotonic_ns()
                handled_holder.append(h)
            except Exception as e:
                handled_err.append(repr(e))
        th=threading.Thread(target=wait_handled)
        th.start()

        busy_begin=time.monotonic_ns()
        ops=lib.busy_ns(3_000_000_000)
        busy_end=time.monotonic_ns()

        th.join(timeout=2)
        if not handled_holder:
            raise ValueError('HANDLED event ACK was not received in time: '+repr(handled_err))
        handled_ack=handled_holder[0]
        if handled_ack.get('ack_for')!='EVENT' or handled_ack.get('stage')!='HANDLED':
            raise ValueError('bad event ack: '+str(handled_ack))
        expected_event='close_event' if is_close else 'ui_event'
        if handled_ack.get('event')!=expected_event:
            raise ValueError(f'event mismatch: {handled_ack.get("event")} != {expected_event}')

        # 检查观察时刻落在忙算区间内
        obs=handled_ack['observed_ns']
        if not (busy_begin <= obs <= busy_end):
            raise ValueError(f'HANDLED event observed outside busy interval: {obs} not in [{busy_begin}, {busy_end}]')

        if not is_close:
            send(dict(v=1,sid=1,type='CLOSE'))
            try:recv()
            except Exception:pass
        sock.close();rc=child.wait(timeout=3)

        stdout_text=(root/'host.stdout').read_text()
        logs=[json.loads(line) for line in stdout_text.splitlines() if line.strip().startswith('{')]
        event=next((x for x in logs if x.get('event')==expected_event),None)
        if not event or not event.get('main_thread'):raise ValueError('event missing or not on main thread in host.stdout')

        result_data=dict(scenario=args.scenario,busy_ms=(busy_end-busy_begin)/1e6,
                         busy_ops=ops,host_exit=rc,event=event,
                         armed_ack=armed,handled_ack=handled_ack,
                         observed_in_busy=True)

    result_data.update(fixture=bool(override),host_sha256=digest)
    (root/'result.json').write_text(json.dumps(result_data,indent=2))
    return int(result_data.get('host_exit',0)!=0)

if __name__=='__main__':sys.exit(main())
