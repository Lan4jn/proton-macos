import errno
import json
import struct
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from scripts.backend.process import run_isolated,LAB
from scripts.proton.audit_proton import BinaryAuditor

class Regressions(unittest.TestCase):
    def test_real_elf_vernaux_layout(self):
        strings=b'\x00libc.so.6\x00GLIBC_2.38\x00'
        verneed=struct.pack('<HHIII',1,1,1,16,0)+struct.pack('<IHHII',0,0,2,11,0)
        self.assertEqual(BinaryAuditor(str(LAB/'fixtures/abi/bin/dynamic_hello'))._parse_verneed(verneed,strings,'<'),['GLIBC_2.38'])

    def test_cleanup_error_preserves_result(self):
        with patch('scripts.backend.process.os.killpg',side_effect=PermissionError(errno.EPERM,'test')):
            r=run_isolated([sys.executable,'-c','print(1)'],LAB/'logs/backend/tests',timeout=2)
        # Cleanup failure cannot claim overall exit 0, but target child exit is preserved in target_exit
        self.assertNotEqual(r['exit'],0)
        self.assertEqual(r['target_exit'],0)
        self.assertTrue(r['cleanup_errors'])
        data = json.loads(Path(r['run_dir'],'result.json').read_text())
        self.assertTrue(data['cleanup_errors'])

    def test_no_environment_path_escape(self):
        with self.assertRaises(ValueError):
            run_isolated([sys.executable,'-c','print(1)'],LAB/'logs/backend/tests',extra_env={'HOME':'/tmp/outside'},timeout=2)

if __name__=='__main__': unittest.main()
