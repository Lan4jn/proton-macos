import unittest
from pathlib import Path
from scripts.backend.process import LAB,run_isolated

class AbiTests(unittest.TestCase):
    def check(self,name,expected):
        r=run_isolated([str(LAB/'sources/elfuse/build/elfuse'),'--sysroot',str(LAB/'fixtures/runtime/sysroot'),'--timeout','6',str(LAB/'fixtures/abi/bin'/name)],LAB/'logs/abi',timeout=10)
        text=Path(r['stdout']).read_text()+Path(r['stderr']).read_text()
        self.assertEqual(r['exit'],0,text[-4000:])
        self.assertIn(expected,text)
        print(name,r['run_dir'])
    def test_dynamic(self): self.check('dynamic_hello','DYNAMIC_GLIBC_OK')
    def test_shared(self): self.check('shared','SHARED_OK')
    def test_futex(self): self.check('futex','FUTEX_OK')
    def test_signal(self): self.check('signal','SIGNAL_OK')
    def test_spawn(self): self.check('spawn_missing','SPAWN_ENOENT_OK')

if __name__=='__main__':unittest.main()
