import json,shutil,sys,time
from pathlib import Path
sys.path.insert(0,"/Users/mewcapoo/Projects/proton-macos-lab")
from scripts.backend.process import run_isolated
lab=Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve();rt=lab/"sources/elfuse-once-panorama2-derived/build/elfuse";srcp=lab/"fixtures/runtime/futex-args-vulkan/pfx";root=lab/"logs/win32u-fix/moduletrace4/patched";root.mkdir(parents=True);pfx=root/"pfx";shutil.copytree(srcp,pfx,symlinks=True)
wr=lab/"sources/wine-win32u-experimental/patched/files";wine=wr/"bin-arm64/wine";server=wr/"bin-arm64/wineserver";old=json.loads((lab/"logs/vulkan-null-driver/result.json").read_text())["result"]["argv"];argv=old[:];argv[0]=str(rt)
for i,a in enumerate(argv):
 if a.startswith("WINEPREFIX="):a="WINEPREFIX="+str(pfx)
 elif a.startswith("WINELOADER="):a="WINELOADER="+str(wine)
 elif a.startswith("WINESERVER="):a="WINESERVER="+str(server)
 elif a.startswith("WINEDEBUG="):a=a+",+loaddll"
 elif a.startswith("--timeout"): pass
 if a.startswith("unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;"):
  a=a.replace("unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;","unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES; export LD_DEBUG=libs;",1)
  a=a.replace("/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wine",str(wine))
  a=a.replace("/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix",str(wr/"lib/wine/aarch64-unix"))
 argv[i]=a
# experiment WINEDLLPATH either arch-specific or root (combined); all other flags same
extra={"ELFUSE_DIAG_SESSION_SHARED":"1","ELFUSE_IO_TRANSACTION_OBSERVE":"1","ELFUSE_FIXTURE_IDENTITY":"1","ELFUSE_FUTEX_OWNER_OBSERVE":"1","ELFUSE_FUTEX_TARGET_UADDR":"0x20102d440","ELFUSE_THREAD_LIFETIME_OBSERVE":"1","ELFUSE_ONCE_PANORAMA_OBSERVE":"1","ELFUSE_ONCE_COUNT_OBSERVE":"1","ELFUSE_ONCE_TRACE_OBSERVE":"1","ELFUSE_ONCE_COUNT_UADDR":"0x20102d440","ELFUSE_ONCE_TRACE_UADDR":"0x20102d440","WINEDLLPATH":str(wr/"lib/wine/aarch64-unix")+":"+str(wr/"lib/wine")}
res=run_isolated(argv,root,timeout=15,extra_env=extra)
err=Path(res["stderr"]).read_text(errors="replace")
print("exit",res["exit"],"timeout",res["timed_out"],"stderr bytes",len(err.encode()))
print("win32u load records:")
for l in err.splitlines():
 if "win32u.so" in l or "win32u.dll" in l or "WINEDLLPATH" in l: print(l)
(root/"search_probe.json").write_text(json.dumps({"argv":argv,"extra_env":extra,"exit":res["exit"],"timed_out":res["timed_out"],"run_dir":res.get("run_dir"),"win32u_lines":[l for l in err.splitlines() if "win32u.so" in l or "win32u.dll" in l]},indent=2)+"\n")
