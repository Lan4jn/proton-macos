import unittest
from scripts.runtime.arm64_vulkan_probe.runner import classify

class VulkanClassifierTests(unittest.TestCase):
    def setUp(self):
        self.r = {'exit':0, 'target_exit':0, 'timed_out':False, 'cleanup_errors':[]}
        self.out = '\n'.join(['[WIN_ARM64_VK] SUCCESS: VkInstance created at 0x10', '[WIN_ARM64_VK] SUCCESS: Verified CPU lavapipe/llvmpipe device.', '[WIN_ARM64_VK] FINAL_STATUS: WIN_ARM64_VULKAN_OK'])
    def test_full_guarded_evidence(self):
        self.assertEqual(classify(self.r,self.out),'ARM64_WINDOWS_VULKAN_CPU_ENUM_PASSED')
    def test_nonzero_after_marker(self):
        for n in (12,124,139,-15):
            self.r.update(exit=n,target_exit=n)
            self.assertEqual(classify(self.r,self.out),'TARGET_FAILED')
    def test_missing_target(self):
        self.r['target_exit']=None
        self.assertEqual(classify(self.r,self.out),'TARGET_FAILED')
    def test_timeout(self):
        self.r['timed_out']=True
        self.assertEqual(classify(self.r,self.out),'TIMEOUT')
    def test_cleanup(self):
        self.r['cleanup_errors']=['failed']
        self.assertEqual(classify(self.r,self.out),'CLEANUP_FAILED')
    def test_cpu_guard_missing(self):
        self.assertEqual(classify(self.r,self.out.replace('[WIN_ARM64_VK] SUCCESS: Verified CPU lavapipe/llvmpipe device.','')),'INCOMPLETE')
    def test_loader_only(self):
        self.assertEqual(classify(self.r,'[WIN_ARM64_VK] SUCCESS: vulkan-1.dll loaded'),'INCOMPLETE')

if __name__ == '__main__': unittest.main()
