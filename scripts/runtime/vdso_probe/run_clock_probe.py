import hashlib, json, sys, time
from pathlib import Path
lab=Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0,str(lab))
from scripts.backend.process import run_isolated
rt=lab/"sources/elfuse-once-backtrace-derived/build/elfuse"
sysroot=lab/"fixtures/runtime/arch-case"
probe=lab/"scripts/runtime/vdso_probe/clock_vdso_probe.py"
logs=lab/"logs/vdso"
logs.mkdir(parents=True,exist_ok=True)
argv=[str(rt),"--user","501:20","--sysroot",str(sysroot),"--timeout","12",str(sysroot/"usr/bin/python3.14"),str(probe)]
t0=time.monotonic()
r=run_isolated(argv,logs/"clock-test",timeout=15)
stdout=Path(r["stdout"]).read_text(errors="replace")
stderr=Path(r["stderr"]).read_text(errors="replace")
receipt={"runtime_sha256":hashlib.sha256(rt.read_bytes()).hexdigest(),"probe_sha256":hashlib.sha256(probe.read_bytes()).hexdigest(),"argv":argv,"exit_code":r["exit"],"target_exit":r.get("target_exit"),"timed_out":r["timed_out"],"elapsed_seconds":time.monotonic()-t0,"run_dir":r["run_dir"],"stdout":stdout,"stderr":stderr,"run_valid":r["exit"]==0 and "VDSO_PROBE_PASS" in stdout}
(logs/"clock-test-receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
print(json.dumps(receipt,indent=2))
