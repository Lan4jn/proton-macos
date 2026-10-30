import hashlib,json,shutil,sys,time,re
from pathlib import Path
lab=Path("/Users/mewcapoo/Projects/proton-macos-lab");sys.path.insert(0,str(lab));from scripts.backend.process import run_isolated
rt=lab/"sources/elfuse-x64block-derived/build/elfuse"; root=lab/"fixtures/runtime/arch-case"; bundle=lab/"fixtures/runtime/proton-derived"; probe=lab/"scripts/runtime/x64_vk/vk_enum_x64.exe"; srcp=lab/"fixtures/runtime/futex-args-vulkan/pfx"; out=lab/"logs/x64-block/sampled-read-identity"; shutil.rmtree(out,ignore_errors=True); out.mkdir(parents=True); pfx=out/"pfx"; shutil.copytree(srcp,pfx,symlinks=True); shutil.copyfile(probe,pfx/"drive_c/vk_enum_x64.exe")
old=json.loads((lab/"logs/vulkan-null-driver/result.json").read_text()); argv=old["result"]["argv"][:]; argv[0]=str(rt); argv=[("WINEPREFIX="+str(pfx)) if x.startswith("WINEPREFIX=") else x.replace("vk_enum_arm64.exe","vk_enum_x64.exe") for x in argv]
for i in range(len(argv)-1):
 if argv[i] == "--env" and argv[i+1].startswith("WINEDEBUG="):
  argv[i+1] = "WINEDEBUG=+timestamp,+process,+winstation,+vulkan,+explorer,+driver,+seh,+loaddll"
env={"ELFUSE_DIAG_SESSION_SHARED":"1","ELFUSE_IO_TRANSACTION_OBSERVE":"1","ELFUSE_FIXTURE_IDENTITY":"1","ELFUSE_FUTEX_OWNER_OBSERVE":"1","ELFUSE_FUTEX_TARGET_UADDR":"0x20102d440","ELFUSE_THREAD_LIFETIME_OBSERVE":"1","ELFUSE_ONCE_PANORAMA_OBSERVE":"1","ELFUSE_ONCE_COUNT_OBSERVE":"1","ELFUSE_ONCE_TRACE_OBSERVE":"1","ELFUSE_ONCE_COUNT_UADDR":"0x20102d440","ELFUSE_ONCE_TRACE_UADDR":"0x20102d440","ELFUSE_DIAG_DISABLE_VDSO_AUXV":"1","ELFUSE_X64BLOCK_SAMPLE":"1","WINEDEBUG":"+timestamp,+process,+winstation,+vulkan,+explorer,+driver,+seh,+loaddll"}
start=time.monotonic(); r=run_isolated(argv,out,timeout=25,extra_env=env); elapsed=time.monotonic()-start; stdout=Path(r["stdout"]).read_text(errors="replace"); stderr=Path(r["stderr"]).read_text(errors="replace");
proc_lines=[ln for ln in stderr.splitlines() if re.search(r"trace:process|warn:process|err:process|create_process|CreateProcess",ln,re.I)]
pe_lines=[ln for ln in stderr.splitlines() if "vk_enum_x64.exe" in ln.lower()]
step1="[WIN_X64_VK] Step 1: Calling LoadLibraryA(\"vulkan-1.dll\")..." in stdout
step3="[WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)..." in stdout
# Map syscall numbers to names for observed syscall samples
scmap={63:"read",64:"write",72:"pselect6",73:"ppoll",98:"futex",56:"openat",57:"close",62:"lseek",93:"exit",94:"exit_group",96:"set_tid_address",98:"futex",129:"kill",131:"tgkill",172:"getpid",174:"getuid",198:"socket",200:"bind",202:"accept",203:"connect",204:"getsockname",207:"sendto",206:"recvfrom",221:"execve",220:"clone",435:"clone3"}
enter_lines=[ln for ln in stderr.splitlines() if "THREAD_LIFETIME_ENTER" in ln]
snapshots=[ln for ln in stderr.splitlines() if "THREAD_SNAPSHOT_BEGIN" in ln or "FUTEX_OWNER_THREAD" in ln]
# compact process/thread/syscall summary from observed enter records
per_pid={}
for ln in enter_lines:
 m=re.search(r"pid=(\d+) gtid=(-?\d+) nr=(\d+) sc=([^ ]+)",ln)
 if not m: continue
 pid,gtid,nr,sc=m.groups(); row=per_pid.setdefault(pid,{"guest_tids":set(),"syscalls":{}}); row["guest_tids"].add(gtid); row["syscalls"][sc]=row["syscalls"].get(sc,0)+1
per_pid_json={pid:{"guest_tids":sorted(d["guest_tids"],key=lambda s:int(s)),"syscall_counts":d["syscalls"]} for pid,d in per_pid.items()}
receipt={"runtime_sha256":hashlib.sha256(rt.read_bytes()).hexdigest(),"probe_sha256":hashlib.sha256(probe.read_bytes()).hexdigest(),"run_valid":False,"has_step1":step1,"has_step3":step3,"exit_code":r["exit"],"timed_out":r["timed_out"],"elapsed_seconds":elapsed,"stdout_bytes":len(stdout.encode()),"stderr_bytes":len(stderr.encode()),"run_dir":r["run_dir"],"extra_env":{"ELFUSE_DIAG_DISABLE_VDSO_AUXV":"1","ELFUSE_X64BLOCK_SAMPLE":"1","WINEDEBUG":env["WINEDEBUG"]},"stdout":stdout,"wine_process_trace_lines":proc_lines[:300],"x64_probe_mentions":pe_lines[:100],"guest_process_syscall_summary":per_pid_json,"lifetime_enter_samples":enter_lines[:500],"snapshot_samples":snapshots[-250:],"target_once_calls":[ln for ln in stderr.splitlines() if "ONCE_ENTRY_COUNT" in ln and "0x20102d440" in ln],"target_futex_enters":[ln for ln in stderr.splitlines() if "FUTEX_OWNER_ENTER" in ln and "uaddr=0x20102d440" in ln]}
(out/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n"); print(json.dumps({k:v for k,v in receipt.items() if k not in ("lifetime_enter_samples","snapshot_samples","wine_process_trace_lines","x64_probe_mentions","stdout")},indent=2)); print("--- stdout ---"); print(stdout); print("--- process trace sample ---"); print("\n".join(proc_lines[:40])); print("--- x64 PE mentions ---"); print("\n".join(pe_lines[:30])); print("--- process syscalls ---"); print(json.dumps(per_pid_json,indent=2)); print("--- final snapshots ---"); print("\n".join(snapshots[-40:]))