import json,re,statistics,hashlib,sys,unittest
from pathlib import Path
LAB=Path(__file__).resolve().parents[3]
def parse_updates(text):
    matches=re.findall(r'INPROC_UPDATE phase=(\d+) seq=(\d+) begin_ns=(\d+) duration_ns=(\d+) gap_ns=(\d+) events=(\d+)',text)
    if not matches:raise ValueError('No actual in-process UI updates')
    rows=[dict(zip(['phase','seq','begin_ns','duration_ns','gap_ns','events'],map(int,x))) for x in matches]
    if any(r['duration_ns']<=0 for r in rows):raise ValueError('Invalid duration')
    if any(a['begin_ns']>=b['begin_ns'] for a,b in zip(rows,rows[1:])):raise ValueError('Nonmonotonic callbacks')
    return rows
class Tests(unittest.TestCase):
    def test_parse(self):
        r=parse_updates('INPROC_UPDATE phase=1 seq=2 begin_ns=100 duration_ns=20 gap_ns=0 events=0')
        self.assertEqual(r[0]['duration_ns'],20)
    def test_no_updates_fails(self):
        with self.assertRaises(ValueError):parse_updates('exit0 without ready')
if __name__=='__main__' and '--finalize' not in sys.argv:unittest.main(verbosity=2)

def finalize():
    out=LAB/'logs/inproc-present';source=(LAB/'logs/vk-offscreen/framebuffer.raw').read_bytes();expected=hashlib.sha256(source).hexdigest()
    result={}
    for label in ['off','invalid','invalidrange','on','off2','on2','on3','on4','finaloff','finalon','sealedoff','sealedon']:
        root=out/label;r=json.loads((root/'receipt.json').read_text())['result'];stdout=Path(r['stdout']).read_text();stderr=Path(r['stderr']).read_text()
        item={'exit':r['exit'],'seconds':r['seconds'],'timed_out':r['timed_out'],'cleanup_errors':r['cleanup_errors'],'last_stdout':stdout.splitlines()[-3:]}
        if label.startswith('off'):
            assert 'INPROC_LOAD' not in stderr and 'INPROC_WINDOW' not in stderr
        if 'INPROC_UPDATE' in stderr:
            rows=parse_updates(stderr);dur=[r['duration_ns']/1e6 for r in rows]
            item.update({'update_count':len(rows),'ui_update_callback_ms':{'min':min(dur),'median':statistics.median(dur),'max':max(dur)},
              'max_ui_gap_ms':max(r['gap_ns'] for r in rows)/1e6,'phase_update_counts':{str(p):sum(r['phase']==p for r in rows) for p in [1,2,3]},
              'all_ui_on_main':all('main=1' in l for l in stderr.splitlines() if 'INPROC_WINDOW' in l),
              'window_records':[l for l in stderr.splitlines() if 'INPROC_WINDOW' in l],
              'phase_boundary_updates':[r for r in rows if r['phase'] in [2,3]][:2],
              'update_gate_min_interval_ms':16,'configured_upper_bound_updates_per_second':62.5})
            steady=sorted(r['duration_ns']/1e6 for r in rows[1:])
            captures_at_phase=[r for i,r in enumerate(rows) if i and r['phase']!=rows[i-1]['phase']]
            item['first_callback_ms']=rows[0]['duration_ns']/1e6
            item['callbacks_excluding_first_ms']={'min':min(steady),'median':statistics.median(steady),'p95':steady[__import__('math').ceil(.95*len(steady))-1],'max':max(steady)}
            item['phase_change_capture_callback_ms']=[r['duration_ns']/1e6 for r in captures_at_phase]
            item['phase_observed_update_rates']={}
            for phase in [1,3]:
                phase_rows=[r for r in rows if r['phase']==phase]
                if len(phase_rows)>1:item['phase_observed_update_rates'][str(phase)]=(len(phase_rows)-1)*1e9/(phase_rows[-1]['begin_ns']-phase_rows[0]['begin_ns'])
            captures={}
            for raw in root.glob('phase*.rgba'):
                pixels=raw.read_bytes();assert pixels==source
                captures[raw.name]={'sha256':hashlib.sha256(pixels).hexdigest(),'exact_pixels':4096,'mismatches':0}
            item['captures']=captures
        freq=re.search(r'GUEST_READY frequency=(\d+)',stdout)
        if freq:
            frequency=int(freq.group(1));item['guest_clock_frequency']=frequency
            item['heartbeat_max_gap_ms']={phase:int(t)*1000/frequency for phase,t in re.findall(r'HEARTBEAT(\d+) max_gap_ticks=(\d+)',stdout)}
            compute=re.search(r'COMPUTE_NO_SYSCALL ticks=(\d+)',stdout)
            item['no_syscall_compute_ms']=int(compute.group(1))*1000/frequency if compute else None
        if label=='on2':item['status']='NOT_A_PRESENTATION_PASS; stale configured GVA, no ready observed'
        result[label]=item
    assert result['on3']['exit']==0 and result['on3']['captures'] and result['on3']['phase_update_counts']['2']==1
    assert result['on3']['max_ui_gap_ms']>2900
    assert result['invalidrange']['exit']==86 and result['invalid']['exit']==86
    (out/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__' and '--finalize' in sys.argv:finalize()
