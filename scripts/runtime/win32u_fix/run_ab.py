import hashlib, json, shutil, sys, time
from pathlib import Path
sys.path.insert(0,"/Users/mewcapoo/Projects/proton-macos-lab")
from scripts.backend.process import run_isolated

lab=Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
rt=lab/"sources/elfuse-once-panorama2-derived/build/elfuse"
sysroot=lab/"fixtures/runtime/arch-case"
source_prefix=lab/"fixtures/runtime/futex-args-vulkan/pfx"
base_args_file=lab/"logs/vulkan-null-driver/result.json"
probe_sha="d408405ca8340342a08e6e44ddaccc8ad78d25570bea5a523a4b10067a87dc08"
source_module=lab/"artifacts/public-proton/extracted/root/.local/share/Steam/steamapps/common/Proton Experimental (ARM64)/files/lib/wine/aarch64-unix/win32u.so"
base_module_sha=hashlib.sha256(source_module.read_bytes()).hexdigest()

assert rt.exists(),rt
assert source_prefix.exists(),source_prefix
old=json.loads(base_args_file.read_text())['result']
base_argv=old['argv'][:]
base_argv[0]=str(rt)

extra_env={
 'ELFUSE_DIAG_SESSION_SHARED':'1',
 'ELFUSE_IO_TRANSACTION_OBSERVE':'1',
 'ELFUSE_FIXTURE_IDENTITY':'1',
 'ELFUSE_FUTEX_OWNER_OBSERVE':'1',
 'ELFUSE_FUTEX_TARGET_UADDR':'0x20102d440',
 'ELFUSE_THREAD_LIFETIME_OBSERVE':'1',
 'ELFUSE_ONCE_PANORAMA_OBSERVE':'1',
 'ELFUSE_ONCE_COUNT_OBSERVE':'1',
 'ELFUSE_ONCE_TRACE_OBSERVE':'1',
 'ELFUSE_ONCE_COUNT_UADDR':'0x20102d440',
 'ELFUSE_ONCE_TRACE_UADDR':'0x20102d440'
}
logs=lab/"logs/win32u-fix"
results={}
for label,moddir in [
 ("baseline",lab/"sources/wine-win32u-experimental/baseline/files/lib/wine/aarch64-unix"),
 ("patched",lab/"sources/wine-win32u-experimental/patched/files/lib/wine/aarch64-unix")]:
    root=logs/label
    root.mkdir(parents=True,exist_ok=True)
    pfx=root/"pfx"
    if pfx.exists(): raise RuntimeError(f"refuse overwrite prefix {pfx}")
    shutil.copytree(source_prefix,pfx,symlinks=True)
    argv=[]
    for a in base_argv:
        if a.startswith("WINEPREFIX="):
            argv.append("WINEPREFIX="+str(pfx))
        elif a.startswith("WINEDEBUG="):
            argv.append(a+",+loaddll")
        elif a.startswith("unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;"):
            a=a.replace(
             "/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix",
             "/sources/wine-win32u-experimental/"+label+"/files/lib/wine/aarch64-unix",1)
            argv.append(a)
        else:
            argv.append(a)
    print(f"\n=== {label.upper()} ===")
    print("override_module_dir:",moddir)
    print("override_module_sha256:",hashlib.sha256((moddir/"win32u.so").read_bytes()).hexdigest())
    print("prefix:",pfx,"source_prefix:",source_prefix)
    print("argv:",json.dumps(argv))
    print("env_overrides:",json.dumps(extra_env,sort_keys=True))
    start=time.monotonic()
    r=run_isolated(argv,root,timeout=62,extra_env=extra_env)
    elapsed=time.monotonic()-start
    out=Path(r['stdout']).read_text(errors='replace')
    err=Path(r['stderr']).read_text(errors='replace')
    outlines=out.splitlines()
    errlines=err.splitlines()
    steps=[x for x in outlines if '[WIN_ARM64_VK] Step ' in x]
    target_enter=[x for x in errlines if x.startswith('FUTEX_OWNER_ENTER') and 'uaddr=0x20102d440' in x]
    once_target=[x for x in errlines if 'ONCE_ENTRY_COUNT' in x and 'x0_uaddr=0x20102d440' in x]
    patch_lr=[x for x in errlines if 'ONCE_ENTRY_COUNT' in x and 'lr=0x200f3a3f8' in x]
    loaded=[x for x in errlines if 'win32u.so' in x or 'win32u.dll' in x or 'Loaded L"C:' in x]
    # Call-through behavior visible if Step3 completion marker / Step4 reached or Vulkan result markers.
    step4=[x for x in outlines if '[WIN_ARM64_VK] Step 4' in x]
    returns=[x for x in outlines if 'vkCreateInstance returned' in x or 'vkCreateInstance result' in x or 'VK_SUCCESS' in x]
    result={
     "label":label,"argv":argv,"extra_env":extra_env,"prefix":str(pfx),"prefix_source":str(source_prefix),
     "module_path_requested":str(moddir/"win32u.so"),"module_sha256":hashlib.sha256((moddir/"win32u.so").read_bytes()).hexdigest(),
     "exit_code":r['exit'],"timed_out":r['timed_out'],"seconds":elapsed,
     "stdout_bytes":len(out.encode()),"stderr_bytes":len(err.encode()),"run_dir":r.get("run_dir",str(root)),
     "step_markers":steps,"target_enter_count":len(target_enter),"target_enter_lines":target_enter,
     "target_once_entry_count":len(once_target),"target_once_entry_lines":once_target,
     "inner_patch_path_lr_0x200f3a3f8_count":len(patch_lr),"inner_patch_path_lr_lines":patch_lr,
     "module_load_lines":loaded[:100],"step4_markers":step4,"vkcreate_return_markers":returns,
     "stdout_tail":outlines[-30:],"diagnostic_note":"No implementation claim; this is a one-instruction causal experiment."
    }
    results[label]=result
    (root/"receipt.json").write_text(json.dumps(result,indent=2)+"\n")
    print("exit:",r['exit'],"timeout:",r['timed_out'],"seconds:",f"{elapsed:.3f}","stdout/stderr bytes:",result['stdout_bytes'],result['stderr_bytes'])
    print("Step markers:",steps)
    print("target once entries:",len(once_target),"target futex ENTER:",len(target_enter),"inner LR count:",len(patch_lr))
    print("step4:",step4,"vkcreate returns:",returns)
    print("run_dir:",result['run_dir'])

comparison={
 "experiment":"Task-106 one-instruction DIAGNOSTIC patch; baseline and patched use same elfuse runtime SHA, probe, argv template, extra env and independently cloned identical source prefix",
 "elfuse_runtime_sha256":hashlib.sha256(rt.read_bytes()).hexdigest(),
 "probe_sha256":probe_sha,
 "original_win32u_sha256":base_module_sha,
 "binary_patch":{"ELF_VA":"0x13a3f4","file_offset":"0x13a3f4","original_bytes":"43d0fb97","replacement_bytes":"1f2003d5","instruction":"BL pthread_once@plt -> NOP; causal test only"},
 "runs":results
}
comp_path=logs/"comparison.json"
comp_path.write_text(json.dumps(comparison,indent=2)+"\n")
print("\ncomparison:",comp_path)
