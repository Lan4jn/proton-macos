#!/usr/bin/env python3
"""
scripts/runtime/windows_vulkan/test_classifier.py

Unit tests for the production Windows x64 Vulkan test result classifier.
Imports and validates the real function from scripts.runtime.windows_vulkan.classifier.
"""

import sys
import unittest
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.runtime.windows_vulkan.classifier import classify_vulkan_run, parse_vulkan_trace


class TestVulkanClassifier(unittest.TestCase):
    def test_classify_success_with_all_guards(self):
        stdout = """
[WIN_X64_VK] Starting Windows x64 Vulkan Enumeration Test
[WIN_X64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
[WIN_X64_VK] SUCCESS: vulkan-1.dll loaded at 0xfc050000
[WIN_X64_VK] Step 2: Resolving Vulkan function pointers...
[WIN_X64_VK] SUCCESS: All function pointers resolved.
[WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
[WIN_X64_VK] SUCCESS: VkInstance created at 0x1234
[WIN_X64_VK] Physical device count: 1
[WIN_X64_VK] Device Properties:
  - deviceName: llvmpipe (LLVM 23.1)
  - deviceType: 4 (VK_PHYSICAL_DEVICE_TYPE_CPU)
[WIN_X64_VK] SUCCESS: Verified CPU lavapipe/llvmpipe device.
[WIN_X64_VK] FINAL_STATUS: WIN_X64_VULKAN_OK
"""
        stderr = """
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\vulkan-1.dll" at 000000DFFC050000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\winevulkan.dll" at 000000DFFBF60000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFC1A0000: builtin
0024:trace:vulkan:vulkan_init_once Host instance extensions:
"""
        res = classify_vulkan_run(
            stdout, stderr, exit_code=0, target_exit=0, timed_out=False, cleanup_errors=[]
        )
        self.assertEqual(res["verdict"], "WIN_X64_VULKAN_ENUM_SUCCESS")
        self.assertEqual(res["stage"], "COMPLETE")
        self.assertTrue(res["trace"]["vulkan_1_loaded"])
        self.assertTrue(res["trace"]["winevulkan_dll_loaded"])
        self.assertTrue(res["trace"]["fex_loaded"])
        self.assertTrue(res["trace"]["winevulkan_unix_active"])

    def test_classify_success_rejected_if_cleanup_errors(self):
        stdout = """
[WIN_X64_VK] Device Properties:
  - deviceName: llvmpipe (LLVM 23.1)
  - deviceType: 4 (VK_PHYSICAL_DEVICE_TYPE_CPU)
[WIN_X64_VK] FINAL_STATUS: WIN_X64_VULKAN_OK
"""
        res = classify_vulkan_run(
            stdout, "", exit_code=0, target_exit=0, timed_out=False, cleanup_errors=["orphan PID 1234 not terminated"]
        )
        self.assertEqual(res["verdict"], "CLEANUP_FAILURE")

    def test_classify_success_rejected_if_target_nonzero(self):
        stdout = """
[WIN_X64_VK] Device Properties:
  - deviceName: llvmpipe (LLVM 23.1)
  - deviceType: 4 (VK_PHYSICAL_DEVICE_TYPE_CPU)
[WIN_X64_VK] FINAL_STATUS: WIN_X64_VULKAN_OK
"""
        res = classify_vulkan_run(
            stdout, "", exit_code=0, target_exit=1, timed_out=False, cleanup_errors=[]
        )
        self.assertNotEqual(res["verdict"], "WIN_X64_VULKAN_ENUM_SUCCESS")

    def test_classify_desktop_timeout(self):
        stdout = """
[WIN_X64_VK] Starting Windows x64 Vulkan Enumeration Test
[WIN_X64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
[WIN_X64_VK] SUCCESS: vulkan-1.dll loaded at 0xfc050000
[WIN_X64_VK] Step 2: Resolving Vulkan function pointers...
[WIN_X64_VK] SUCCESS: All function pointers resolved.
[WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
"""
        stderr = """
0024:trace:vulkan:vulkan_init_once - VK_KHR_surface
00dc:err:win:get_desktop_window failed to create desktop window
"""
        res = classify_vulkan_run(
            stdout, stderr, exit_code=124, target_exit=None, timed_out=True, cleanup_errors=[]
        )
        self.assertEqual(res["verdict"], "VK_CREATE_INSTANCE_DESKTOP_WINDOW_TIMEOUT")
        self.assertEqual(res["stage"], "VK_CREATE_INSTANCE_SURFACE_PROBE")

    def test_classify_load_failure(self):
        stdout = """
[WIN_X64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
[WIN_X64_VK] ERROR: LoadLibraryA("vulkan-1.dll") failed. GetLastError=126
"""
        res = classify_vulkan_run(
            stdout, "", exit_code=10, target_exit=10, timed_out=False, cleanup_errors=[]
        )
        self.assertEqual(res["verdict"], "VULKAN_DLL_LOAD_FAILURE")

    def test_classify_non_cpu_rejection(self):
        stdout = """
[WIN_X64_VK] Device Properties:
  - deviceName: llvmpipe (LLVM 23.1)
  - deviceType: 2 (VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU)
[WIN_X64_VK] ERROR: Device is not VK_PHYSICAL_DEVICE_TYPE_CPU
"""
        res = classify_vulkan_run(
            stdout, "", exit_code=15, target_exit=15, timed_out=False, cleanup_errors=[]
        )
        self.assertEqual(res["verdict"], "NON_CPU_DEVICE_REJECTED")

    def test_classify_non_llvmpipe_rejection(self):
        stdout = """
[WIN_X64_VK] Device Properties:
  - deviceName: SomeHardwareGPU
  - deviceType: 4 (VK_PHYSICAL_DEVICE_TYPE_CPU)
[WIN_X64_VK] ERROR: Device name does not match expected software rasterizer
"""
        res = classify_vulkan_run(
            stdout, "", exit_code=15, target_exit=15, timed_out=False, cleanup_errors=[]
        )
        self.assertEqual(res["verdict"], "NON_CPU_DEVICE_REJECTED")

    def test_classify_desktop_timeout_after_instance_created(self):
        # Negative test: If VkInstance was already created, a subsequent desktop timeout
        # must NOT be falsely classified as VK_CREATE_INSTANCE_DESKTOP_WINDOW_TIMEOUT.
        stdout = """
[WIN_X64_VK] Starting Windows x64 Vulkan Enumeration Test
[WIN_X64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
[WIN_X64_VK] SUCCESS: vulkan-1.dll loaded at 0xfc050000
[WIN_X64_VK] Step 2: Resolving Vulkan function pointers...
[WIN_X64_VK] SUCCESS: All function pointers resolved.
[WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
[WIN_X64_VK] SUCCESS: VkInstance created at 0x12345678
[WIN_X64_VK] Step 4: Querying physical device count...
"""
        stderr = """
00dc:err:win:get_desktop_window failed to create desktop window
"""
        res = classify_vulkan_run(
            stdout, stderr, exit_code=124, target_exit=None, timed_out=True, cleanup_errors=[]
        )
        self.assertNotEqual(res["verdict"], "VK_CREATE_INSTANCE_DESKTOP_WINDOW_TIMEOUT")
        self.assertEqual(res["verdict"], "AFTER_INSTANCE_DESKTOP_WINDOW_TIMEOUT")
        self.assertEqual(res["stage"], "POST_INSTANCE_CREATION")


if __name__ == "__main__":
    unittest.main()
