import unittest
from unittest.mock import Mock
from classifier import ProbeClassifier


class ExecutionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.c = ProbeClassifier()
        self.c.classify = Mock(return_value={'verdict': 'CASE_ANALYSIS'})
        self.evidence = dict(probe_returncode=0, timed_out=False,
                             seed_sha_before='a'*64, seed_sha_after='a'*64)

    def test_complete_evidence_reaches_case_analysis(self):
        result = self.c.classify_execution({}, **self.evidence)
        self.assertEqual(result['verdict'], 'CASE_ANALYSIS')
        self.c.classify.assert_called_once_with({}, **self.evidence)

    def test_absent_values_never_reach_case_analysis(self):
        for field in self.evidence:
            with self.subTest(field=field):
                args = dict(self.evidence); args[field] = None
                self.assertEqual(self.c.classify_execution({}, **args)['verdict'], 'INCONCLUSIVE')
        self.c.classify.assert_not_called()

    def test_omitted_required_values_raise(self):
        with self.assertRaises(TypeError):
            self.c.classify_execution({})
        self.c.classify.assert_not_called()

    def test_bool_is_not_exit_integer(self):
        self.evidence['probe_returncode'] = False
        self.assertEqual(self.c.classify_execution({}, **self.evidence)['verdict'], 'INCONCLUSIVE')
        self.c.classify.assert_not_called()

    def test_integer_is_not_timeout_bool(self):
        self.evidence['timed_out'] = 0
        self.assertEqual(self.c.classify_execution({}, **self.evidence)['verdict'], 'INCONCLUSIVE')
        self.c.classify.assert_not_called()

    def test_bad_hash_values(self):
        for value in ('', 'a'*63, 'z'*64, 'A'*64, 123):
            with self.subTest(value=value):
                self.evidence['seed_sha_after'] = value
                self.assertEqual(self.c.classify_execution({}, **self.evidence)['verdict'], 'INCONCLUSIVE')
        self.c.classify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
