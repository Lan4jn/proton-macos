"""Explicit live observer coverage checks; no Wine execution."""
import hashlib
import json
import os
from pathlib import Path
import unittest
import sys
lab=Path('/Users/mewcapoo/Projects/proton-macos-lab')
sys.path.insert(0,str(lab))
from scripts.backend.process import run_isolated
MARKER=b'[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...'

@unittest.skipUnless(os.environ.get('ELFUSE_LIVE_IDENTITY_TEST')=='1','explicit live opt-in required')
class FixtureCoverage(unittest.TestCase):
    def test_coverage_matrix(self):
        log=lab/'logs/pe-identity-sample/coverage-v1'
        self.assertFalse(log.exists()); log.mkdir()
        rt=lab/'sources/elfuse-pe-identity-derived/build/elfuse'
        original=json.loads((lab/'logs/pe-identity-sample/control.json').read_text())
        self.assertEqual(hashlib.sha256(rt.read_bytes()).hexdigest(),original['runtime_sha256'])
        cases=[
          ('plain', 'os.write(1,m)', True, MARKER),
          ('dup', 'f=os.dup(1); os.write(f,m); os.close(f)', False, MARKER),
          ('writev_split', 'os.writev(1,[m[:20],m[20:]])', False, MARKER),
          ('split_calls', 'os.write(1,m[:20]); os.write(1,m[20:])', False, MARKER),
          ('unrelated','os.write(1,b"UNRELATED_OUTPUT")',False,b'UNRELATED_OUTPUT'),
        ]
        results=[]
        for name,body,expected,output in cases:
            with self.subTest(name=name):
                argv=[str(rt),'--sysroot',str(lab/'fixtures/runtime/arch-case'),'--timeout','3',str(lab/'fixtures/runtime/arch-case/usr/bin/python3.14'),'-c','import os; m='+repr(MARKER)+'; '+body]
                r=run_isolated(argv,log,timeout=5,extra_env={'ELFUSE_FIXTURE_IDENTITY':'1','ELFUSE_ABSOCK_BASE':str(lab/'.s')})
                text=Path(r['stderr']).read_text(); marks=[s for s in text.splitlines() if s.startswith('FIXTURE_STEP3_IDENTITY')]
                row={'case':name,'result':r,'markers':marks,'detected':bool(marks),'expected_current_coverage':expected,'stdout_matches':Path(r['stdout']).read_bytes()==output}
                results.append(row)
                self.assertEqual(r['exit'],0); self.assertEqual(r['target_exit'],0)
                self.assertFalse(r['timed_out']); self.assertEqual(r['cleanup_errors'],[])
                self.assertTrue(row['stdout_matches']); self.assertEqual(bool(marks),expected)
        (log/'matrix.json').write_text(json.dumps({'runtime_sha256':original['runtime_sha256'],'cases':results,'meaning':'characterizes existing gaps, not desired complete coverage'},indent=2)+chr(10))
        print(json.dumps([{'case':x['case'],'detected':x['detected'],'exit':x['result']['exit'],'seconds':x['result']['seconds']} for x in results]))

if __name__=='__main__': unittest.main()
