import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[2] / 'scripts/runtime/session_v2_round2/correlation.py'

def load():
    if not MODULE.exists(): return None
    spec = importlib.util.spec_from_file_location('correlation', MODULE)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

class CorrelationTests(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.assertIsNotNone(self.m, 'correlation implementation missing')
        self.owner = {'pid': 100, 'ppid': 2, 'pgid': 100, 'identity': 'leader', 'state': 'S'}
        self.parent = {'pid': 101, 'ppid': 100, 'pgid': 100, 'identity': 'parent', 'state': 'S'}
        self.child = {'pid': 102, 'ppid': 101, 'pgid': 100, 'identity': 'child', 'state': 'S'}
    def evaluate(self, pre, post, pre_token='abc', post_token='abc'):
        return self.m.evaluate(self.owner, pre, post, 'abc', pre_token, post_token)
    def test_valid_stable_tree(self):
        r = self.evaluate([self.owner,self.parent,self.child], [self.owner,self.parent,self.child])
        self.assertEqual(r['status'], 'PASS')
        self.assertEqual(r['correlation'], 'bounded_inference')
    def test_empty_or_missing_child_unknown(self):
        for rows in ([], [self.owner,self.parent]):
            self.assertEqual(self.evaluate(rows, rows)['status'], 'UNKNOWN')
    def test_token_mismatch_unknown(self):
        rows=[self.owner,self.parent,self.child]
        self.assertEqual(self.evaluate(rows,rows,post_token='wrong')['status'], 'UNKNOWN')
    def test_unrelated_extra_descendant_is_ambiguous(self):
        extra = dict(self.child, pid=103, identity='extra')
        rows=[self.owner,self.parent,self.child,extra]
        self.assertEqual(self.evaluate(rows,rows)['status'], 'UNKNOWN')
    def test_changed_identity_unknown(self):
        pre=[self.owner,self.parent,self.child]
        post=[self.owner,self.parent,dict(self.child,identity='reused')]
        self.assertEqual(self.evaluate(pre,post)['status'], 'UNKNOWN')
    def test_changed_pgid_is_fail(self):
        pre=[self.owner,self.parent,self.child]
        post=[self.owner,self.parent,dict(self.child,pgid=102)]
        self.assertEqual(self.evaluate(pre,post)['status'], 'FAIL')

if __name__ == '__main__': unittest.main(verbosity=2)
