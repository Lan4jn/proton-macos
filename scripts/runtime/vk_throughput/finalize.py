import hashlib,json,re,sys
from pathlib import Path
LAB=Path(__file__).resolve().parents[3];sys.path.insert(0,str(LAB))
from scripts.runtime.vk_throughput.analyze import analyze
OUT=LAB/'logs/vk-throughput'
labels=['small20','p720measure','smalllong','p720long','smallinst100','p360inst100','p720inst100','p1080inst100','p720inst20']
summary=[]
for label in labels:
 root=OUT/label;text=(root/'probe.stdout.log').read_text();stats=analyze(text)
 receipt=json.loads((root/'receipt.json').read_text());execution=json.loads((root/'execution-result.json').read_text())
 assert execution['exit']==0 and not execution['timed_out'] and not execution['cleanup_errors']
 assert json.loads((root/'rollback.json').read_text())['status']=='success'
 assert (root/'fingerprint-before.json').read_bytes()==(root/'fingerprint-after.json').read_bytes()
 captures={};w,h=stats['width'],stats['height']
 for group in ['draw','readback','clear']:
  raw=(root/'compat/pfx/drive_c'/('bench-'+group+'.raw')).read_bytes();assert len(raw)==w*h*4
  red=sum(raw[i:i+4]==bytes([255,0,0,255]) for i in range(0,len(raw),4))
  blue=sum(raw[i:i+4]==bytes([0,0,128,255]) for i in range(0,len(raw),4))
  assert red+blue==w*h
  if group=='clear':assert red==0
  else:assert red>0 and blue>0
  captures[group]={'sha256':hashlib.sha256(raw).hexdigest(),'red_pixels':red,'blue_pixels':blue,'byte_length':len(raw),'all_pixels_expected_colors':True}
 assert captures['draw']['sha256']==captures['readback']['sha256']
 if w==64:assert captures['draw']['sha256']=='2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050'
 (root/'statistics.json').write_text(json.dumps(stats,indent=2)+'\n');(root/'capture-validation.json').write_text(json.dumps(captures,indent=2)+'\n')
 instances=re.search(r'BENCH_WORKLOAD instances=(\d+)',text);count=int(instances.group(1)) if instances else 1
 wall=execution['seconds']*1000;loop=stats['clock_validation']['qpc_interval_ms'];pipeline=stats['pipeline_ms']
 stderr=(root/'probe.stderr.log').read_text();explorer=re.findall(r'(\d+\.\d+).*?get_desktop_window (starting explorer|started explorer)',stderr)
 item={'label':label,'instances':count,'width':w,'height':h,'steady_frames':len(stats['groups']['draw']['samples'])-6,
   'groups':{g:{'first_frame_ms':v['first_frame_ms'],**v['steady']} for g,v in stats['groups'].items()},
   'clock':stats['clock_validation'],'pipeline_ms':pipeline,'wall_ms':wall,'measurement_loop_ms':loop,
   'outside_measurement_and_pipeline_ms':wall-loop-pipeline,'outside_fraction':(wall-loop-pipeline)/wall,
   'wineboot_duration_ms':'UNKNOWN; no complete start/end markers','explorer_markers':explorer,
   'explorer_duration_ms':'UNKNOWN; trace boundary only, child startup overlaps','readback_median_delta_ms':stats['delta_readback_minus_draw_median_ms'],
   'red_pixels_per_instance_assumed':captures['draw']['red_pixels'],'captures':captures,'probe_sha256':receipt['probe_sha256']}
 summary.append(item)
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
rows={r['label']:r for r in summary}
def incremental(a,b,independent):
 ta=a['groups']['draw']['median_ms']-a['groups']['clear']['median_ms'];tb=b['groups']['draw']['median_ms']-b['groups']['clear']['median_ms']
 return {'a':a['label'],'b':b['label'],'incremental_net_draw_ms':tb-ta,'independent_delta':independent,
  'ns_per_unit':(tb-ta)*1e6/independent,'units_per_second':independent/((tb-ta)/1000)}
slopes={'scope':'finite differences of separately measured medians after own clear subtraction; model estimate, not direct hardware counter or general fill rate',
 'assumption':'Every repeated instance rasterizes independently; no evidence of plateau from 20 to 100, but no per-instance hardware counter',
 'fixed_100_instances_resolution':[
 incremental(rows[a],rows[b],(rows[b]['red_pixels_per_instance_assumed']-rows[a]['red_pixels_per_instance_assumed'])*100)
 for a,b in [('smallinst100','p360inst100'),('p360inst100','p720inst100'),('p720inst100','p1080inst100')]],
 'fixed_720p_instances20_to100':incremental(rows['p720inst20'],rows['p720inst100'],80)}
(OUT/'slopes.json').write_text(json.dumps(slopes,indent=2)+'\n')
for r in summary:
 print(r['label'],'draw median/p90/interval_rate',*[round(r['groups']['draw'][k],3) for k in ['median_ms','p90_ms','continuous_interval_fps']], 'outside%',round(100*r['outside_fraction'],3))
print(json.dumps(slopes,indent=2))
