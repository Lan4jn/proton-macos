#!/usr/bin/env python3
"""Single-frame host probe inside the P0-owned process group."""
import argparse
import hashlib
import json
import os
import pathlib
import socket
import sys
import time
import zlib
import roles
import deadline_io
import wire

ROOT=pathlib.Path(__file__).resolve().parents[2]
HOST=ROOT/'logs/p1-a-copy-v2/run-4e2a63efe2f2/presenter'
HOST_SHA='b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb'


def main():
    p=argparse.ArgumentParser()
    p.add_argument('scenario',metavar='scenario',choices=['smoke','correctness','throughput','latest','resize','busy','busy-close','disconnect'])
    p.add_argument('--fixture-host',default=None)
    p.add_argument('--frames',type=int,default=None)
    args=p.parse_args()
    if args.frames is not None and not args.fixture_host:raise SystemExit('frames override fixture only')
    if args.fixture_host and args.scenario not in ('smoke','correctness','throughput'):raise SystemExit('fixture host only permitted for test scenarios')
    root=pathlib.Path.cwd()
    try:
        owner=json.loads((root.parent/'owned.json').read_text())
        if owner['pgid']!=os.getpgrp():raise ValueError('group mismatch')
    except (OSError,ValueError,KeyError):raise SystemExit('P0 supervised session required')
    if args.scenario not in ('smoke','correctness','throughput'):raise SystemExit('host scenario not implemented')
    override=args.fixture_host
    host=pathlib.Path(override) if override else HOST
    digest=hashlib.sha256(host.read_bytes()).hexdigest()
    if not override and digest!=HOST_SHA:raise SystemExit('frozen host SHA mismatch')
    sockpath=root/'s'
    if len(str(sockpath).encode())>=104:raise SystemExit('socket path too long')
    argv=([sys.executable,str(host)] if override else [str(host)])+[str(sockpath),'120']
    child=roles.spawn('host',argv,root)
    # Preserve producer identity before connect; P0 parent identity remains reserved.
    import subprocess
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
    shape=dict(v=1,sid=1,gen=1,w=64,h=64,pitch=256,format='RGBA8')
    def send(header,data=b''):wire.send_packet(sock,header,data,time.monotonic()+2)
    def recv():
        h,data=wire.receive_packet(sock,time.monotonic()+3)
        if data:raise ValueError('unexpected ack payload')
        return h
    if args.scenario=='throughput' and not override:shape.update(w=1280,h=720,pitch=5120)
    send(dict(shape,type='CREATE'))
    ack=recv()
    if ack.get('ack_for')!='CREATE' or ack.get('stage')!='CONFIGURED':raise ValueError('create ack')
    realtime=args.scenario=='throughput'
    count=args.frames if override and args.frames is not None else (900 if realtime else (1000 if args.scenario=='correctness' else 1))
    if count<1:raise ValueError('frame count')
    terminals=[];received_acks=[];sent={};sent_at={};reader_errors=[]
    import threading
    def collect():
        try:
            while len(terminals)<count:
                ack,data=wire.receive_packet(sock,time.monotonic()+5)
                if data:raise ValueError('unexpected ack payload')
                ack['producer_observed_ns']=time.monotonic_ns()
                if ack.get('stage')=='RECEIVED':received_acks.append(ack)
                elif ack.get('stage')=='CONSUMED':terminals.append(ack)
                else:raise ValueError('unexpected ack')
        except Exception as exc:reader_errors.append(repr(exc))
    reader=threading.Thread(target=collect) if realtime else None
    if reader:reader.start()
    started=time.monotonic()
    for seq in range(1,count+1):
        if realtime and not override:
            due=started+(seq-1)/30
            if due>time.monotonic():time.sleep(due-time.monotonic())
        w,h=(1280,720) if realtime and not override else (64,64)
        frame_shape=dict(shape,w=w,h=h,pitch=w*4)
        payload=bytes((seq&255,(seq>>8)&255,(seq*17)&255,255))*(w*h);crc=zlib.crc32(payload)
        sent[seq]=crc;sent_at[seq]=time.monotonic_ns()
        send(dict(frame_shape,type='FRAME',seq=seq,payload_bytes=len(payload),crc32=crc,capture=not realtime),payload)
        if not realtime:
            received=recv();terminal=recv()
            for ack in (received,terminal):
                if ack.get('seq')!=seq or ack.get('gen')!=1 or ack.get('crc32')!=crc or ack.get('sid')!=1:raise ValueError('identity mismatch')
                if ack.get('slot') not in (0,1):raise ValueError('invalid slot')
            if received.get('slot')!=terminal.get('slot'):raise ValueError('slot mismatch between stages')
            if received.get('stage')!='RECEIVED' or terminal.get('stage')!='CONSUMED' or terminal.get('disposition')!='displayed' or not terminal.get('capture_match'):raise ValueError('frame mismatch')
            received_acks.append(received);terminals.append(terminal)
    if realtime:
        if not override:
            remainder=started+30-time.monotonic()
            if remainder>0:time.sleep(remainder)
        reader.join(timeout=8)
        if reader.is_alive() or reader_errors:raise RuntimeError('ack reader incomplete: '+repr(reader_errors))
        for group in (received_acks,terminals):
            if len(group)!=count or {a.get('seq') for a in group}!=set(sent):raise ValueError('missing or duplicate ACK')
            if any(a.get('crc32')!=sent[a['seq']] or a.get('gen')!=1 or a.get('sid')!=1 for a in group):raise ValueError('ACK identity')
            if any(a.get('slot') not in (0,1) for a in group):raise ValueError('invalid slot')
        # 配对每seq的slot一致
        recv_by_seq={a['seq']:a['slot'] for a in received_acks}
        if any(recv_by_seq[a['seq']]!=a['slot'] for a in terminals):raise ValueError('slot mismatch between stages')
        if any(a.get('disposition') not in ('displayed','replaced','invalidated') for a in terminals):raise ValueError('invalid terminal disposition')
    duration=time.monotonic()-started
    send(dict(v=1,sid=1,type='CLOSE'))
    if recv().get('stage')!='CLOSED':raise ValueError('close ack')
    sock.close();rc=child.wait(timeout=3)
    def pct(values):
        values=sorted(values)
        return {k:values[round((len(values)-1)*q)] for k,q in [('p50',.5),('p95',.95),('p99',.99)]} if values else {}
    rtt=[(a['producer_observed_ns']-sent_at[a['seq']])/1e6 for a in terminals if 'producer_observed_ns' in a]
    age=[a['host_age_ms'] for a in terminals if 'host_age_ms' in a]
    result=dict(scenario=args.scenario,fixture=bool(override),host_sha256=digest,host_exit=rc,
                displayed=sum(a.get('disposition')=='displayed' for a in terminals),
                replaced=[a['seq'] for a in terminals if a.get('disposition')=='replaced'],
                invalidated=[a['seq'] for a in terminals if a.get('disposition')=='invalidated'],
                received=received_acks,terminal=terminals,duration_s=duration,
                rtt_ms=pct(rtt),host_age_ms=pct(age),ready_depth_max=max([a.get('ready_depth',0) for a in received_acks] or [0]),
                payload_bytes=count*(1280*720*4 if realtime and not override else 64*64*4))
    (root/'result.json').write_text(json.dumps(result,indent=2))
    return int(rc!=0)

if __name__=='__main__':sys.exit(main())
