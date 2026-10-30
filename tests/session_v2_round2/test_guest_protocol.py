import importlib.util
import pathlib
import unittest

P=pathlib.Path(__file__).resolve().parents[2]/'scripts/runtime/session_v2_round2/guest_protocol.py'
class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(P.exists(), 'protocol parser missing')
        spec=importlib.util.spec_from_file_location('guest_protocol',P)
        self.m=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)
    def test_accept_matching_phase(self):
        x='{"phase":"pre","token":"aaaa","pid":2,"ppid":1,"pgid":1,"sid":1,"result":0,"errno":0}'
        self.assertEqual(self.m.parse_phase(x,'pre','aaaa')['pid'],2)
    def test_accept_ppid_zero_from_actual_guest_capture(self):
        # Actual Linux guest root process capture
        x='{"phase":"parent","token":"aaaa","pid":1,"ppid":0,"pgid":1,"sid":1,"result":0,"errno":0}'
        rec = self.m.parse_phase(x,'parent','aaaa')
        self.assertEqual(rec['ppid'], 0)
        self.assertEqual(rec['pid'], 1)
    def test_wrong_token_or_phase_or_bad_pid_rejected(self):
        samples=['{"phase":"post","token":"aaaa","pid":2,"ppid":1,"pgid":1,"sid":1,"result":0,"errno":0}',
                 '{"phase":"pre","token":"bad","pid":2,"ppid":1,"pgid":1,"sid":1,"result":0,"errno":0}',
                 '{"phase":"pre","token":"aaaa","pid":true,"ppid":1,"pgid":1,"sid":1,"result":0,"errno":0}',
                 '{"phase":"pre","token":"aaaa","pid":2,"ppid":-1,"pgid":1,"sid":1,"result":0,"errno":0}',
                 '{"phase":"pre","token":"aaaa","pid":0,"ppid":0,"pgid":1,"sid":1,"result":0,"errno":0}']
        for x in samples:
            with self.assertRaises(ValueError): self.m.parse_phase(x,'pre','aaaa')
if __name__=='__main__': unittest.main(verbosity=2)
