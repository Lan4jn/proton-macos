import hashlib, json, shutil, sys, time
from pathlib import Path
sys.path.insert(0,"/Users/mewcapoo/Projects/proton-macos-lab")
from scripts.backend.process import run_isolated
lab=Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
rt=lab/"sources/elfuse-once-panorama2-derived/build/elfuse"
sysroot=lab/"fixtures/runtime/arch-case"
srcp=lab/"fixtures/runtime/futex-args-vulkan/pfx"
old=json.loads((lab/"logs/vulkan-null-driver/result.json").read_text())["result"]["argv"]
extra={"ELFUSE_DIAG_SESSION_SHARED":"1","ELFUSE_IO_TRANSACTION_OBSERVE":"1","ELFUSE_FIXTURE_IDENTITY":"1","ELFUSE_FUTEX_OWNER_OBSERVE":"1","ELFUSE_FUTEX_TARGET_UADDR":"0x20102d440","ELFUSE_THREAD_LIFETIME_OBSERVE":"1","ELFUSE_ONCE_PANORAMA_OBSERVE":"1","ELFUSE_ONCE_COUNT_OBSERVE":"1","ELFUSE_ONCE_TRACE_OBSERVE":"1","ELFUSE_ONCE_COUNT_UADDR":"0x20102d440","ELFUSE_ONCE_TRACE_UADDR":"0x20102d440",}
root=lab/"logs/win32u-fix/moduletrace2"
root.mkdir(parents=True,exist_ok=True)
out={}
for label in ["baseline","patched"]:
  rd=root/label
  rd.mkdir(exist_ok=False)
  pfx=rd/"pfx"
  shutil.copytree(srcp,pfx,symlinks=True)
  moddir=lab/"sources/wine-win32u-experimental"/label/"files/lib/wine/aarch64-unix"
  argv=old[:]
  argv[0]=str(rt)
  for i,a in enumerate(argv):
    if a.startswith("WINEPREFIX="): argv[i]="WINEPREFIX="+str(pfx)
    if a.startswith("WINEDEBUG="): argv[i]=a+",+loaddll"
    if a.startswith("unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;"):
      a=a.replace("unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;", "unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES; export LD_DEBUG=libs;", 1)
      argv[i]=a.replace("/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix","/sources/wine-win32u-experimental/"+label+"/files/lib/wine/aarch64-unix",1)
  t=time.monotonic(); res=run_isolated(argv,rd,timeout=62,extra_env=extra); sec=time.monotonic()-t
  op=Path(res["stdout"]).read_text(errors="replace"); ep=Path(res["stderr"]).read_text(errors="replace")
  module_lines=[l for l in ep.splitlines() if "win32u.so" in l or "wine-win32u-experimental" in l or "calling init" in l and "win32u" in l.lower()]
  steps=[l for l in op.splitlines() if "[WIN_ARM64_VK] Step" in l]
  ent=[l for l in ep.splitlines() if "FUTEX_OWNER_ENTER" in l and "0x20102d440" in l]
  inner=[l for l in ep.splitlines() if "ONCE_ENTRY_COUNT" in l and "lr=0x200f3a3f8" in l]
  ret=[l for l in op.splitlines() if "vkCreateInstance" in l and ("return" in l.lower() or "VK_SUCCESS" in l)]
  record={"label":label,"module_path_requested":str(moddir/"win32u.so"),"module_sha256":hashlib.sha256((moddir/"win32u.so").read_bytes()).hexdigest(),"argv":argv,"extra_env":extra,"prefix":str(pfx),"prefix_source":str(srcp),"exit_code":res["exit"],"timed_out":res["timed_out"],"seconds":sec,"stdout_bytes":len(op.encode()),"stderr_bytes":len(ep.encode()),"run_dir":res.get("run_dir",str(rd)),"steps":steps,"target_enter_count":len(ent),"target_enter":ent,"inner_patch_path_lr_count":len(inner),"inner_patch_path_lr":inner,"loaded_module_lines":module_lines,"vkcreate_return_markers":ret,"stdout_tail":op.splitlines()[-15:]}
  out[label]=record
  (rd/"receipt.json").write_text(json.dumps(record,indent=2)+"\n")
  print("===",label,"exit",res["exit"],"timed_out",res["timed_out"],"===")
  print("steps",steps,"target_enter",len(ent),"inner_LR",len(inner),"return",ret)
  print("loaded_module_lines",module_lines[:20])
  print("run_dir",record["run_dir"],"stderr",record["stderr_bytes"])
comparison={"instrumentation_runtime_sha256":hashlib.sha256(rt.read_bytes()).hexdigest(),"common_probe_sha256":"d408405ca8340342a08e6e44ddaccc8ad78d25570bea5a523a4b10067a87dc08","paired_runs":out}
(root/"comparison.json").write_text(json.dumps(comparison,indent=2)+"\n")
print("comparison",root/"comparison.json")
