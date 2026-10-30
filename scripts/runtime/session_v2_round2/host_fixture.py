"""Exercise frozen P0 session worker with a real host fork barrier."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

LAB = Path(__file__).resolve().parents[3]
P0 = LAB/'scripts/runtime/session_v2/run.py'
P0_SHA = '3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b'

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

def run_fixture(mode='normal', run_id=None, fail_post_cleanup_snapshot=False):
    if mode not in ('normal', 'timeout', 'worker_crash'): raise ValueError('invalid mode')
    if hashlib.sha256(P0.read_bytes()).hexdigest() != P0_SHA: raise RuntimeError('P0 SHA mismatch')
    p0 = module(P0, 'frozen_p0')
    corr = module(Path(__file__).with_name('correlation.py'), 'correlation')
    run_id = run_id or 'host-'+uuid.uuid4().hex
    if not re.fullmatch(r'[A-Za-z0-9_-]+',run_id): raise ValueError('invalid run id')
    root = LAB/'logs/session-v2-round2'/run_id
    root.mkdir(parents=True, exist_ok=False)
    for n in ('work','prefix','home','tmp'): (root/n).mkdir()
    token = uuid.uuid4().hex
    env = {'PATH':'/usr/bin:/bin', 'HOME':str(root/'home'), 'TMPDIR':str(root/'tmp'),
           'FIXTURE_ROOT':str(root), 'FIXTURE_TOKEN':token}
    cfg = {'command':[sys.executable,'-I',str(Path(__file__).with_name('fixture_child.py'))],
           'timeout':1 if mode=='timeout' else 8, 'environment':env}
    (root/'config.json').write_text(json.dumps(cfg))
    sentinel = subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)'], start_new_session=True)
    proc = None; owner = None; result = None; snapshots=[]; tokens=[]; known=[]; fault=None
    assessment={'status':'UNKNOWN','reason':'incomplete barriers'}
    run_error=None
    try:
        with (root/'worker-stderr.log').open('xb') as err:
            proc = subprocess.Popen([sys.executable,'-I',str(P0),'--worker',str(root)],
                start_new_session=True, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err)
            rows = p0.snapshot()
            owner = next(r for r in rows if r['pid']==proc.pid)
            if owner['pgid'] != proc.pid: raise RuntimeError('worker not group leader')
            (root/'owned.json').write_text(json.dumps(owner))
            deadline = time.monotonic()+3
            while not (root/'ready.json').exists():
                if time.monotonic()>deadline: raise TimeoutError('worker ready')
                time.sleep(.01)
            ready = json.loads((root/'ready.json').read_text())
            if ready != {'pid':owner['pid'], 'pgid':owner['pgid']}: raise RuntimeError('identity mismatch')
            proc.stdin.write(b'GO\n'); proc.stdin.flush(); proc.stdin.close()
            for phase in ('pre','post'):
                deadline=time.monotonic()+5
                while not (root/phase).exists():
                    if time.monotonic()>deadline: raise TimeoutError(phase)
                    time.sleep(.01)
                tokens.append((root/phase).read_text())
                snapshots.append(p0.snapshot())
                if phase=='pre' and mode != 'normal':
                    known=[r for r in snapshots[-1] if r['pgid']==owner['pgid']]
                    if len(known)<3: raise RuntimeError('missing known pre-fault tree')
                    (root/'pre-fault-identities.json').write_text(json.dumps(known,indent=2))
                    if mode=='worker_crash':
                        current=next((r for r in p0.snapshot() if r['pid']==owner['pid']),None)
                        if not current or current['identity']!=owner['identity'] or current['pgid']!=owner['pgid']: raise RuntimeError('worker identity lost')
                        os.kill(owner['pid'],signal.SIGKILL)
                        fault={'pid':owner['pid'],'identity':owner['identity'],'signal':'SIGKILL','result':'sent'}
                    break
                (root/(phase+'.ack')).write_text(token)
            if mode!='worker_crash':
                deadline=time.monotonic()+5
                while not (root/'worker-result.json').exists():
                    if time.monotonic()>deadline: raise TimeoutError('worker result')
                    time.sleep(.01)
                result=json.loads((root/'worker-result.json').read_text())
            if mode=='normal': assessment=corr.evaluate(owner, snapshots[0], snapshots[1],token,*tokens)
    except Exception as exc:
        run_error=type(exc).__name__+': '+str(exc)
    finally:
        errors=[] if run_error is None else [run_error]; cleanup={'complete':False}; remaining=None
        try:
            if proc:
                if proc.stdin and not proc.stdin.closed: proc.stdin.close()
                cleanup=p0.cleanup(root,owner,proc) if owner else {'complete':proc.wait(timeout=4) is not None}
            else: cleanup={'complete':True}
        except Exception as exc:
            errors.append('cleanup: '+str(exc))
        try:
            if fail_post_cleanup_snapshot: raise RuntimeError('injected post-cleanup snapshot')
            after=p0.snapshot()
            remaining=[r for r in after if any(r['pid']==k['pid'] and r['identity']==k['identity'] for k in known) and not r['state'].startswith('Z')]
        except Exception as exc:
            errors.append(str(exc))
        finally:
            sentinel_alive=sentinel.poll() is None
            if sentinel_alive: sentinel.terminate()
            sentinel.wait(timeout=3)
    output={'correlation':assessment, 'sentinel_alive':sentinel_alive, 'sentinel_reaped':sentinel.poll() is not None,
            'cleanup':cleanup, 'errors':errors,
            'post_cleanup_observation':'UNKNOWN' if remaining is None else 'OBSERVED',
            'target_exit':result['target_exit'] if result else None,
            'inner_timed_out':result['inner_timed_out'] if result else None,
            'fault_signal':fault, 'known_before_fault':known, 'known_after_cleanup':remaining,
            'known_after_cleanup_clear':None if remaining is None else not remaining, 'snapshots':snapshots, 'root':str(root)}
    (root/'host-fixture-receipt.json').write_text(json.dumps(output,indent=2))
    return output
