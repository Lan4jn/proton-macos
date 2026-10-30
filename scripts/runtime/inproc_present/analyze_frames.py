import json,re,statistics,math,sys
from pathlib import Path
LAB=Path(__file__).resolve().parents[3];sys.path.insert(0,str(LAB))
from scripts.runtime.inproc_present.analyze import parse_updates
OUT=LAB/'logs/inproc-present';labels=['frameoff','frameon','frameonmainonly','frameonmainonly2','frame720off','frame720onmainonly','frametaggedonmainonly','frame720onmainonlyfinal']
result={}
for label in labels:
 root=OUT/label;receipt=json.loads((root/'receipt.json').read_text());stdout=(root/'probe.stdout.log').read_text();stderr=(root/'probe.stderr.log').read_text();stats=json.loads((root/'statistics.json').read_text())
 item={'exit':receipt['wrapper_exit'],'duration_seconds':receipt['duration_seconds'],'statistics':stats,'updates':[]}
 if 'INPROC_UPDATE' in stderr:
  updates=parse_updates(stderr);item['updates']=updates;times=sorted(r['duration_ns']/1e6 for r in updates[1:])
  item['first_callback_ms']=updates[0]['duration_ns']/1e6
  item['steady_callback_ms']={'min':min(times),'median':statistics.median(times),'p95':times[math.ceil(.95*len(times))-1],'max':max(times)}
  item['update_count']=len(updates);item['unique_sampled_sequences']=sorted(set(r['seq'] for r in updates))
  item['overall_update_rate']= (len(updates)-1)*1e9/(updates[-1]['begin_ns']-updates[0]['begin_ns'])
  item['post_init_update_rate']=(len(updates)-2)*1e9/(updates[-1]['begin_ns']-updates[1]['begin_ns']) if len(updates)>2 else None
  item['max_update_gap_ms']=max(r['gap_ns'] for r in updates)/1e6
  commits=[int(s) for s in re.findall(r'INPROC_FRAME_COMMIT seq=(\d+)',stdout)]
  if not commits:commits=list(range(1,28)) # historical untagged constant-content fixture, not changing pixels
  deferred=set(map(int,re.findall(r'INPROC_DEFER seq=(\d+)',stderr)))
  table=[]
  for seq in commits:
   shown=seq in item['unique_sampled_sequences']
   reason='sampled_into_host_view' if shown else '16ms_throttle_then_single_slot_overwrite' if seq in deferred else 'no_eligible_main_callback_observed_before_single_slot_overwrite; trigger reason UNKNOWN'
   table.append({'commit_seq':seq,'sampled':shown,'throttle_observed':seq in deferred,'reason':reason})
  item['commit_sampling_table']=table;item['commit_count']=len(commits)
  item['missing_identity_fraction']=sum(not r['sampled'] for r in table)/len(table)
  item['content_scope']='CPU pixel0 seq watermark; all other pixels genuine rendered readback' if 'INPROC_FRAME_COMMIT seq=' in stdout else 'identical pixels all frames; seq loss is NOT observed visual-content loss'
  (root/'frame-sampling.json').write_text(json.dumps(table,indent=2)+'\n')
  (root/'frame-sampling.csv').write_text('commit_seq,sampled,throttle_observed,reason\n'+''.join(str(r['commit_seq'])+','+str(r['sampled'])+','+str(r['throttle_observed'])+','+r['reason']+'\n' for r in table))
  counters={}
  for pid,main,worker,first,last,gap in re.findall(r'INPROC_STATS pid=(\d+) main_entries=(\d+) worker_skips=(\d+) first_s=([\d.]+) last_s=([\d.]+) main_gap_max_s=([\d.]+)',stderr):
   d={'main_entries':int(main),'worker_skips':int(worker),'first_s':float(first),'last_s':float(last),'main_gap_max_s':float(gap)}
   span=d['last_s']-d['first_s'];d['main_entries_per_second_in_recorded_span']=d['main_entries']/span if span else None;counters[pid]=d
  item['per_process_last_counter_snapshot']=counters
  active=re.findall(r'INPROC_ACTIVE pid=(\d+) entries=(\d+) first_ns=(\d+) last_ns=(\d+)',stderr)
  active=list(dict.fromkeys(active))
  item['active_main_entry_measurements']=[{'pid':int(p),'entries':int(n),'first_ns':int(a),'last_ns':int(b),'entries_per_second':int(n)*1e9/(int(b)-int(a))} for p,n,a,b in active if int(b)>int(a)]
 if label=='frameonmainonly':item['performance_valid']=False;item['reason']='1699049 per-entry logging lines: do not use any timing/FPS for performance conclusion'
 result[label]=item
(OUT/'frame-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
for label in ['frame720off','frame720onmainonlyfinal','frametaggedonmainonly']:
 r=result[label];print(label,'readback',r['statistics'].get('groups',{}).get('readback',{}).get('steady'))
 for key in ['first_callback_ms','steady_callback_ms','update_count','unique_sampled_sequences','commit_count','missing_identity_fraction','post_init_update_rate','active_main_entry_measurements']:print(key,r.get(key))
 if 'per_process_last_counter_snapshot' in r:
  print('worker_total_last_snapshots',sum(x['worker_skips'] for x in r['per_process_last_counter_snapshot'].values()))
