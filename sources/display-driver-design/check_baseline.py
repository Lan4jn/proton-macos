import hashlib,json
from pathlib import Path
LAB=Path(__file__).resolve().parents[2]
paths=['sources/host-present-spike/presenter','logs/host-present/trial2/host-view.png','logs/vk-offscreen/framebuffer.raw','logs/host-present/trial2/receipt.json','logs/display-probe/driver_trace/receipt.json']
results={p:hashlib.sha256((LAB/p).read_bytes()).hexdigest() for p in paths}
assert results['logs/vk-offscreen/framebuffer.raw']=='2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050'
assert results['logs/host-present/trial2/host-view.png']=='89876eeee3522b45d1ccdb6238bde774c2506b358f93af1f250b183f3268f7fb'
host=json.loads((LAB/'logs/host-present/trial2/receipt.json').read_text())
assert host['status']=='PASS' and host['view_pixels_exact'] and host['occlusion_visible']
reg=LAB/'logs/win-window/baseline/compat/pfx/user.reg';assert '"Graphics"="null"' in reg.read_text()
results['checks']={'source_frame_and_capture_intact':True,'existing_host_view_exact':True,'explicit_null_registry':True,'new_driver_implemented':False,'transport_measured_this_task':False}
(LAB/'logs/display-driver-design/baseline-check.json').write_text(json.dumps(results,indent=2)+'\n')
print('BASELINE_INTEGRITY_PASS; inventory/read-only checks only, no new presentation or transport runtime')
