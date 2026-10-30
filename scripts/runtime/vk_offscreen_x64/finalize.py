import json,hashlib,struct,zlib,sys,platform
from pathlib import Path
LAB=Path('/Users/mewcapoo/Projects/proton-macos-lab'); sys.path.insert(0,str(LAB))
from scripts.runtime.vk_offscreen.verify_pixels import verify_framebuffer,run_negative_tests
from scripts.backend.steam_plan import compute_tree_fingerprint
D=LAB/'logs/vk-offscreen-x64'; j=json.loads((D/'receipt.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=(D/'normal_framebuffer.raw').read_bytes(); ok,details=verify_framebuffer(b);assert ok
assert j['runs']['skip_draw']['wrapper_exit']==21 and j['runs']['skip_draw']['negative_pass']
assert j['runs']['normal']['wrapper_exit']==0
chunk=lambda k,v:struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
png=b'\x89PNG\r\n\x1a\n' # replaced below using bytes to avoid quoting ambiguity
png=bytes([137,80,78,71,13,10,26,10])+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(bytes([0])+b[y*256:(y+1)*256] for y in range(64))))+chunk(b'IEND',b'')
(D/'normal_framebuffer.png').write_bytes(png)
files=['sources/vk-offscreen-probe/vk_offscreen_arm64.exe','sources/vk-offscreen-x64/vk_offscreen_x64.exe','sources/vk-offscreen-x64/vk_offscreen_x64.c','sources/vk-offscreen-x64/shaders/triangle.vert.spv','sources/vk-offscreen-x64/shaders/triangle.frag.spv','sources/elfuse-once-panorama2-derived/build/elfuse']
j['artifact_hashes']={p:sha(LAB/p) for p in files}
assert j['artifact_hashes'][files[0]]=='112377ef135b5bb3d240646b665b1747bc21078ec8ee2272208bec2c1ae11e22'
j['host']=platform.uname()._asdict(); j['pixel_verification']=details;j['synthetic_negatives']=run_negative_tests()
j['raw_hashes']={p.name:sha(p) for p in D.glob('*') if p.suffix in ['.raw','.png','.log','.txt','.diff']}
for label,v in j['runs'].items():
    err=(D/(label+'_stderr.log')).read_text(errors='replace').splitlines()
    count=[{'line':i+1,'text':l} for i,l in enumerate(err) if 'Returning 1 devices.' in l]
    v['physical_device_count_evidence']=count; v['physical_device_count']=1 if count else None
    v['cleanup_errors']=v['result']['cleanup_errors']
    assert not v['cleanup_errors']
rb=json.loads((D/'rollback.json').read_text());j['rollback_status']=rb['status'];j['rollback_errors']=rb['errors']
pre=json.loads((D/'fingerprint_pre.json').read_text());post=compute_tree_fingerprint(D/'runs/fixture_steam_root')
(D/'fingerprint_post.json').write_text(json.dumps(post,indent=2));j['rollback_fingerprint_equal']=pre==post
j['layers']={'AMD64_PE_build':True,'installed_wrapper_execution':True,'translated_x64_PE_execution_on_ARM64':True,'Vulkan_instance':True,'device_count_at_least_one':all(v['physical_device_count']==1 for v in j['runs'].values()),'skip_draw_negative_exit21':True,'normal_draw_exit0':True,'eight_point_readback':ok,'hardware_GPU':False,'normal_COW_gate_off':'NOT_TESTED','game_window':'NOT_TESTED'}
j['FEX_attribution']='Approved ARM64 Wine/FEX configuration executing verified AMD64 PE on Darwin arm64; no separate translator module-load trace was enabled in these runs.'
j['limitations']=['ELFUSE_DIAG_SESSION_SHARED=1 remains enabled and sacrifices targeted private mapping semantics.','CPU llvmpipe; no hardware GPU or interactive window validation.','Negative probe exits at first interior mismatch before writing framebuffer.raw; raw pixel is reported by PE stdout, no negative framebuffer file is claimed.']
(D/'receipt.json').write_text(json.dumps(j,indent=2))
print(json.dumps({'layers':j['layers'],'rollback_equal':j['rollback_fingerprint_equal'],'rollback_status':j['rollback_status'],'rollback_errors':j['rollback_errors'],'framebuffer_sha256':sha(D/'normal_framebuffer.raw')},indent=2))
