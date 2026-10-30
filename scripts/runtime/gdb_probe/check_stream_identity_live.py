import json
import hashlib
from pathlib import Path
import sys
lab=Path('/Users/mewcapoo/Projects/proton-macos-lab'); sys.path.insert(0,str(lab))
from scripts.backend.process import run_isolated
rt=Path(sys.argv[1]).resolve(); log=Path(sys.argv[2]).resolve()
assert rt.is_relative_to(lab/'sources') and log.is_relative_to(lab/'logs') and not log.exists()
log.mkdir(); m=b'[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...'
cases=[('plain','os.write(1,m)',True),('dup','f=os.dup(1); os.write(f,m); os.close(f)',True),('writev','os.writev(1,[m[:20],m[20:]])',True),('split','os.write(1,m[:20]); os.write(1,m[20:])',True),('unrelated','os.write(1,b"UNRELATED")',False),('other_object','f=os.open(os.devnull,os.O_WRONLY); os.write(f,m); os.close(f)',False),('split_other','os.write(1,m[:20]); f=os.open(os.devnull,os.O_WRONLY); os.write(f,m[20:]); os.close(f)',False)]
rows=[]
for name,body,expected in cases:
    argv=[str(rt),'--sysroot',str(lab/'fixtures/runtime/arch-case'),'--timeout','3',str(lab/'fixtures/runtime/arch-case/usr/bin/python3.14'),'-c','import os; m='+repr(m)+'; '+body]
    r=run_isolated(argv,log,timeout=5,extra_env={'ELFUSE_FIXTURE_IDENTITY':'1','ELFUSE_ABSOCK_BASE':str(lab/'.s')})
    e=Path(r['stderr']).read_text(); marks=[s for s in e.splitlines() if s.startswith('FIXTURE_STEP3_IDENTITY')]
    passed=r['exit']==0 and r['target_exit']==0 and not r['timed_out'] and not r['cleanup_errors'] and bool(marks)==expected
    rows.append({'case':name,'expected':expected,'detected':bool(marks),'passed':passed,'markers':marks,'result':r})
out={'runtime_sha256':hashlib.sha256(rt.read_bytes()).hexdigest(),'cases':rows,'passed':all(x['passed'] for x in rows)}
(log/'matrix.json').write_text(json.dumps(out,indent=2)+chr(10)); print(json.dumps({'passed':out['passed'],'cases':[{k:x[k] for k in ['case','expected','detected','passed']} for x in rows]})); sys.exit(0 if out['passed'] else 1)
