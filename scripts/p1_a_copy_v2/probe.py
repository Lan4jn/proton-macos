"""Black-box host-only P1 scenarios. Every host belongs to a unique OwnedSession."""
import argparse
import ctypes
import hashlib
import json
import pathlib
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib
from session import OwnedSession, new_run
from wire import pack, receive

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOGS = ROOT / 'logs/p1-a-copy-v2'
SRC = ROOT / 'sources/p1-a-copy-v2'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shape(gen=1, w=64, h=64):
    return dict(v=1, sid=1, gen=gen, w=w, h=h, pitch=w*4, format='RGBA8')


def payload(seq, w, h):
    return bytes((seq & 255, (seq >> 8) & 255, (seq*17) & 255, 255))*(w*h)


def frame(seq, gen=1, w=64, h=64, capture=True):
    data = payload(seq, w, h)
    meta = dict(shape(gen,w,h), type='FRAME', seq=seq, payload_bytes=len(data),
                crc32=zlib.crc32(data), capture=capture)
    return meta, data


class Client:
    def __init__(self, sock):
        self.sock = sock
        self.cv = threading.Condition()
        self.messages = []
        self.eof = False
        self.thread = threading.Thread(target=self.reader, daemon=True)
        self.thread.start()

    def reader(self):
        try:
            while True:
                h, data = receive(self.sock)
                if data:
                    raise ValueError('ACK payload')
                h['producer_observed_ns'] = time.monotonic_ns()
                with self.cv:
                    self.messages.append(h)
                    self.cv.notify_all()
        except (EOFError, OSError, ValueError) as e:
            with self.cv:
                self.eof = True
                self.eof_ns = time.monotonic_ns()
                self.reader_exit = str(e)
                self.cv.notify_all()

    def send(self, header, data=b''):
        self.sock.sendall(pack(header, data))

    def wait(self, predicate, timeout=5):
        deadline = time.monotonic()+timeout
        with self.cv:
            while True:
                for item in self.messages:
                    if predicate(item):
                        return item
                if self.eof:
                    raise AssertionError('EOF before expected ACK')
                remain=deadline-time.monotonic()
                if remain<=0:
                    raise TimeoutError('ACK deadline')
                self.cv.wait(remain)

    def configured(self, gen=1, w=64, h=64, resize=False):
        self.send(dict(shape(gen,w,h), type='RESIZE' if resize else 'CREATE'))
        return self.wait(lambda a:a.get('stage')=='CONFIGURED' and a.get('gen')==gen)

    def terminal(self, seq, timeout=5):
        return self.wait(lambda a:a.get('stage')=='CONSUMED' and a.get('seq')==seq,timeout)

    def close(self):
        self.send(dict(v=1,sid=1,type='CLOSE'))
        return self.wait(lambda a:a.get('stage')=='CLOSED')


def send_header_only(sock, meta, data):
    packet=pack(meta,data)
    sock.sendall(packet[:-len(data)] if data else packet)


def expect_rejection(client,sender):
    try:sender()
    except BrokenPipeError:pass
    return client.wait(lambda a:a.get('type')=='ERROR')


def percentiles(values):
    values=sorted(values)
    if not values:
        return {}
    return {name:values[min(len(values)-1,round((len(values)-1)*p))]
            for name,p in [('p50',.5),('p95',.95),('p99',.99),('max',1)]}


def launch(binary, directory, hz, owner):
    sockpath=directory/'s'
    proc=owner.start([str(binary),str(sockpath),str(hz)],'host')
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    deadline=time.monotonic()+8
    while True:
        try:
            sock.connect(str(sockpath))
            break
        except (FileNotFoundError,ConnectionRefusedError):
            if proc.poll() is not None or time.monotonic()>deadline:
                raise AssertionError('host failed before connect: '+str(proc.poll()))
            time.sleep(.01)
    return owner,proc,Client(sock)


def verify_frames(client, sent, require_display=False):
    received=[m for m in client.messages if m.get('stage')=='RECEIVED']
    terminal=[m for m in client.messages if m.get('stage')=='CONSUMED']
    assert len(received)==len(sent),(len(received),len(sent))
    assert len(terminal)==len(sent),(len(terminal),len(sent))
    assert len({m['seq'] for m in terminal})==len(sent),'duplicate terminal'
    for item in received+terminal:
        assert item['crc32']==sent[item['seq']]['crc32']
        assert item['gen']==sent[item['seq']]['gen']
        assert item['slot'] in (0,1)
    if require_display:
        assert all(m['disposition']=='displayed' and m.get('capture_match') for m in terminal)
    return dict(received=len(received),terminals=len(terminal),
                displayed=sum(m['disposition']=='displayed' for m in terminal),
                replaced=[m['seq'] for m in terminal if m['disposition']=='replaced'],
                invalidated=[m['seq'] for m in terminal if m['disposition']=='invalidated'],
                capture_count=sum('capture_match' in m for m in terminal),
                capture_all_match=all(m.get('capture_match',True) for m in terminal),
                host_age_ms=percentiles([m['host_age_ms'] for m in terminal]),
                ready_depth_max=max([m.get('ready_depth',0) for m in received] or [0]))


def scenario(binary, kind, count=4, hz=120, busy_lib=None):
    directory=new_run(LOGS)
    record=dict(kind=kind,host_only=True,guest_runtime_executed=False,
                clock='producer monotonic_ns for RTT; host mach clock age; cross-domain one-way UNKNOWN',
                capture_scope='NSView cache; no screen capture',runner_exit=1,
                inner_timeout=False,outer_timeout='NOT_IMPLEMENTED',command=sys.argv,
                binary=str(binary.relative_to(ROOT)),binary_sha256=sha(binary),run_dir=str(directory.relative_to(ROOT)))
    owner=OwnedSession(directory); client=None;proc=None;start=time.monotonic_ns()
    try:
        owner,proc,client=launch(binary,directory,hz,owner)
        if kind.startswith('negative:'):
            defect=kind.split(':',1)[1]
            if defect=='length':
                client.sock.sendall(struct.pack('!I',16777217))
            elif defect=='short':
                client.sock.sendall(b'\x00\x00')
                client.sock.shutdown(socket.SHUT_WR)
            else:
                client.configured()
                meta,data=frame(1)
                if defect=='overflow':meta['w']=2**62
                elif defect=='generation':meta['gen']=2
                elif defect=='crc':meta['crc32']^=1
                elif defect=='duplicate':
                    client.send(meta,data); client.terminal(1)
                elif defect=='truncated':
                    client.sock.sendall(pack(meta,data)[:-7]);client.sock.shutdown(socket.SHUT_WR)
                elif defect=='crc-object':meta['crc32']={}
                elif defect=='crc-string':meta['crc32']='123'
                elif defect=='crc-float':meta['crc32']=float(meta['crc32'])
                elif defect=='crc-bool':meta['crc32']=True
                elif defect=='capture-object':meta['capture']={}
                if defect in ('overflow','generation','duplicate','crc-object','crc-string','crc-float','crc-bool'):
                    expect_rejection(client,lambda:send_header_only(client.sock,meta,data))
                elif defect!='truncated':client.send(meta,data)
            error=client.wait(lambda a:a.get('type')=='ERROR')
            record['expected_protocol_error']=error
            record['successful_received']=sum(m.get('stage')=='RECEIVED' for m in client.messages)
            if defect!='duplicate':assert record['successful_received']==0
            proc.wait(timeout=3)
        elif kind=='disconnect':
            client.configured();client.sock.shutdown(socket.SHUT_RDWR)
            proc.wait(timeout=3)
        elif kind=='producer_exit':
            client.configured()
            # Shutdown socket is exactly the EOF observed after a process exit;
            # actual producer subprocess death is exercised separately by reviewer.
            client.sock.close()
            proc.wait(timeout=3)
        elif kind in ('busy','busy-close'):
            client.configured()
            meta,data=frame(1);client.send(meta,data);client.terminal(1)
            client.send(dict(v=1,sid=1,type='ARM',close=kind=='busy-close'))
            armed=client.wait(lambda a:a.get('stage')=='ARMED')
            busy_begin=time.monotonic_ns()
            lib=ctypes.CDLL(str(busy_lib));lib.busy_ns.argtypes=[ctypes.c_uint64];lib.busy_ns.restype=ctypes.c_uint64
            operations=lib.busy_ns(3_000_000_000)
            busy_end=time.monotonic_ns()
            record.update(busy_begin_ns=busy_begin,busy_end_ns=busy_end,
                          busy_ms=(busy_end-busy_begin)/1e6,busy_operations=operations,arm_ack=armed)
            if kind=='busy':client.close()
            proc.wait(timeout=3)
            logs=[json.loads(line) for line in (directory/'host.stdout').read_text().splitlines()]
            event=next(x for x in logs if x.get('event')==('close_event' if kind=='busy-close' else 'ui_event'))
            record['event']=event
            record['host_due_to_event_ms']=(event['host_ns']-armed['due_ns'])/1e6
            # Clock-domain-independent proof: event/exit already observed by ACK reader during busy.
            assert event['main_thread'] and 0 <= record['host_due_to_event_ms'] < 1000
            if kind=='busy-close':
                assert client.eof and busy_begin <= client.eof_ns <= busy_end,'close EOF not observed during busy'
                record['producer_observed_eof_ns']=client.eof_ns
            event_ack=client.wait(lambda a:a.get('ack_for')=='EVENT' and a.get('stage')=='HANDLED')
            record['event_ack']=event_ack
            assert busy_begin <= event_ack['producer_observed_ns'] <= busy_end,'AppKit event ACK not observed inside busy interval'
        else:
            w,h=(1280,720) if kind=='throughput' else (64,64)
            client.configured(w=w,h=h)
            sent={};published={};rtts=[]
            epoch=time.monotonic(); first=epoch
            target_count=900 if kind=='throughput' else count
            for seq in range(1,target_count+1):
                if kind=='throughput':
                    due=epoch+(seq-1)/30
                    if due>time.monotonic():time.sleep(due-time.monotonic())
                gen=1
                if kind=='resize' and seq==2:
                    client.configured(gen=2,w=32,h=48,resize=True);w,h=32,48
                if kind=='resize' and seq>=2:gen=2
                meta,data=frame(seq,gen,w,h,capture=kind!='throughput' and kind!='latest')
                sent[seq]=meta;published[seq]=time.monotonic_ns()
                client.send(meta,data)
                if kind!='latest' and kind!='throughput':
                    terminal=client.terminal(seq)
                    rtts.append((terminal['producer_observed_ns']-published[seq])/1e6)
            if kind=='throughput':
                end_due=epoch+30
                if end_due>time.monotonic():time.sleep(end_due-time.monotonic())
            client.terminal(target_count,timeout=10)
            elapsed=time.monotonic()-epoch
            client.close();proc.wait(timeout=3)
            record.update(verify_frames(client,sent,require_display=kind in ('correctness','resize','smoke')))
            if kind=='latest':assert record['replaced'],'must actually replace frames'
            if kind=='throughput':
                assert elapsed>=30
                rtts=[(a['producer_observed_ns']-published[a['seq']])/1e6 for a in client.messages if a.get('stage')=='CONSUMED']
            record.update(frame_count=target_count,payload_bytes=sum(m['payload_bytes'] for m in sent.values()),
                          duration_s=elapsed,producer_rtt_ms=percentiles(rtts),
                          payload_MBps=sum(m['payload_bytes'] for m in sent.values())/elapsed/1e6)
        record['target_exit']=proc.returncode
        assert proc.returncode==0,proc.returncode
        record['runner_exit']=0
    except Exception as exc:
        record['failure']=repr(exc)
        if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)):record['inner_timeout']=True
    finally:
        if client:
            try:client.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            client.sock.close();client.thread.join(timeout=1)
            (directory/'acks.json').write_text(json.dumps(client.messages,indent=2))
        record['cleanup']=owner.cleanup() if owner else []
        if any(r['signal_error'] or r['alive_after'] for r in record['cleanup']):
            record['runner_exit']=1
            record['cleanup_failure']=True
        record['elapsed_s']=(time.monotonic_ns()-start)/1e9
        if proc:record['target_exit']=proc.returncode
        record['inputs_sha256']={str(p.relative_to(ROOT)):sha(p) for p in list(SRC.glob('*'))+list((ROOT/'scripts/p1_a_copy_v2').glob('*.py')) if p.is_file()}
        record['evidence_sha256']={p.name:sha(p) for p in directory.iterdir() if p.is_file()}
        (directory/'receipt.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(dict(run_dir=record['run_dir'],kind=kind,exit=record['runner_exit'],failure=record.get('failure'))),flush=True)
    return record


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=['smoke','full'],default='smoke')
    args=parser.parse_args()
    build=new_run(LOGS)
    binary=build/'presenter'
    cmd=['clang','-fobjc-arc','-fblocks','-O2',str(SRC/'presenter.m'),'-o',str(binary),'-framework','AppKit','-framework','QuartzCore','-lz']
    compile_result=subprocess.run(cmd,capture_output=True)
    (build/'build.stdout').write_bytes(compile_result.stdout)
    (build/'build.stderr').write_bytes(compile_result.stderr)
    (build/'build.json').write_text(json.dumps(dict(argv=cmd,exit=compile_result.returncode)))
    if compile_result.returncode:
        print(compile_result.stderr.decode(),file=sys.stderr)
        return compile_result.returncode
    results=[scenario(binary,'smoke')]
    for defect in ['length','short','overflow','generation','crc','duplicate','truncated']:
        results.append(scenario(binary,'negative:'+defect))
    results.append(scenario(binary,'resize',count=4))
    results.append(scenario(binary,'disconnect'))
    if args.suite=='full':
        busy=build/'busy.dylib'
        busy_cmd=['clang','-O2','-dynamiclib',str(SRC/'busy.c'),'-o',str(busy)]
        cp=subprocess.run(busy_cmd,capture_output=True)
        (build/'busy-build.json').write_text(json.dumps(dict(argv=busy_cmd,exit=cp.returncode,stderr=cp.stderr.decode())))
        if cp.returncode:return cp.returncode
        results += [scenario(binary,'correctness',count=1000,hz=240),
                    scenario(binary,'throughput',hz=60),
                    scenario(binary,'latest',count=500,hz=10),
                    scenario(binary,'busy',busy_lib=busy),
                    scenario(binary,'busy-close',busy_lib=busy)]
    summary=dict(suite=args.suite,results=results,runner_exit=int(any(r['runner_exit'] for r in results)))
    (build/'summary.json').write_text(json.dumps(summary,indent=2))
    print('SUMMARY',str((build/'summary.json').relative_to(ROOT)),flush=True)
    return summary['runner_exit']


if __name__=='__main__':
    sys.exit(main())
