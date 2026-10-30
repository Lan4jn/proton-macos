import math,re,statistics,unittest
GROUPS=['draw','readback','clear']
def analyze(text):
    cfg=re.search(r'BENCH_CONFIG width=(\d+) height=(\d+) frames=(\d+) warmup=(\d+) frequency=(\d+) pipeline_ticks=(\d+)',text)
    if not cfg:raise ValueError('Missing benchmark configuration')
    width,height,n,warm,freq,pipeline=map(int,cfg.groups())
    if freq<=0 or n<2:raise ValueError('Invalid clock or sample size')
    done=re.search(r'BENCH_DONE total_draws=(\d+) total_submits=(\d+) validations=(\d+)',text)
    if not done:raise ValueError('Incomplete benchmark')
    samples={g:[] for g in GROUPS}
    for g,i,phase,t in re.findall(r'BENCH_FRAME group=(\w+) index=(\d+) phase=(\w+) ticks=(\d+)',text):
        if g not in samples:raise ValueError('Unknown group')
        samples[g].append({'index':int(i),'phase':phase,'ticks':int(t),'ms':int(t)*1000/freq})
    result={'width':width,'height':height,'steady_frames':n,'warmup_frames':warm,'frequency':freq,'pipeline_ms':pipeline*1000/freq,'groups':{}}
    per_group={g:int(n) for g,n in re.findall(r'BENCH_GROUP group=(\w+) frames=(\d+)',text)}
    for g,rows in samples.items():
        n=per_group.get(g,result['steady_frames'])
        if len(rows)!=n+warm+1 or [x['index'] for x in rows]!=list(range(n+warm+1)):raise ValueError('Missing or duplicate frames')
        if [x['phase'] for x in rows]!=['first']+['warmup']*warm+['steady']*n:raise ValueError('Wrong phases')
        if any(x['ticks']<=0 for x in rows):raise ValueError('Nonpositive frame duration')
        raw=[x['ms'] for x in rows[1+warm:]];ordered=sorted(raw);total=sum(raw)
        result['groups'][g]={'first_frame_ms':rows[0]['ms'],'samples':rows,'readback_included':g=='readback',
            'real_draw':g!='clear','steady':{'min_ms':min(raw),'median_ms':statistics.median(raw),
            'p90_ms':ordered[math.ceil(.9*n)-1],'max_ms':max(raw),'total_ms':total,'fps':n/(total/1000)}}
    draws,submits,validations=map(int,done.groups())
    expected_draws=sum(per_group.get(g,result['steady_frames'])+warm+2 for g in ['draw','readback'])
    expected_submits=sum(per_group.get(g,result['steady_frames'])+warm+2 for g in GROUPS)
    if (draws,submits,validations)!=(expected_draws,expected_submits,3):raise ValueError('Draw/submission count mismatch')
    timed_rows=re.findall(r'BENCH_FRAME group=(\w+) index=(\d+) phase=(\w+) ticks=(\d+) start=(\d+) end=(\d+)',text)
    if timed_rows:
        previous=0
        for g,i,phase,t,start,end in timed_rows:
            t,start,end=map(int,[t,start,end])
            if end<=start or end-start!=t or start<previous:raise ValueError('QPC nonmonotonic or inconsistent')
            previous=end
        clock=re.search(r'BENCH_CLOCK qpc_elapsed_ticks=(\d+) tick_elapsed_ms=(\d+)',text)
        if not clock:raise ValueError('Missing independent clock interval')
        qpc_ticks,wall_ms=map(int,clock.groups());qpc_ms=qpc_ticks*1000/freq
        result['clock_validation']={'frequency':freq,'qpc_quantum_ns':1e9/freq,'all_frames_positive_and_monotonic':True,
           'qpc_interval_ms':qpc_ms,'GetTickCount64_interval_ms':wall_ms,'interval_ratio':qpc_ms/wall_ms if wall_ms else None,
           'min_frame_ticks':min(int(row[3]) for row in timed_rows),'unique_frame_ticks':len(set(row[3] for row in timed_rows))}
        if wall_ms<=0 or abs(qpc_ms-wall_ms)>max(30,wall_ms*.15):raise ValueError('Clock calibration disagreement')
        for g,ticks in re.findall(r'BENCH_GROUP_END group=(\w+) steady_wall_ticks=(\d+)',text):
            ms=int(ticks)*1000/freq
            result['groups'][g]['steady']['continuous_interval_ms']=ms
            result['groups'][g]['steady']['continuous_interval_fps']=per_group.get(g,result['steady_frames'])/(ms/1000)
    result['validated_draws']=draws;result['validated_submits']=submits
    result['process_cold_pipeline_plus_first_draw_ms']=result['pipeline_ms']+result['groups']['draw']['first_frame_ms']
    result['delta_readback_minus_draw_median_ms']=result['groups']['readback']['steady']['median_ms']-result['groups']['draw']['steady']['median_ms']
    result['delta_draw_minus_clear_median_ms']=result['groups']['draw']['steady']['median_ms']-result['groups']['clear']['steady']['median_ms']
    return result
class StatsTests(unittest.TestCase):
    def sample(self):
        return 'BENCH_CONFIG width=64 height=64 frames=3 warmup=1 frequency=1000 pipeline_ticks=10\n'+''.join('BENCH_FRAME group=%s index=%d phase=%s ticks=%d\n'%(g,i,['first','warmup','steady','steady','steady'][i],i+1) for g in GROUPS for i in range(5))+'BENCH_DONE total_draws=12 total_submits=18 validations=3\n'
    def test_statistics(self):
        r=analyze(self.sample());self.assertEqual(r['groups']['draw']['steady']['median_ms'],4);self.assertEqual(r['groups']['draw']['steady']['p90_ms'],5)
    def test_missing_frames_fails(self):
        with self.assertRaises(ValueError):analyze(self.sample().replace('group=draw index=4','group=draw index=3'))
    def test_zero_ticks_fails(self):
        with self.assertRaises(ValueError):analyze(self.sample().replace('ticks=1','ticks=0'))
    def test_wrong_draw_count_fails(self):
        with self.assertRaises(ValueError):analyze(self.sample().replace('total_draws=12','total_draws=0'))
    def test_incomplete_fails(self):
        with self.assertRaises(ValueError):analyze(self.sample().replace('BENCH_DONE','NOT_COMPLETE'))
if __name__=='__main__':unittest.main(verbosity=2)
