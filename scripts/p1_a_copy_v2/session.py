"""P0 reviewed worker/cleanup adapter; all evidence stays in task-3 roots."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import time
import uuid

P0_PATH=pathlib.Path(__file__).resolve().parents[1]/'runtime/session_v2/run.py'
P0_SHA256='3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b'
import hashlib
if hashlib.sha256(P0_PATH.read_bytes()).hexdigest()!=P0_SHA256:
    raise RuntimeError('P0 frozen module changed; adapter re-review required')
spec=importlib.util.spec_from_file_location('p0_session_v2',P0_PATH)
p0=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p0)


def new_run(root,label=None):
    root=pathlib.Path(root);root.mkdir(parents=True,exist_ok=True)
    path=root/(label or ('run-'+uuid.uuid4().hex[:12]))
    if path.parent.resolve()!=root.resolve():raise ValueError('one component label required')
    path.mkdir(exist_ok=False)
    return path


class Target:
    def __init__(self,worker,root):
        self.worker=worker;self.root=root;self.pid=worker.pid

    def result(self):
        path=self.root/'worker-result.json'
        return json.loads(path.read_text()) if path.exists() else None

    def poll(self):
        result=self.result()
        if result:return result['target_exit']
        leader=next((r for r in p0.snapshot() if r['pid']==self.pid),None)
        if leader is None or leader['state'].startswith('Z'):
            raise RuntimeError('worker exited; target exit NOT_OBSERVED')
        return None

    @property
    def returncode(self):return self.poll()

    def wait(self,timeout=None):
        deadline=time.monotonic()+(timeout if timeout is not None else 60)
        while True:
            result=self.result()
            if result:
                if result.get('error'):raise RuntimeError(result['error'])
                if result['inner_timed_out']:raise subprocess.TimeoutExpired('P0 target',timeout)
                return result['target_exit']
            if time.monotonic()>=deadline:raise subprocess.TimeoutExpired('P0 target',timeout)
            time.sleep(.01)


class OwnedSession:
    def __init__(self,directory):
        self.directory=pathlib.Path(directory);self.children=[]

    def start(self,argv,name):
        root=self.directory/('governance-'+name);root.mkdir()
        (root/'work').mkdir()
        p0.save(root/'config.json',dict(command=list(map(str,argv)),timeout=65,environment=dict(os.environ)))
        worker_stderr=open(root/'worker-stderr.log','xb')
        worker=subprocess.Popen([sys.executable,'-I',str(P0_PATH),'--worker',str(root)],
                                start_new_session=True,stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,stderr=worker_stderr)
        # Register before observation; without identity, never send GO or signals.
        entry=dict(worker=worker,root=root,owner=None,stderr=worker_stderr)
        self.children.append(entry)
        try:
            owner=next(r for r in p0.snapshot() if r['pid']==worker.pid)
            if owner['pgid']!=worker.pid:raise RuntimeError('P0 worker not isolated')
            entry['owner']=owner;p0.save(root/'owned.json',owner)
            deadline=time.monotonic()+3
            while not (root/'ready.json').exists():
                if time.monotonic()>=deadline:raise TimeoutError('P0 worker ready')
                time.sleep(.01)
            ready=json.loads((root/'ready.json').read_text())
            if ready!=dict(pid=owner['pid'],pgid=owner['pgid']):raise RuntimeError('P0 handshake identity')
            for suffix,source in [('stdout','stdout.log'),('stderr','stderr.log')]:
                (self.directory/(name+'.'+suffix)).symlink_to(root.name+'/'+source)
            worker.stdin.write(b'GO\n');worker.stdin.flush();worker.stdin.close()
        except Exception:
            if worker.stdin and not worker.stdin.closed:worker.stdin.close()
            raise
        return Target(worker,root)

    def cleanup(self):
        records=[]
        for entry in self.children:
            worker=entry['worker'];root=entry['root'];owner=entry['owner']
            if worker.stdin and not worker.stdin.closed:worker.stdin.close()
            if owner is not None:
                report=p0.cleanup(root,owner,worker)
            else:
                report=dict(complete=False,error='UNKNOWN identity; no GO or signal sent',observed=[],signals=[])
                try:report['worker_exit']=worker.wait(timeout=4)
                except subprocess.TimeoutExpired:report['error']+='; self-retirement timeout'
            entry['stderr'].close()
            result=json.loads((root/'worker-result.json').read_text()) if (root/'worker-result.json').exists() else None
            record=dict(pid=worker.pid,pgid=worker.pid,spawn_identity=owner,
                        target_result=result,exit=result.get('target_exit') if result else None,
                        signal_error=report.get('error'),alive_after=not report['complete'],
                        group_members_before={r['pid']:r for r in report['observed']},
                        cleanup_state='exited' if report['complete'] else 'UNKNOWN_or_failed',
                        self_retired_before_exec=owner is None and worker.returncode is not None,
                        target_not_started=owner is None,p0_sha256=P0_SHA256,p0_cleanup=report)
            p0.save(root/'adapter-cleanup.json',record);records.append(record)
        return records
