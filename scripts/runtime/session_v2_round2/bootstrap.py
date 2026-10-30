"""Round-2 P0 bootstrap: fixture mode only; no guest execution."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import uuid

LAB=Path(__file__).resolve().parents[3]
P0=LAB/'scripts/runtime/session_v2/run.py'
SHA='3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b'

def main():
    if len(sys.argv)!=3 or sys.argv[1] not in ('--fixture','--stall-fixture'): raise SystemExit('fixture mode only')
    mode,run_id=sys.argv[1:]
    if hashlib.sha256(P0.read_bytes()).hexdigest()!=SHA: raise SystemExit('P0 digest mismatch')
    root=LAB/'sources/p0-session-round2'/('fixture-'+uuid.uuid4().hex)
    (root/'tmp').mkdir(parents=True,exist_ok=False)
    standin=Path(__file__).with_name('standin.py')
    spec=importlib.util.spec_from_file_location('p0',P0); p0=importlib.util.module_from_spec(spec); spec.loader.exec_module(p0)
    p0.LOGS=LAB/'logs/session-v2-round2'
    args=['--run-id',run_id,'--timeout','20','--outer-timeout','30','--module','standin='+str(standin),
          '--',sys.executable,'-I',str(Path(__file__).with_name('guest_wrapper.py')),
          '--root',str(root),'--standin',str(standin)]
    if mode=='--stall-fixture':
        args[args.index('20')]='20'; args[args.index('30')]='6'; args.insert(0,'--fixture-short-outer'); args.append('--stall')
    sys.argv=[str(P0)]+args
    return p0.main()
if __name__=='__main__': sys.exit(main())
