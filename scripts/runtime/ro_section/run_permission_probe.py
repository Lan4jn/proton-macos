#!/usr/bin/env python3
import os,json,time,subprocess,signal,hashlib,resource,argparse
from pathlib import Path
LAB=Path(__file__).resolve().parents[3]
OUT=LAB/'logs/ro-section'
RT=LAB/'sources/elfuse-once-panorama2-derived/build/elfuse'
SYS=LAB/'fixtures/runtime/arch-case'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
env=dict(os.environ)
env.pop('ELFUSE_DIAG_SESSION_SHARED',None)
assert 'ELFUSE_DIAG_SESSION_SHARED' not in env
parser=argparse.ArgumentParser()
parser.add_argument('labels',nargs='*',default=['baseline','approved_candidate'])
for label in parser.parse_args().labels:
    assert label in ['baseline','approved_candidate','detach_red','detach_green','production_red','production_green','production_observe']
    assert not (OUT/(label+'.result.json')).exists(), 'Keep previous evidence; choose a new run label'
    exe=LAB/'sources/wine-ro-section-adapt'/label
    argv=[str(RT),'--user',f'{os.getuid()}:{os.getgid()}','--sysroot',str(SYS),'--timeout','15',str(exe)]
    start=time.monotonic();timed_out=False
    with (OUT/(label+'.stdout.log')).open('w') as out,(OUT/(label+'.stderr.log')).open('w') as err:
        p=subprocess.Popen(argv,env=env,cwd=OUT,stdout=out,stderr=err,start_new_session=True)
        try: code=p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            timed_out=True;os.killpg(p.pid,signal.SIGKILL);code=p.wait()
        finally:
            try:os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError:pass
    stdout=(OUT/(label+'.stdout.log')).read_text()
    result={'label':label,'argv':argv,'gate_in_host_env':False,'gate_in_guest_env':False,'duration_seconds':round(time.monotonic()-start,3),'exit_code':code,'timed_out':timed_out,'runtime_sha256':sha(RT),'executable_sha256':sha(exe),'boundary':('complete production virtual.c TU; only debug logging stubs; real map_file_into_view and set_protection' if label.startswith('production_') else 'extracted Wine helper boundary, not PE NtProtect'),'private_leak_observed':('STOP_PRIVATE_WRITE_LEAK' in stdout or 'NO_BACKING_LEAK=FAIL' in stdout)}
    (OUT/(label+'.result.json')).write_text(json.dumps(result,indent=2)+chr(10))
    print(json.dumps(result,indent=2));print(stdout)
    if result['private_leak_observed']:
        print('STOP: approved design private-write regression failed; no Wine deployment.')
        break
