#!/usr/bin/env python3
import hashlib,json,os,shutil,signal,subprocess,sys,time
from pathlib import Path
LAB=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(LAB))
from scripts.backend.steam_handoff import prepare_runtime_tool
from scripts.backend.steam_plan import generate_compatibility_tool_vdfs,create_compat_tool_plan,apply_installation_plan,verify_installation_manifest,rollback_installation_manifest,compute_tree_fingerprint
from scripts.runtime.win_window.verify_timeline import analyze
OUT=LAB/'logs/win-window'
def save(path,obj):path.write_text(json.dumps(obj,indent=2)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 label=sys.argv[1] if len(sys.argv)>1 else 'baseline'
 if not label.replace('_','').isalnum():raise ValueError('Bad label')
 verb=sys.argv[2] if len(sys.argv)>2 else 'runinprefix'
 if verb not in ['run','runinprefix']:raise ValueError('Bad verb')
 root=OUT/label;root.mkdir(parents=True,exist_ok=False)
 pkg=root/'source';pkg.mkdir()
 files=pkg/'files'
 shutil.copytree(LAB/'sources/wine-win32u-experimental/patched-full/files',files,symlinks=True)
 share=files/'share'
 if share.is_symlink():share.unlink()
 elif share.exists():shutil.rmtree(share)
 shutil.copytree(LAB/'fixtures/runtime/proton-derived/files/share',share,symlinks=True)
 for name,source in [('win32u.so',LAB/'sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so'),('winevulkan.so',LAB/'fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/winevulkan.so')]:
  dest=files/'lib/wine/aarch64-unix'/name
  if dest.is_symlink():dest.unlink()
  elif dest.exists():dest.chmod(0o755);dest.unlink()
  shutil.copy2(source,dest)
 for name in ['proton','filelock.py','version']:shutil.copy2(LAB/'fixtures/runtime/proton-derived'/name,pkg/name)
 prefix=root/'compat/pfx';prefix.parent.mkdir()
 shutil.copytree(LAB/'fixtures/runtime/futex-args-vulkan/pfx',prefix,symlinks=True)
 probe=LAB/'sources/win-window-probe/window_x64.exe'
 shutil.copy2(probe,prefix/'drive_c/window_x64.exe')
 sysroot=LAB/'fixtures/runtime/arch-case';lvp=LAB/'fixtures/runtime/lavapipe-derived'
 diag={'ELFUSE_DIAG_SESSION_SHARED':'1','WINEDEBUG':'+timestamp,+winstation,+driver,+explorer,+x11drv,+waylanddrv'}
 guest={'LD_LIBRARY_PATH':str(lvp/'usr/lib')+':'+str(sysroot/'usr/lib'),'LP_NUM_THREADS':'1','VK_ICD_FILENAMES':str(lvp/'usr/share/vulkan/icd.d/lvp_icd.json')}
 steam=root/'fixture-steam';steam.mkdir()
 prepare_runtime_tool(pkg,steam/'compatibilitytools.d',execute_runtime=True,
  elfuse_path=LAB/'sources/elfuse-once-panorama2-derived/build/elfuse',sysroot=sysroot,prefix=prefix,
  runtime_bundle=pkg,logs_dir=root/'runtime-logs',guest_env=guest,diagnostic_env=diag,timeout=115.0)
 name='proton-window-x64';generate_compatibility_tool_vdfs(pkg,name,'Windows x64 Window Diagnostic',wrapper_rel_path='proton-wrapper.sh')
 before=compute_tree_fingerprint(steam);save(root/'fingerprint-before.json',before)
 plan=create_compat_tool_plan(steam,pkg,name);save(root/'installation-plan.json',plan)
 manifest=apply_installation_plan(plan,steam);save(root/'installation-manifest.json',manifest)
 valid,errors=verify_installation_manifest(manifest,steam)
 if not valid:raise ValueError(errors)
 dest=steam/'compatibilitytools.d'/name;pkg.rename(root/'source-MOVED')
 argv=[str(dest/'proton-wrapper.sh'),verb,'C:\\window_x64.exe']
 start=time.monotonic();host_timeout=False
 try:
  with (root/'wrapper.stdout.log').open('w') as out,(root/'wrapper.stderr.log').open('w') as err:
   p=subprocess.Popen(argv,stdout=out,stderr=err,start_new_session=True)
   try:rc=p.wait(timeout=125)
   except subprocess.TimeoutExpired:
    host_timeout=True;os.killpg(p.pid,signal.SIGTERM)
    try:rc=p.wait(timeout=3)
    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);rc=p.wait()
  duration=time.monotonic()-start
  runs=sorted((root/'runtime-logs').glob('run-*'),key=lambda p:p.stat().st_mtime)
  run=runs[-1] if runs else None
  stdout=(run/'stdout.log').read_text(errors='replace') if run and (run/'stdout.log').exists() else ''
  stderr=(run/'stderr.log').read_text(errors='replace') if run and (run/'stderr.log').exists() else ''
  (root/'probe.stdout.log').write_text(stdout);(root/'probe.stderr.log').write_text(stderr)
  verdict=analyze(stdout,rc,host_timeout or rc==124)
  wrapper_raw=(root/'wrapper.stdout.log').read_text()
  try:adapter=json.loads(wrapper_raw)
  except ValueError:adapter=None
  save(root/'timeline.json',verdict)
  save(root/'receipt.json',{'label':label,'duration_seconds':duration,'wrapper_exit':rc,'host_timeout':host_timeout,
   'runtime_timeout_seconds':115,'host_timeout_seconds':125,'argv':argv,'adapter_result':adapter,
   'probe_sha256':sha(probe),'gate':'1','cpu_caveat':'existing llvmpipe CPU baseline; this probe uses GDI, no hardware GPU claim',
   'diagnostic_env':diag,'guest_env':guest,'verdict':verdict,'source_moved':True,'runtime_log':str(run) if run else None})
  print(json.dumps({'duration_seconds':duration,'exit':rc,'timeline':verdict,'runtime_log':str(run)},indent=2))
 finally:
  rolled=rollback_installation_manifest(manifest,steam);save(root/'rollback.json',rolled)
  after=compute_tree_fingerprint(steam);save(root/'fingerprint-after.json',after)
  if rolled['status']!='success' or before!=after:raise ValueError('Rollback failed')
if __name__=='__main__':main()
