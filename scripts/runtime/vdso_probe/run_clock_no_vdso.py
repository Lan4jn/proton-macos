import json,sys,time,hashlib
from pathlib import Path
lab=Path("/Users/mewcapoo/Projects/proton-macos-lab");sys.path.insert(0,str(lab));from scripts.backend.process import run_isolated
rt=lab/"sources/elfuse-vdso-derived/build/elfuse";root=lab/"fixtures/runtime/arch-case";probe=lab/"scripts/runtime/vdso_probe/clock_no_vdso_probe.py";out=lab/"logs/vdso/no-vdso-clock-test";out.mkdir(parents=True,exist_ok=True)
argv=[str(rt),"--user","501:20","--sysroot",str(root),"--timeout","12",str(root/"usr/bin/python3.14"),str(probe)]
t0=time.monotonic();r=run_isolated(argv,out,timeout=15,extra_env={"ELFUSE_DIAG_DISABLE_VDSO_AUXV":"1"})
stdout=Path(r["stdout"]).read_text(errors="replace");stderr=Path(r["stderr"]).read_text(errors="replace")
rec={"runtime_sha256":hashlib.sha256(rt.read_bytes()).hexdigest(),"probe_sha256":hashlib.sha256(probe.read_bytes()).hexdigest(),"exit_code":r["exit"],"target_exit":r.get("target_exit"),"timed_out":r["timed_out"],"elapsed_seconds":time.monotonic()-t0,"run_dir":r["run_dir"],"extra_env":{"ELFUSE_DIAG_DISABLE_VDSO_AUXV":"1"},"stdout":stdout,"stderr":stderr,"run_valid":r["exit"]==0 and "VDSO_DISABLE_PROBE_PASS" in stdout}
(lab/"logs/vdso/no-vdso-clock-receipt.json").write_text(json.dumps(rec,indent=2)+"\n");print(json.dumps(rec,indent=2))