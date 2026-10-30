import unittest
from scripts.runtime.arm64_loader_probe.runner import classify

class StageClassifierTests(unittest.TestCase):
    def setUp(self):
        self.result = {'exit': 37, 'target_exit': 37, 'timed_out': False, 'cleanup_errors': []}
    def test_expected_exit_and_marker(self):
        self.assertEqual(classify(self.result, 'ARM64_KERNEL32_OK', 37, 'ARM64_KERNEL32_OK'), 'STAGE_PASSED')
    def test_marker_without_expected_exit(self):
        for code in (0, 124, 139, -15):
            with self.subTest(code=code):
                self.result.update(exit=code, target_exit=code)
                self.assertEqual(classify(self.result, 'ARM64_KERNEL32_OK', 37, 'ARM64_KERNEL32_OK'), 'TARGET_FAILED')
    def test_target_exit_missing(self):
        self.result['target_exit'] = None
        self.assertEqual(classify(self.result, 'ARM64_KERNEL32_OK', 37, 'ARM64_KERNEL32_OK'), 'TARGET_FAILED')
    def test_timeout_after_marker(self):
        self.result['timed_out'] = True
        self.assertEqual(classify(self.result, 'ARM64_KERNEL32_OK', 37, 'ARM64_KERNEL32_OK'), 'TIMEOUT')
    def test_cleanup_failure_after_marker(self):
        self.result['cleanup_errors'] = ['owned group cleanup failed']
        self.assertEqual(classify(self.result, 'ARM64_KERNEL32_OK', 37, 'ARM64_KERNEL32_OK'), 'CLEANUP_FAILED')
    def test_missing_marker(self):
        self.assertEqual(classify(self.result, '', 37, 'ARM64_KERNEL32_OK'), 'MARKER_MISSING')
    def test_dpi_requires_dpi_stage_marker(self):
        self.result.update(exit=38, target_exit=38)
        self.assertEqual(classify(self.result, 'ARM64_USER32_LOAD_RETURNED', 38, 'ARM64_DPI_RETURNED='), 'MARKER_MISSING')

if __name__ == '__main__':
    unittest.main()
