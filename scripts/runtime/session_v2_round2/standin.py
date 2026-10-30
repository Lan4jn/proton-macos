"""Host stand-in: all guest identities are synthetic; never changes host session."""
import json
import os
from pathlib import Path
import sys
import time

root=Path(sys.argv[1]); token=sys.argv[2]
def emit(phase,pid,ppid,pgid,sid,result=0):
    print(json.dumps(dict(phase=phase,token=token,pid=pid,ppid=ppid,pgid=pgid,sid=sid,result=result,errno=0)),flush=True)
def ack(phase):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        p=root/(phase+'.ack')
        if p.exists(): return p.read_text()==token
        time.sleep(.01)
    return False
emit('parent',101,100,100,100)
pid=os.fork()
if pid==0:
    emit('pre',102,101,100,100)
    if not ack('pre'): os._exit(71)
    emit('post',102,101,102,102,102)
    if not ack('post'): os._exit(72)
    os._exit(0)
_,status=os.waitpid(pid,0)
exitcode=os.waitstatus_to_exitcode(status)
emit('child_exit',101,100,100,100,exitcode)
os._exit(exitcode)
