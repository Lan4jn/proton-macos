"""Register children by identity in the inherited P0 session."""
import json
import os
import pathlib
import subprocess

_unregistered=[]


def spawn(role,argv,root):
    root=pathlib.Path(root)
    out=open(root/(role+'.stdout'),'xb')
    err=open(root/(role+'.stderr'),'xb')
    try:
        child=subprocess.Popen(argv,stdout=out,stderr=err)
    finally:
        out.close();err.close()
    # P0 parent owns cleanup even if identity capture fails here.
    try:
        observed=subprocess.run(['/bin/ps','-p',str(child.pid),'-o','pid=,ppid=,pgid=,lstart='],capture_output=True,text=True,check=True,timeout=2)
    except Exception:
        try:child.wait(timeout=.5)
        except subprocess.TimeoutExpired: _unregistered.append(child)
        raise
    fields=observed.stdout.strip().split(None,3)
    if len(fields)!=4 or int(fields[0])!=child.pid or int(fields[2])!=os.getpgrp():
        raise RuntimeError('child identity or group not observed')
    record=dict(role=role,pid=int(fields[0]),ppid=int(fields[1]),pgid=int(fields[2]),identity=fields[3],argv=argv)
    with (root/(role+'.identity.json')).open('x') as f:json.dump(record,f,indent=2)
    return child
