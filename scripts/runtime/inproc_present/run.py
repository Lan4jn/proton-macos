import json,os,sys,subprocess,re
from pathlib import Path
LAB=Path(__file__).resolve().parents[3];sys.path.insert(0,str(LAB))
from scripts.backend.process import run_isolated
OUT=LAB/'logs/inproc-present'
runtime=LAB/'sources/elfuse-inproc-present-derived/build/elfuse'
guest=LAB/'sources/inproc-present-dylib/guest'
label=sys.argv[1];mode=sys.argv[2]
symbols=subprocess.check_output(['/opt/homebrew/Cellar/llvm@21/21.1.8/bin/llvm-nm',str(guest)],text=True)
gva='0x'+re.search(r'([0-9a-fA-F]+) B packet',symbols).group(1)
root=OUT/label;root.mkdir(exist_ok=False)
argv=[str(runtime),'--user',str(os.getuid())+':'+str(os.getgid()),'--sysroot',str(LAB/'fixtures/runtime/arch-case'),'--timeout','25',str(guest)]
env={'ELFUSE_DIAG_SESSION_SHARED':'1'}
if mode!='off':env.update({'ELFUSE_INPROC_PRESENT_DYLIB':str(LAB/'sources/inproc-present-dylib/present.dylib'),
 'ELFUSE_INPROC_PRESENT_GVA':'0xffffffffffffe000' if mode=='invalid' else '0xdead0000' if mode=='invalidrange' else hex(int(gva,16)+8) if mode=='waitnotready' else hex(int(gva,16)+12288) if mode=='crossrange' else gva,'ELFUSE_INPROC_PRESENT_OUT':str(root)})
if mode=='waitnotready':env['ELFUSE_INPROC_PRESENT_WAIT_RANGE']='1'
if mode=='badlayout':env['ELFUSE_INPROC_PRESENT_FRAME_LAYOUT']='1'
if mode=='baddimensions':env['ELFUSE_INPROC_PRESENT_WIDTH']='0'
r=run_isolated(argv,root/'raw',timeout=30,extra_env=env)
(root/'receipt.json').write_text(json.dumps({'mode':mode,'env':env,'result':r},indent=2)+'\n')
print(json.dumps(r,indent=2))
