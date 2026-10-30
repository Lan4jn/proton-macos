import hashlib,json,shutil,sys,time
from pathlib import Path
sys.path.insert(0,"/Users/mewcapoo/Projects/proton-macos-lab")
from scripts.backend.process import run_isolated
lab=Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve(); rt=lab/"sources/elfuse-once-panorama2-derived/build/elfuse"; sysroot=lab/"fixtures/runtime/arch-case"; srcp=lab/"fixtures/runtime/futex-args-vulkan/pfx"
oldargv=json.loads((lab/"logs/vulkan-null-driver/result.json").read_text())["result"]["argv"]
extra_base={"ELFUSE_DIAG_SESSION_SHARED":"1","ELFUSE_IO_TRANSACTION_OBSERVE":"1","ELFUSE_FIXTURE_IDENTITY":"1","ELFUSE_FUTEX_OWNER_OBSERVE":"1","ELFUSE_FUTEX_TARGET_UADDR":"0x20102d440","ELFUSE_THREAD_LIFETIME_OBSERVE":"1","ELFUSE_ONCE_PANORAMA_OBSERVE":"1","ELFUSE_ONCE_COUNT_OBSERVE":"1","ELFUSE_ONCE_TRACE_OBSERVE":"1","ELFUSE_ONCE_COUNT_UADDR":"0x20102d440","ELFUSE_ONCE_TRACE_UADDR":"0x20102d440"}
root=lab/"logs/win32u-fix/winelldllpath"; root.mkdir(parents=True,exist_ok=True); runs={}
for label in ("baseline","patched"):
 rd=root/label; rd.mkdir(); pfx=rd/"pfx"; shutil.copytree(srcp,pfx,symlinks=True)
 wine_root=lab/"sources/wine-win32u-experimental"/label/"files"
 wineloader=wine_root/"bin-arm64/wine"; wineserver=wine_root/"bin-arm64/wineserver"
 env=dict(extra_base); env["WINEDLLPATH"]=str(wine_root/"lib/wine")+":"+str(lab/"fixtures/runtime/proton-derived/files/lib/wine")
 argv=oldargv[:]; argv[0]=str(rt)
 for i,a in enumerate(argv):
  if a.startswith("WINEPREFIX="): a="WINEPREFIX="+str(pfx)
  if a.startswith("WINESERVER="): a="WINESERVER="+str(wineserver)
  if a.startswith("WINELOADER="): a="WINELOADER="+str(wineloader)
  if a.startswith("WINEDEBUG="): a=a+",+loaddll"
  if a.startswith("unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;"):
   a=a.replace("unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;","unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES; export LD_DEBUG=libs;",1)
   a=a.replace("/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wine",str(wineloader))
   a=a.replace("/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix",str(wine_root/"lib/wine/aarch64-unix"))
   a=a.replace("/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib:/",str(wine_root/"lib")+":")
  argv[i]=a
 start=time.monotonic(); res=run_isolated(argv,rd,timeout=62,extra_env=env); secs=time.monotonic()-start
 out=Path(res["stdout"]).read_text(errors="replace"); err=Path(res["stderr"]).read_text(errors="replace")
 module=str(wine_root/"lib/wine/aarch64-unix/win32u.so"); modsha=hashlib.sha256(Path(module).read_bytes()).hexdigest()
 module_lines=[l for l in err.splitlines() if module in l and ("calling init:" in l or "trying file=" in l or "generating link map" in l)]
 steps=[l for l in out.splitlines() if "[WIN_ARM64_VK] Step " in l]
 once=[l for l in err.splitlines() if l.startswith("ONCE_ENTRY_COUNT") and "x0_uaddr=0x20102d440" in l]
 target=[l for l in err.splitlines() if l.startswith("FUTEX_OWNER_ENTER") and "uaddr=0x20102d440" in l]
 ret=[l for l in out.splitlines() if "vkCreateInstance" in l and ("return" in l.lower() or "VK_SUCCESS" in l)]
 step4=[l for l in out.splitlines() if "Step 4" in l]
 rec={"label":label,"runtime_sha256":hashlib.sha256(rt.read_bytes()).hexdigest(),"module_expected_path":module,"module_sha256":modsha,"wineloader":str(wineloader),"wineserver":str(wineserver),"WINEDLLPATH":env["WINEDLLPATH"],"prefix":str(pfx),"prefix_source":str(srcp),"argv":argv,"extra_env":env,"exit_code":res["exit"],"timed_out":res["timed_out"],"elapsed_sec":secs,"stdout_bytes":len(out.encode()),"stderr_bytes":len(err.encode()),"run_dir":res.get("run_dir",str(rd)),"step_markers":steps,"has_step3":any("Step 3" in x for x in steps),"has_step4":bool(step4),"target_once_entries":once,"target_once_entry_count":len(once),"target_futex_enter":target,"target_futex_enter_count":len(target),"inner_once_LR_0x200f3a3f8_count":sum("lr=0x200f3a3f8" in x for x in once),"module_load_evidence":module_lines,"module_load_confirmed":len(module_lines)>0,"vkCreateInstance_return_markers":ret,"stdout_tail":out.splitlines()[-20:],"stderr_tail_lines":err.splitlines()[-30:]}
 rec["run_valid"] = bool(rec["has_step3"] and rec["target_futex_enter_count"]>0 and rec["module_load_confirmed"])
 runs[label]=rec; (rd/"receipt.json").write_text(json.dumps(rec,indent=2)+"\n")
 print("===",label,"exit",rec["exit_code"],"valid",rec["run_valid"],"module_loaded",rec["module_load_confirmed"],"module_sha",modsha)
 print("steps",steps,"target_once",len(once),"innerLR",rec["inner_once_LR_0x200f3a3f8_count"],"targetENTER",len(target),"step4",bool(step4),"returns",ret)
 print("loaded:",module_lines[:4]); print("run_dir",rec["run_dir"],"stderr",rec["stderr_bytes"])
comparison={"pair_design":"same runtime, argv template, diagnostic env, cloned prefix source; only win32u.so differs by a single NOP at ELF VA/file offset 0x13a3f4; WINEDLLPATH points to derived package root first","patch":{"va":"0x13a3f4","file_offset":"0x13a3f4","original":"43d0fb97","replacement":"1f2003d5"},"runs":runs}
(root/"comparison.json").write_text(json.dumps(comparison,indent=2)+"\n")
print("comparison",root/"comparison.json")
