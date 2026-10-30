#!/usr/bin/env python3
"""Offline compatibility package builder; no actual Steam integration verdict."""
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
LAB=Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path: sys.path.insert(0,str(LAB))
OUT=LAB/'logs/compat-package'
NAME='proton-macos-lab-arm64-diag'
DISPLAY='Proton macOS Lab ARM64 (Diagnostic CPU Vulkan)'
PATCH_SHA='59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed'
VK_SHA='2786ca6f5f440821972e91a371e609d2d482597a8b6d75bcf02e287f83eea9ab'
PACKAGE=OUT/NAME

def parse_vdf(text):
    """Independent strict KeyValues subset: strings, braces, // comments, escapes."""
    tokens=[];i=0
    while i<len(text):
        if text[i].isspace(): i+=1;continue
        if text.startswith('//',i):
            e=text.find('\n',i);i=len(text) if e<0 else e+1;continue
        if text[i] in '{}':tokens.append(text[i]);i+=1;continue
        if text[i]!='"':raise ValueError('Expected quoted VDF string')
        i+=1;value=[]
        while i<len(text) and text[i]!='"':
            if text[i]=='\\':
                i+=1
                if i>=len(text):raise ValueError('Truncated VDF escape')
                if text[i] not in ['"','\\']:raise ValueError('Unsupported VDF escape')
            value.append(text[i]);i+=1
        if i>=len(text):raise ValueError('Unterminated VDF string')
        tokens.append(('string',''.join(value)));i+=1
    position=0
    def pairs(nested=False):
        nonlocal position
        result={}
        while position<len(tokens):
            token=tokens[position]
            if token=='}':
                if not nested:raise ValueError('Unexpected closing brace')
                position+=1;return result
            if not isinstance(token,tuple):raise ValueError('Expected key')
            key=token[1];position+=1
            if key in result:raise ValueError('Duplicate VDF key')
            if position>=len(tokens):raise ValueError('Missing VDF value')
            value=tokens[position];position+=1
            if value=='{': result[key]=pairs(True)
            elif isinstance(value,tuple):result[key]=value[1]
            else:raise ValueError('Unexpected VDF token')
        if nested:raise ValueError('Missing closing brace')
        return result
    return pairs()

def validate_tool(root):
    root=Path(root).resolve()
    try:
        tools=parse_vdf((root/'compatibilitytool.vdf').read_text())['compatibilitytools']['compat_tools']
        manifest=parse_vdf((root/'toolmanifest.vdf').read_text())['manifest']
        if len(tools)!=1:raise ValueError('Expected exactly one tool')
        name,entry=next(iter(tools.items()))
        for key,value in [('install_path','.'),('from_oslist','windows'),('to_oslist','macos')]:
            if entry.get(key)!=value:raise ValueError('Invalid '+key)
        if not entry.get('display_name'):raise ValueError('Missing display_name')
        if manifest.get('version')!='2':raise ValueError('Invalid manifest version')
        cmd=shlex.split(manifest['commandline'])
        if cmd!=['/proton-wrapper.sh','--','%verb%']:raise ValueError('Invalid tool-relative commandline/%verb%')
        if not os.access(root/'proton-wrapper.sh',os.X_OK):raise ValueError('Wrapper is not executable')
    except (KeyError,OSError,TypeError) as e:raise ValueError('Invalid tool layout: '+str(e)) from e
    return {'tool_name':name,'directory':str(root),'fields':entry,'manifest':manifest,'resolved_wrapper':str(root/'proton-wrapper.sh')}

def scan_tools(root):
    """Offline approximation only; does not execute or reproduce closed Steam client."""
    results=[]
    for directory in sorted(Path(root).iterdir()):
        if not directory.is_dir() or directory.is_symlink():continue
        try:results.append(validate_tool(directory))
        except ValueError:continue
    return results

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def inventory(root):
    root=Path(root).resolve();files={}
    for base,dirs,names in os.walk(root):
        dirs.sort()
        for name in sorted(dirs+names):
            p=Path(base)/name;rel=p.relative_to(root).as_posix()
            if rel=='SHA256SUMS.json':continue
            mode=oct(stat.S_IMODE(p.lstat().st_mode))
            if p.is_symlink():
                if not p.resolve().is_relative_to(root) or not p.exists():raise ValueError('External or broken symlink: '+rel)
                files[rel]={'kind':'symlink','target':os.readlink(p),'sha256':hashlib.sha256(os.readlink(p).encode()).hexdigest()}
            elif p.is_file():files[rel]={'kind':'file','sha256':digest(p),'size':p.stat().st_size,'mode':mode}
    return files

def verify_package(root):
    root=Path(root).resolve()
    expected=json.loads((root/'SHA256SUMS.json').read_text())
    actual=inventory(root)
    if actual!=expected:
        differences=[k for k in set(actual)|set(expected) if actual.get(k)!=expected.get(k)]
        raise ValueError('Package inventory mismatch: '+str(sorted(differences)[:10]))
    return {'inventory_matches':True,'entries':len(actual),'regular_files':sum(x['kind']=='file' for x in actual.values()),'symlinks':sum(x['kind']=='symlink' for x in actual.values())}

class PackageTests(unittest.TestCase):
    def test_nested_and_escaped_vdf(self):
        self.assertEqual(parse_vdf('"manifest" { "commandline" "\\\"/wrapper\\\" -- %verb%" }')['manifest']['commandline'],'"/wrapper" -- %verb%')
    def test_duplicate_and_truncated_vdf(self):
        for text in ['"a" { "x" "1" "x" "2" }','"a" { "x"','"a" { } trailing']:
            with self.assertRaises(ValueError): parse_vdf(text)
    def test_scan_ignores_non_tools_and_bad_vdf(self):
        from scripts.backend.steam_plan import generate_compatibility_tool_vdfs
        OUT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=OUT) as d:
            root=Path(d);good=root/'good';good.mkdir()
            generate_compatibility_tool_vdfs(good,NAME,DISPLAY,wrapper_rel_path='proton-wrapper.sh')
            (good/'proton-wrapper.sh').write_text('#!/bin/sh\n');(good/'proton-wrapper.sh').chmod(0o755)
            (root/'not-a-tool').mkdir();(root/'bad').mkdir();(root/'bad/compatibilitytool.vdf').write_text('"a" {')
            self.assertEqual([x['tool_name'] for x in scan_tools(root)],[NAME])
    def test_invalid_oslist_or_absolute_source_command_fails(self):
        from scripts.backend.steam_plan import generate_compatibility_tool_vdfs
        OUT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=OUT) as d:
            root=Path(d)
            generate_compatibility_tool_vdfs(root,NAME,DISPLAY,wrapper_rel_path='proton-wrapper.sh')
            wrapper=root/'proton-wrapper.sh';wrapper.write_text('#!/bin/sh\n');wrapper.chmod(0o755)
            compat=root/'compatibilitytool.vdf';valid=compat.read_text()
            compat.write_text(valid.replace('"windows"','"linux"'))
            with self.assertRaises(ValueError):validate_tool(root)
            compat.write_text(valid)
            manifest=root/'toolmanifest.vdf'
            manifest.write_text(manifest.read_text().replace('/proton-wrapper.sh','/source/absolute/proton-wrapper.sh'))
            with self.assertRaises(ValueError):validate_tool(root)
    def test_materialized_file_link_keeps_bytes(self):
        OUT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=OUT) as d:
            root=Path(d);(root/'payload').write_bytes(b'known payload')
            link=root/'alias';link.symlink_to('payload')
            self.assertEqual(materialize_file_links(root),1)
            self.assertFalse(link.is_symlink());self.assertEqual(link.read_bytes(),b'known payload')
    def test_tampered_manifest_fails(self):
        OUT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=OUT) as d:
            root=Path(d);(root/'payload').write_text('first')
            expected=inventory(root);(root/'SHA256SUMS.json').write_text(json.dumps(expected))
            (root/'payload').write_text('changed')
            with self.assertRaises(ValueError): verify_package(root)
    def test_external_symlink_fails(self):
        OUT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=OUT) as d:
            root=Path(d);(root/'escape').symlink_to('/usr/bin/python3')
            with self.assertRaises(ValueError): inventory(root)


def save(path,data):
    Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')

def offline_path(path):
    p=Path(path).resolve()
    if not p.is_relative_to(OUT.resolve()) or p==OUT.resolve():raise ValueError('Writes limited to '+str(OUT))
    return p

def materialize_file_links(root):
    # Existing installer preserves directory links but dereferences file links.
    root=Path(root).resolve();count=0
    for base,dirs,names in os.walk(root):
        for name in names:
            path=Path(base)/name
            if path.is_symlink():
                target=path.resolve()
                if not target.is_relative_to(root):raise ValueError('External payload link')
                data=path.read_bytes();mode=stat.S_IMODE(path.stat().st_mode)
                path.unlink();path.write_bytes(data);path.chmod(mode);count+=1
    return count

def build_package():
    from scripts.backend.steam_handoff import prepare_runtime_tool
    from scripts.backend.steam_plan import generate_compatibility_tool_vdfs
    OUT.mkdir(parents=True,exist_ok=True)
    if PACKAGE.exists():raise ValueError('Package exists; preserve it and use verify/e2e')
    official=LAB/'fixtures/runtime/proton-derived'
    patch=LAB/'sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so'
    if digest(patch)!=PATCH_SHA:raise ValueError('Patch SHA mismatch')
    shutil.copytree(official/'files',PACKAGE/'files',symlinks=True)
    materialize_file_links(PACKAGE)
    for path in official.iterdir():
        if path.is_file() and path.name not in ['dist.lock','toolmanifest.vdf']:shutil.copy2(path,PACKAGE/path.name)
    dst=PACKAGE/'files/lib/wine/aarch64-unix/win32u.so'
    if dst.is_symlink():dst.unlink()
    if dst.exists():dst.chmod(0o755)
    shutil.copy2(patch,dst)
    if digest(PACKAGE/'files/lib/wine/aarch64-unix/winevulkan.so')!=VK_SHA:raise ValueError('winevulkan SHA mismatch')
    prefix=OUT/'compat-data/pfx'
    if not prefix.exists():shutil.copytree(LAB/'fixtures/runtime/futex-args-vulkan/pfx',prefix,symlinks=True)
    runtime=LAB/'sources/elfuse-once-panorama2-derived/build/elfuse'
    sysroot=LAB/'fixtures/runtime/arch-case';lavapipe=LAB/'fixtures/runtime/lavapipe-derived'
    prepare_runtime_tool(PACKAGE,OUT/'sandbox-steam/compatibilitytools.d',execute_runtime=True,
        elfuse_path=runtime,sysroot=sysroot,prefix=prefix,linux_python=sysroot/'usr/bin/python3',
        runtime_bundle=PACKAGE,logs_dir=OUT/'runtime-logs',timeout=110.0,
        guest_env={'LD_LIBRARY_PATH':str(lavapipe/'usr/lib')+':'+str(sysroot/'usr/lib'),
            'LP_NUM_THREADS':'1','VK_ICD_FILENAMES':str(lavapipe/'usr/share/vulkan/icd.d/lvp_icd.json')},
        diagnostic_env={'ELFUSE_DIAG_SESSION_SHARED':'1'})
    adapter=LAB/'scripts/backend/steam_handoff.py'
    wrapper='\n'.join(['#!/bin/sh','set -eu','DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
        'unset LD_PRELOAD LD_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH',
        'if [ "$#" -gt 0 ] && [ "$1" = "--" ]; then shift; fi',
        'exec '+shlex.quote(sys.executable)+' '+shlex.quote(str(adapter))+' --config "$DIR/config.json" -- "$@"',''])
    (PACKAGE/'proton-wrapper.sh').write_text(wrapper);(PACKAGE/'proton-wrapper.sh').chmod(0o755)
    generate_compatibility_tool_vdfs(PACKAGE,NAME,DISPLAY,wrapper_rel_path='proton-wrapper.sh')
    unused=PACKAGE/'install-plan.json'
    if unused.exists():unused.unlink()
    external={'package_scope':'Wine/Proton payload,VDF,wrapper,config bundled; host runtime external',
        'host_python':{'path':sys.executable,'sha256':digest(sys.executable)},'host_shell':'/bin/sh',
        'adapter_workspace':{'root':str(LAB),'required_files':{str(q.relative_to(LAB)):digest(q) for q in
            [adapter,LAB/'scripts/backend/bundle.py',LAB/'scripts/backend/process.py',LAB/'scripts/backend/supervisor.py']}},
        'elfuse':{'path':str(runtime),'sha256':digest(runtime),'requirements':'Apple Silicon macOS Hypervisor; diagnostic shared mapping enabled'},
        'linux_sysroot':str(sysroot),'linux_python':str(sysroot/'usr/bin/python3'),
        'lavapipe_icd':str(lavapipe/'usr/share/vulkan/icd.d/lvp_icd.json'),'lavapipe_libraries':str(lavapipe/'usr/lib'),
        'bundle_manifest':str(LAB/'artifacts/public-proton/bundle.json'),
        'mutable_prefix':str(prefix),'mutable_logs':str(OUT/'runtime-logs'),
        'limits':['Existing adapter requires lab-local paths; not standalone across machines',
            'Prefix fixed to fixture, not selected from Steam app id','Real Steam discovery/launch UNKNOWN',
            'Diagnostic gate changes private COW semantics','x64 graphics not proven by ARM64 package']}
    save(PACKAGE/'external-dependencies.json',external)
    save(PACKAGE/'SHA256SUMS.json',inventory(PACKAGE))
    result={'package':str(PACKAGE),'validation':verify_package(PACKAGE),'vdf':validate_tool(PACKAGE),
        'win32u_sha256':digest(dst),'winevulkan_sha256':digest(PACKAGE/'files/lib/wine/aarch64-unix/winevulkan.so'),
        'default_pfx_arm64':(PACKAGE/'files/share/default_pfx_arm64').is_dir(),
        'real_steam_discovery':'UNKNOWN','real_steam_launch':'UNKNOWN'}
    save(OUT/'build-result.json',result);print(json.dumps(result,indent=2))

def install(package,root,manifest_path):
    from scripts.backend.steam_plan import create_compat_tool_plan,apply_installation_plan,verify_installation_manifest
    package=offline_path(package);root=offline_path(root);manifest_path=offline_path(manifest_path)
    verify_package(package);validate_tool(package);root.mkdir(parents=True,exist_ok=True)
    if manifest_path.exists():raise ValueError('Keep existing install manifest')
    plan=create_compat_tool_plan(root,package,NAME,DISPLAY)
    save(manifest_path.with_suffix('.plan.json'),plan)
    manifest=apply_installation_plan(plan,root);save(manifest_path,manifest)
    valid,errors=verify_installation_manifest(manifest,root)
    if not valid:raise ValueError(errors)
    installed=root/'compatibilitytools.d'/NAME;verify_package(installed)
    expected=json.loads((installed/'SHA256SUMS.json').read_text())
    indexed={str(Path(x['path']).relative_to(installed)):x for x in manifest['installed_files']}
    for rel,entry in expected.items():
        actual=indexed[rel]
        if entry['kind']=='file' and actual['sha256']!=entry['sha256']:raise ValueError('Manifest hash mismatch: '+rel)
        if entry['kind']=='symlink' and actual['sha256']!='symlink':raise ValueError('Link manifest mismatch')
    if set(indexed)!=set(expected)|{'SHA256SUMS.json'}:raise ValueError('Manifest path set mismatch')
    return manifest,{'status':'INSTALLED_OFFLINE','verified':valid,'manifest_entries':len(indexed),'package_manifest_matches_install_manifest':True}

def rollback(manifest_path,root):
    from scripts.backend.steam_plan import rollback_installation_manifest
    root=offline_path(root);manifest_path=offline_path(manifest_path)
    result=rollback_installation_manifest(json.loads(manifest_path.read_text()),root)
    if result['status']!='success':raise ValueError(result['errors'])
    return result

def e2e():
    from scripts.backend.steam_plan import compute_tree_fingerprint
    root=OUT/'sandbox-steam';root.mkdir(parents=True,exist_ok=True)
    marker=root/'unrelated-marker.txt'
    if not marker.exists():marker.write_text('outside tool; retain after rollback\n')
    discovery=root/'compatibilitytools.d';discovery.mkdir(exist_ok=True)
    (discovery/'not-a-tool').mkdir(exist_ok=True)
    bad=discovery/'malformed';bad.mkdir(exist_ok=True);(bad/'compatibilitytool.vdf').write_text('"broken" {')
    before=compute_tree_fingerprint(root);save(OUT/'fingerprint-before.json',before)
    manifest_path=OUT/'installation-manifest.json'
    manifest,installed_result=install(PACKAGE,root,manifest_path)
    destination=discovery/NAME
    scanned=scan_tools(discovery)
    if [x['tool_name'] for x in scanned]!=[NAME]:raise ValueError('Discovery simulation mismatch')
    save(OUT/'scan-result.json',{'tools':scanned,'ignored':['not-a-tool','malformed'],'model_only':True})
    moved=OUT/(NAME+'-MOVED')
    if moved.exists():raise ValueError('Refuse overwrite moved source')
    offline_path(PACKAGE);offline_path(moved);PACKAGE.rename(moved)
    try:
        if PACKAGE.exists():raise ValueError('Source was not moved')
        argv=[str(destination/'proton-wrapper.sh'),'--','invalid-offline-verb']
        p=subprocess.run(argv,capture_output=True,text=True,timeout=10)
        save(OUT/'installed-wrapper-check.json',{'argv':argv,'exit_code':p.returncode,
            'stdout':p.stdout,'stderr':p.stderr,'source_absent':True,'runtime_execution_performed':False,
            'meaning':'relocated wrapper reaches adapter; invalid verb blocked before runtime'})
        if p.returncode!=2 or 'Unknown or unsupported Steam verb' not in p.stderr:raise ValueError('Installed wrapper check failed')
        # Positive config/plan check only: alternate config explicitly disables execution.
        cfg=json.loads((destination/'config.json').read_text());cfg['execute_runtime']=False
        temp_config=destination/'offline-plan-config.json'
        save(temp_config,cfg)
        try:
            plan_call=subprocess.run([sys.executable,str(LAB/'scripts/backend/steam_handoff.py'),
                '--config',str(temp_config),'--','runinprefix','C:\\offline-package-probe.exe'],
                capture_output=True,text=True,timeout=15)
            save(OUT/'installed-plan-check.json',{'exit_code':plan_call.returncode,
                'source_absent':True,'execution_performed':False,'stdout':plan_call.stdout,'stderr':plan_call.stderr})
            if plan_call.returncode!=0 or json.loads(plan_call.stdout).get('status')!='PLAN_READY':
                raise ValueError('Installed positive plan check failed')
        finally:temp_config.unlink()
        save(OUT/'installed-vdf.json',validate_tool(destination))
        installed_validation=verify_package(destination)
    finally:
        moved.rename(PACKAGE)
        rolled=rollback(manifest_path,root);save(OUT/'rollback-result.json',rolled)
    after=compute_tree_fingerprint(root);save(OUT/'fingerprint-after.json',after)
    if before!=after or destination.exists():raise ValueError('Rollback fingerprint mismatch')
    sums=json.loads((PACKAGE/'SHA256SUMS.json').read_text())
    save(OUT/'package-tree.json',{'root':str(PACKAGE),'entries':list(sums),'sha_index':'SHA256SUMS.json'})
    receipt={'status':'OFFLINE_PACKAGE_VERIFIED','package':str(PACKAGE),'install':installed_result,
        'installed_package':installed_validation,'source_moved_wrapper_check':True,
        'rollback_status':rolled['status'],'rollback_fingerprint_equal':True,
        'scan_model_pass':True,'vdf_independent_parser_pass':True,'real_steam_discovery':'UNKNOWN',
        'real_steam_launch':'UNKNOWN','runtime_execution_this_task':False,'installed_positive_plan_ready':True,
        'sha256_manifest':digest(PACKAGE/'SHA256SUMS.json'),'production_ntdll_not_used':True}
    save(OUT/'receipt.json',receipt);print(json.dumps(receipt,indent=2))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['test','build','verify','scan','e2e','install','rollback'])
    parser.add_argument('--root',type=Path,default=OUT/'manual-offline-steam')
    parser.add_argument('--manifest',type=Path,default=OUT/'manual-installation.json')
    args=parser.parse_args()
    if args.command=='test':
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PackageTests));return 0 if result.wasSuccessful() else 1
    if args.command=='build':build_package()
    elif args.command=='verify':print(json.dumps(verify_package(PACKAGE),indent=2))
    elif args.command=='scan':print(json.dumps(scan_tools(args.root),indent=2))
    elif args.command=='e2e':e2e()
    elif args.command=='install':print(json.dumps(install(PACKAGE,args.root,args.manifest)[1],indent=2))
    elif args.command=='rollback':
        result=rollback(args.manifest,args.root);print(json.dumps({'status':result['status'],'files_removed':len(result['files_removed']),'errors':result['errors']},indent=2))
    return 0

if __name__=='__main__':
    sys.exit(main())
