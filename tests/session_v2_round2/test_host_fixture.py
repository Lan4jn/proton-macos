import importlib.util
import pathlib
import unittest

P = pathlib.Path(__file__).resolve().parents[2] / 'scripts/runtime/session_v2_round2/host_fixture.py'

class HostFixtureTests(unittest.TestCase):
    def module(self):
        self.assertTrue(P.exists(), 'host fixture runner missing')
        spec=importlib.util.spec_from_file_location('host_fixture',P)
        m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        return m

    def test_cleanup_snapshot_failure_still_reaps_sentinel(self):
        m=self.module()
        r=m.run_fixture(fail_post_cleanup_snapshot=True)
        self.assertEqual(r['post_cleanup_observation'], 'UNKNOWN')
        self.assertIn('injected post-cleanup snapshot', r['errors'])
        self.assertTrue(r['sentinel_reaped'])

    def test_inner_timeout_cleans_and_preserves_sentinel(self):
        r=self.module().run_fixture(mode='timeout')
        self.assertTrue(r['inner_timed_out'])
        self.assertIsNone(r['target_exit'])
        self.assertTrue(r['cleanup']['complete'])
        self.assertTrue(r['sentinel_alive'])
        self.assertTrue(r['known_after_cleanup_clear'])

    def test_worker_crash_keeps_known_identities_and_cleans(self):
        r=self.module().run_fixture(mode='worker_crash')
        self.assertTrue(r['sentinel_alive'])
        self.assertTrue(r['cleanup']['complete'])
        self.assertEqual(r['fault_signal']['result'], 'sent')
        self.assertGreaterEqual(len(r['known_before_fault']), 3)
        self.assertTrue(r['known_after_cleanup_clear'])

    def test_existing_run_id_rejected_without_changes(self):
        m=self.module(); r=m.run_fixture(); root=pathlib.Path(r['root'])
        before={str(x.relative_to(root)):x.read_bytes() for x in root.rglob('*') if x.is_file()}
        with self.assertRaises(FileExistsError): m.run_fixture(run_id=root.name)
        self.assertEqual(before,{str(x.relative_to(root)):x.read_bytes() for x in root.rglob('*') if x.is_file()})

    def test_real_barriers_cleanup_and_sentinel(self):
        self.assertTrue(P.exists(), 'host fixture runner missing')
        spec=importlib.util.spec_from_file_location('host_fixture',P)
        m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        r=m.run_fixture()
        self.assertEqual(r['correlation']['status'],'PASS')
        self.assertTrue(r['sentinel_alive'])
        self.assertTrue(r['cleanup']['complete'])
        self.assertEqual(r['target_exit'],0)
        self.assertEqual(len(r['snapshots']),2)

if __name__ == '__main__': unittest.main(verbosity=2)
