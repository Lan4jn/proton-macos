import re,unittest
REQUIRED=['PROCESS_START','USER32_OK','REGISTER_OK','CREATE_OK','SHOW_OK','LOOP_ENTER','PAINT_OK','LOOP_QUIT','DESTROY_OK','EXIT_OK']
def analyze(text,exit_code,timed_out):
    events=[{'t_ms':int(t),'stage':stage,'value':int(v)} for t,stage,v in re.findall(r'WINDOW_STAGE t_ms=(\d+) stage=(\w+) value=(\d+)',text)]
    seen=[x['stage'] for x in events]
    missing=[x for x in REQUIRED if x not in seen]
    ordered=not missing and [seen.index(x) for x in REQUIRED]==sorted(seen.index(x) for x in REQUIRED)
    return {'pass':exit_code==0 and not timed_out and ordered,'events':events,'missing':missing,
            'last_stage':seen[-1] if seen else None,'exit_code':exit_code,'timed_out':timed_out,
            'stage_elapsed_ms':events[-1]['t_ms']-events[0]['t_ms'] if events else None}
class TimelineTests(unittest.TestCase):
    def test_success(self):
        text='\n'.join('WINDOW_STAGE t_ms=%d stage=%s value=1'%(i,s) for i,s in enumerate(REQUIRED))
        self.assertTrue(analyze(text,0,False)['pass'])
    def test_create_only_timeout_not_pass(self):
        r=analyze('WINDOW_STAGE t_ms=10 stage=CREATE_BEGIN value=0',124,True)
        self.assertFalse(r['pass']);self.assertEqual(r['last_stage'],'CREATE_BEGIN')
    def test_nonzero_not_pass(self):
        text='\n'.join('WINDOW_STAGE t_ms=%d stage=%s value=1'%(i,s) for i,s in enumerate(REQUIRED))
        self.assertFalse(analyze(text,21,False)['pass'])
if __name__=='__main__':unittest.main(verbosity=2)
