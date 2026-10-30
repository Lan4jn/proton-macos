import re
#!/usr/bin/env python3
import hashlib,json,os,shutil,signal,subprocess,sys,time
from pathlib import Path
LAB=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(LAB))
from scripts.backend.steam_handoff import prepare_runtime_tool
from scripts.backend.steam_plan import generate_compatibility_tool_vdfs,create_compat_tool_plan,apply_installation_plan,verify_installation_manifest,rollback_installation_manifest,compute_tree_fingerprint
from scripts.runtime.vk_throughput.analyze import analyze
OUT=LAB/'logs/inproc-present'
def save(path,obj):path.write_text(json.dumps(obj,indent=2)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 label=sys.argv[1] if len(sys.argv)>1 else 'small'
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
 probe=LAB/'sources/inproc-present-dylib/frame_probe_arm64.exe'
 shutil.copy2(probe,prefix/'drive_c/frame_probe_arm64.exe')
 sysroot=LAB/'fixtures/runtime/arch-case';lvp=LAB/'fixtures/runtime/lavapipe-derived'
 diag={k:'1' for k in ['ELFUSE_DIAG_SESSION_SHARED','ELFUSE_IO_TRANSACTION_OBSERVE','ELFUSE_FIXTURE_IDENTITY','ELFUSE_FUTEX_OWNER_OBSERVE','ELFUSE_THREAD_LIFETIME_OBSERVE','ELFUSE_ONCE_PANORAMA_OBSERVE','ELFUSE_ONCE_COUNT_OBSERVE','ELFUSE_ONCE_TRACE_OBSERVE']}
 diag.update({'VK_ICD_FILENAMES':str(lvp/'usr/share/vulkan/icd.d/lvp_icd.json'),'WINEDEBUG':'+timestamp,+winstation,+vulkan,+explorer,+driver,warn+vulkan'})
 guest={'VK_LOADER_DEBUG':'all','LD_LIBRARY_PATH':str(lvp/'usr/lib')+':'+str(sysroot/'usr/lib'),'LP_NUM_THREADS':'1','VK_ICD_FILENAMES':str(lvp/'usr/share/vulkan/icd.d/lvp_icd.json')}
 if 'on' in label:
  diag.update({'ELFUSE_INPROC_PRESENT_DYLIB':str(LAB/'sources/inproc-present-dylib/present.dylib'),
    'ELFUSE_INPROC_PRESENT_GVA':'0x'+re.search(r'inproc_packet\s+([0-9A-Fa-f]+)',(LAB/'sources/inproc-present-dylib/frame_probe.map').read_text()).group(1),'ELFUSE_INPROC_PRESENT_WAIT_RANGE':'150','ELFUSE_INPROC_PRESENT_OUT':str(root)})
 if 'mainonly' in label:diag['ELFUSE_INPROC_PRESENT_MAIN_ONLY']='1'
 if 'on' in label:
  diag['ELFUSE_INPROC_PRESENT_FRAME_LAYOUT']='1'
  if '720' in label:diag.update({'ELFUSE_INPROC_PRESENT_WIDTH':'1280','ELFUSE_INPROC_PRESENT_HEIGHT':'720'})
 steam=root/'fixture-steam';steam.mkdir()
 prepare_runtime_tool(pkg,steam/'compatibilitytools.d',execute_runtime=True,
  elfuse_path=LAB/'sources/elfuse-inproc-present-derived/build/elfuse',sysroot=sysroot,prefix=prefix,
  runtime_bundle=pkg,logs_dir=root/'runtime-logs',guest_env=guest,diagnostic_env=diag,timeout=115.0)
 name='proton-window-x64';generate_compatibility_tool_vdfs(pkg,name,'Windows x64 Window Diagnostic',wrapper_rel_path='proton-wrapper.sh')
 before=compute_tree_fingerprint(steam);save(root/'fingerprint-before.json',before)
 plan=create_compat_tool_plan(steam,pkg,name);save(root/'installation-plan.json',plan)
 manifest=apply_installation_plan(plan,steam);save(root/'installation-manifest.json',manifest)
 valid,errors=verify_installation_manifest(manifest,steam)
 if not valid:raise ValueError(errors)
 dest=steam/'compatibilitytools.d'/name;pkg.rename(root/'source-MOVED')
 from scripts.backend.bundle import build_plan
 from scripts.backend.process import run_isolated
 args=[verb,'C:\\frame_probe_arm64.exe']+(['--1080p','--frames20'] if '1080' in label else ['--720p','--frames20'] if '720' in label else ['--360p','--frames20'] if '360' in label else ['--frames20'])
 if 'long' in label:args=[a for a in args if a!='--frames20']
 for count in [20,100,500]:
  if 'inst'+str(count) in label:args.append('--instances'+str(count))
 plan_runtime=build_plan(LAB/'artifacts/public-proton/bundle.json',sysroot,prefix,args,
   runtime_bundle=dest,linux_python=(sysroot/'usr/bin/python3').resolve(),elfuse_path=LAB/'sources/elfuse-inproc-present-derived/build/elfuse')
 if plan_runtime['status']!='PLAN_READY':raise ValueError(plan_runtime)
 argv=plan_runtime['argv'];argv[argv.index('--timeout')+1]='180'
 linux_py=str((sysroot/'usr/bin/python3').resolve());idx=argv.index(linux_py)
 env_args=[]
 for key,value in guest.items():env_args.extend(['--env',key+'='+value])
 argv[idx:idx]=env_args
 save(root/'runtime-plan.json',plan_runtime)
 start=time.monotonic();host_timeout=False
 try:
  env=dict(plan_runtime.get('env',{}));env.update(diag);env.pop('LD_LIBRARY_PATH',None)
  result=run_isolated(argv,root/'runtime-logs',timeout=200,extra_env=env)
  save(root/'execution-result.json',result)
  rc=result['exit'];host_timeout=result['timed_out']
  (root/'wrapper.stdout.log').write_text(json.dumps(result,indent=2));(root/'wrapper.stderr.log').write_text('')
  duration=time.monotonic()-start
  runs=sorted((root/'runtime-logs').glob('run-*'),key=lambda p:p.stat().st_mtime)
  run=runs[-1] if runs else None
  stdout=(run/'stdout.log').read_text(errors='replace') if run and (run/'stdout.log').exists() else ''
  stderr=(run/'stderr.log').read_text(errors='replace') if run and (run/'stderr.log').exists() else ''
  (root/'probe.stdout.log').write_text(stdout);(root/'probe.stderr.log').write_text(stderr)
  try:
   verdict=analyze(stdout) if rc==0 and not host_timeout else {'pass':False,'reason':'runtime incomplete','last_raw_stage':stdout.splitlines()[-1:]}
  except ValueError as e:verdict={'pass':False,'reason':str(e)}
  save(root/'statistics.json',verdict)
  wrapper_raw=(root/'wrapper.stdout.log').read_text()
  try:adapter=json.loads(wrapper_raw)
  except ValueError:adapter=None
  save(root/'timeline.json',verdict)
  save(root/'receipt.json',{'label':label,'duration_seconds':duration,'wrapper_exit':rc,'host_timeout':host_timeout,
   'runtime_timeout_seconds':180,'host_timeout_seconds':200,'argv':argv,'adapter_result':adapter,
   'probe_sha256':sha(probe),'gate':'1','cpu_caveat':'llvmpipe CPU real draw/fence, no hardware GPU claim',
   'diagnostic_env':diag,'guest_env':guest,'verdict':verdict,'source_moved':True,'runtime_log':str(run) if run else None})
  print(json.dumps({'duration_seconds':duration,'exit':rc,'timeline':verdict,'runtime_log':str(run)},indent=2))
 finally:
  rolled=rollback_installation_manifest(manifest,steam);save(root/'rollback.json',rolled)
  after=compute_tree_fingerprint(steam);save(root/'fingerprint-after.json',after)
  if rolled['status']!='success' or before!=after:raise ValueError('Rollback failed')
if __name__=='__main__':main()
