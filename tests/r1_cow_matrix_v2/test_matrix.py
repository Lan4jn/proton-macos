import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / 'sources/r1-cow-matrix-v2/probe-host'
CASES = 'shared private lanes fixed protect thread fork-private fork-shared remap'.split()

class MatrixTests(unittest.TestCase):
    def run_probe(self, case, lane, env=None):
        return subprocess.run([str(BIN), case, str(lane)], capture_output=True, text=True, timeout=8, env=env)

    def test_probe_exists(self):
        self.assertTrue(BIN.is_file(), 'probe must be built')

    def test_native_cases(self):
        if not BIN.exists(): self.skipTest('not built')
        for case in CASES:
            with self.subTest(case=case):
                p = self.run_probe(case, os.sysconf('SC_PAGE_SIZE'))
                self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
                r = json.loads(p.stdout)
                self.assertEqual(set(r['assertions']), {'file', 'sibling', 'neighbor'})
                self.assertTrue(all(r['assertions'].values()))
                self.assertEqual(set(r['observed']), {'file', 'sibling', 'target', 'neighbor'})

    def test_subpage_alignment_is_explicit(self):
        if not BIN.exists(): self.skipTest('not built')
        if os.sysconf('SC_PAGE_SIZE') == 4096: self.skipTest('native 4K')
        for case in ['fixed', 'protect', 'remap']:
            p = self.run_probe(case, 4096)
            self.assertEqual(p.returncode, 77)
            self.assertEqual(json.loads(p.stdout)['status'], 'UNSUPPORTED_ALIGNMENT')

    def test_capture_host_receipt(self):
        if not BIN.exists(): self.skipTest('not built')
        p = subprocess.run(['python3', '-I', str(ROOT / 'scripts/r1_cow_matrix_v2/capture_host.py')], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        receipt = json.loads((ROOT / p.stdout.strip() / 'receipt.json').read_text())
        self.assertEqual(receipt['kind'], 'HOST_POSIX_ONLY')
        self.assertEqual(receipt['guest']['status'], 'NOT_RUN')
        self.assertFalse(receipt['gate_present'])
        self.assertEqual(len(receipt['cases']), 9 * len({4096, os.sysconf('SC_PAGE_SIZE')}))
        self.assertTrue(all(r['target_exit'] in (0, 77) and not r['timed_out'] for r in receipt['cases']))

    def test_fork_child_write_is_observed(self):
        if not BIN.exists(): self.skipTest('not built')
        for case in ['fork-private', 'fork-shared']:
            p = self.run_probe(case, os.sysconf('SC_PAGE_SIZE'))
            r = json.loads(p.stdout)
            self.assertEqual(r.get('child_write_seen'), 85, 'child store must be read back via pipe')

    def test_discarded_child_store_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='cow-mutation-', dir=ROOT / 'logs/r1-cow-matrix-v2') as d:
            src = Path(d) / 'mutant.c'
            text = (ROOT / 'sources/r1-cow-matrix-v2/probe.c').read_text()
            self.assertEqual(text.count('*target = 0x55;'), 1)
            src.write_text(text.replace('*target = 0x55;', '/* discarded child store */'))
            binary = Path(d) / 'mutant'
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pthread', str(src), '-o', str(binary)], check=True, capture_output=True)
            p = subprocess.run([str(binary), 'fork-private', str(os.sysconf('SC_PAGE_SIZE'))], capture_output=True, text=True, timeout=8, cwd=d)
            self.assertEqual(p.returncode, 1)
            self.assertEqual(json.loads(p.stdout)['child_write_seen'], 17)
            self.assertFalse(json.loads(p.stdout)['assertions']['sibling'])

    def test_invalid_case(self):
        if not BIN.exists(): self.skipTest('not built')
        self.assertEqual(self.run_probe('invalid', 4096).returncode, 2)

    def test_gate_must_be_unset(self):
        if not BIN.exists(): self.skipTest('not built')
        self.assertEqual(self.run_probe('shared', 4096, dict(os.environ, ELFUSE_DIAG_SESSION_SHARED='0')).returncode, 2)

if __name__ == '__main__': unittest.main()
