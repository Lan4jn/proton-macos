import hashlib,json,shutil,sys,time
from pathlib import Path
sys.path.insert(0,"/Users/mewcapoo/Projects/proton-macos-lab")
from scripts.backend.process import run_isolated
lab=Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve();rt=lab/"sources/elfuse-once-panorama2-derived/build/elfuse";srcp=lab/"fixtures/runtime/futex-args-vulkan/pfx"
baseargv=json.loads((lab/"logs/vulkan-null-driver/result.json").read_text())["result"]["argv"]
extra={"ELFUSE_DIAG_SESSION_SHARED":"1","ELFUSE_IO_TRANSACTION_OBSERVE":"1","ELFUSE_FIXTURE_IDENTITY":"1","ELFUSE_FUTEX_OWNER_OBSERVE":"1","ELFUSE_FUTEX_TARGET_UADDR":"0x20102d440","ELFUSE_THREAD_LIFETIME_OBSERVE":"1","ELFUSE_ONCE_PANORAMA_OBSERVE":"1","ELFUSE_ONCE_COUNT_OBSERVE":"1","ELFUSE_ONCE_TRACE_OBSERVE":"1","ELFUSE_ONCE_COUNT_UADDR":"0x20102d440","ELFUSE_ONCE_TRACE_UADDR":"0x20102d440"}
root=lab/"logs/win32u-fix/moduletrace8";root.mkdir(parents=True,exist_ok=True);runs={}
for label in ("baseline-full","patched-full"):
 rd=root/label;rd.mkdir();pfx=rd/"pfx";shutil.copytree(srcp,pfx,symlinks=True)
 wine_root=lab/"sources/wine-win32u-experimental"/label/"files";wine=wine_root/"bin-arm64/wine";server=wine_root/"bin-arm64/wineserver";relay=str(wine_root/"lib/wine/aarch64-unix")+":"+str(wine_root/"lib/wine")
 argv=baseargv[:];argv[0]=str(rt)
 for i,a in enumerate(argv):
  if a.startswith("WINEPREFIX="):a="WINEPREFIX="+str(pfx)
  elif a.startswith("WINELOADER="):a="WINELOADER="+str(wine)
  elif a.startswith("WINESERVER="):a="WINESERVER="+str(server)
  elif a.startswith("WINEDEBUG="):a=a+",+loaddll"
  if a.startswith("unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;"):
   prefix="unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;"
   a=a.replace(prefix,prefix+" export LD_DEBUG=libs; export WINEDLLPATH='"+relay+"';",1)
   a=a.replace("/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wine",str(wine))
   oldlib="/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib"
   a=a.replace(oldlib,str(wine_root/"lib"))
  argv[i]=a
 start=time.monotonic();res=run_isolated(argv,rd,timeout=62,extra_env=extra);secs=time.monotonic()-start
 out=Path(res["stdout"]).read_text(errors="replace");err=Path(res["stderr"]).read_text(errors="replace")
 mod=str(wine_root/"lib/wine/aarch64-unix/win32u.so");msha=hashlib.sha256(Path(mod).read_bytes()).hexdigest()
 mlines=[x for x in err.splitlines() if mod in x and "calling init:" in x]
 steps=[x for x in out.splitlines() if "[WIN_ARM64_VK] Step " in x]
 once=[x for x in err.splitlines() if x.startswith("ONCE_ENTRY_COUNT") and "x0_uaddr=0x20102d440" in x]
 enter=[x for x in err.splitlines() if x.startswith("FUTEX_OWNER_ENTER") and "uaddr=0x20102d440" in x]
 ret=[x for x in out.splitlines() if "vkCreateInstance" in x and ("return" in x.lower() or "VK_SUCCESS" in x)]
 step4=[x for x in out.splitlines() if "Step 4" in x]
 rec={"label":label,"module_expected":mod,"module_sha256":msha,"module_load_lines":mlines,"module_load_confirmed":bool(mlines),"runtime_sha256":hashlib.sha256(rt.read_bytes()).hexdigest(),"probe_sha256":"d408405ca8340342a08e6e44ddaccc8ad78d25570bea5a523a4b10067a87dc08","wine_loader":str(wine),"wine_server":str(server),"winelldllpath":relay,"prefix":str(pfx),"prefix_source":str(srcp),"argv":argv,"extra_env":extra,"exit":res["exit"],"timed_out":res["timed_out"],"seconds":secs,"stdout_bytes":len(out.encode()),"stderr_bytes":len(err.encode()),"run_dir":res.get("run_dir",str(rd)),"steps":steps,"has_step3":any("Step 3" in x for x in steps),"has_step4":bool(step4),"target_once_entries":once,"target_once_entry_count":len(once),"same_target_futex_enters":enter,"same_target_futex_enter_count":len(enter),"inner_call_lr_0x200f3a3f8_count":sum("lr=0x200f3a3f8" in x for x in once),"vkCreateInstance_returned":bool(ret),"return_lines":ret,"stdout_tail":out.splitlines()[-20:]}
 rec["run_valid"]=bool(rec["has_step3"] and rec["same_target_futex_enter_count"]>0 and rec["module_load_confirmed"])
 runs[label]=rec;(rd/"receipt.json").write_text(json.dumps(rec,indent=2)+chr(10))
 print("===",label,"exit",rec["exit"],"valid",rec["run_valid"],"module loaded",rec["module_load_confirmed"],"module sha",msha)
 print("once entries",len(once),"target futex",len(enter),"inner LR count",rec["inner_call_lr_0x200f3a3f8_count"],"step4",bool(step4),"returns",ret)
 print("module evidence",mlines[:4]);print("run dir",rec["run_dir"])
comp={"experiment":"same runtime/probe/argv/environment/prefix source; only win32u.so differs by one patched BL->NOP; full derived module trees copy all aarch64-unix files","elfuse_sha256":hashlib.sha256(rt.read_bytes()).hexdigest(),"patch":{"offset":"0x13a3f4","before":"43d0fb97","after":"1f2003d5"},"runs":runs}
(root/"comparison.json").write_text(json.dumps(comp,indent=2)+chr(10));print("comparison",root/"comparison.json")
