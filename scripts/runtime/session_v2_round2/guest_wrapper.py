"""P0-owned barrier observer; fixture runs native probe, no guest mode yet."""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
import uuid

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from guest_protocol import parse_phase

def snapshot():
    p=subprocess.run(['/bin/ps','-axo','pid=,ppid=,pgid=,stat=,lstart='],capture_output=True,text=True,check=True,timeout=3)
    out=[]
    for line in p.stdout.splitlines():
        a=line.split(None,4)
        if len(a)==5: out.append(dict(pid=int(a[0]),ppid=int(a[1]),pgid=int(a[2]),state=a[3],identity=a[4]))
    return out

def read_line(fd, buffer, deadline):
    while b'\n' not in buffer:
        remaining=deadline-time.monotonic()
        if remaining<=0: raise TimeoutError('phase deadline')
        ready,_,_=select.select([fd],[],[],remaining)
        if not ready: raise TimeoutError('phase deadline')
        b=os.read(fd,4096)
        if not b: raise EOFError('phase stream EOF')
        buffer+=b
        if len(buffer)>65536: raise ValueError('phase stream too long')
    line,buffer=buffer.split(b'\n',1)
    return line.decode('utf-8'),buffer

def inspect(rows, owner, wrapper, probe):
    by={r['pid']:r for r in rows}
    chain=[owner['pid'],wrapper,probe]
    if len(set(chain))!=3: raise ValueError('duplicate pid')
    if any(i not in by for i in chain): raise ValueError('missing chain')
    if by[owner['pid']]['identity']!=owner['identity'] or by[owner['pid']]['pgid']!=owner['pgid']:
        raise ValueError('owner changed')
    if by[wrapper]['ppid']!=owner['pid'] or by[probe]['ppid']!=wrapper: raise ValueError('broken parent chain')
    children=[r for r in rows if r['ppid']==probe and not r['state'].startswith('Z')]
    if len(children)!=1: raise ValueError('ambiguous child')
    chain.append(children[0]['pid'])
    if any(by[i]['pgid']!=owner['pgid'] for i in chain): raise ValueError('group mismatch')
    return [by[i] for i in chain]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); ap.add_argument('--standin',required=True); ap.add_argument('--stall',action='store_true'); args=ap.parse_args()
    root=Path(args.root); token=uuid.uuid4().hex
    owner=json.loads((Path(os.environ['HOME']).parent/'owned.json').read_text())
    result={'status':'UNKNOWN','guest_evidence':'SIMULATED','runtime_exit':None,'snapshots':[],'events':[],'error':None}
    proc=None
    try:
        proc=subprocess.Popen([sys.executable,'-I',args.standin,str(root/'tmp'),token],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        buf=b''
        for phase in ('parent','pre','post','child_exit'):
            line,buf=read_line(proc.stdout.fileno(),buf,time.monotonic()+4)
            rec=parse_phase(line,phase,token); result['events'].append(rec)
            if phase in ('pre','post'):
                rows=snapshot(); chain=inspect(rows,owner,os.getpid(),proc.pid)
                result['snapshots'].append(chain)
                (Path.cwd()/'observer-pre.json').write_text(json.dumps(result,indent=2))
                if args.stall and phase=='pre':
                    while True: time.sleep(60)
                (root/'tmp'/(phase+'.ack')).write_text(token)
        result['runtime_exit']=proc.wait(timeout=3)
        if result['runtime_exit']!=0: raise ValueError('probe exit')
        pre,post=result['snapshots']
        if [(r['pid'],r['identity'],r['ppid']) for r in pre]!=[(r['pid'],r['identity'],r['ppid']) for r in post]: raise ValueError('identity changed')
        if result['events'][2]['result']!=result['events'][2]['pid']: raise ValueError('setsid failed')
        result['status']='PASS'
    except Exception as exc: result['error']=type(exc).__name__+': '+str(exc)
    finally:
        (Path.cwd()/'observer.json').write_text(json.dumps(result,indent=2))
    return 0 if result['status']=='PASS' else 1
if __name__=='__main__': sys.exit(main())
