import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from scripts.backend.bundle import prepare_tool
from scripts.backend.process import LAB

class PrepareIntegration(unittest.TestCase):
    def test_wrapper_preserves_verb_and_arguments(self):
        base=LAB/'logs/backend/tests';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            root=Path(tmp);out=root/'candidate';prepare_tool(out,root/'not-installed')
            p=subprocess.run([str(out/'probe-wrapper.sh'),'--','waitforexitandrun','游戏.exe','--log-dir','game-only'],capture_output=True,text=True,timeout=5)
            self.assertEqual(p.returncode,0,p.stderr)
            files=list((out/'probe-logs').glob('*.json'));self.assertEqual(len(files),1)
            self.assertEqual(json.loads(files[0].read_text())['argv'],['waitforexitandrun','游戏.exe','--log-dir','game-only'])
            self.assertFalse((root/'not-installed').exists())

    def test_wrapper_without_double_dash(self):
        base=LAB/'logs/backend/tests';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            root=Path(tmp);out=root/'candidate';prepare_tool(out,root/'not-installed')
            p=subprocess.run([str(out/'probe-wrapper.sh'),'waitforexitandrun','游戏.exe','--log-dir','game-only'],capture_output=True,text=True,timeout=5)
            self.assertEqual(p.returncode,0,p.stderr)
            files=list((out/'probe-logs').glob('*.json'));self.assertEqual(len(files),1)
            self.assertEqual(json.loads(files[0].read_text())['argv'],['waitforexitandrun','游戏.exe','--log-dir','game-only'])
            self.assertFalse((root/'not-installed').exists())

if __name__=='__main__':unittest.main()
