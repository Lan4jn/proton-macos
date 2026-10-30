#!/usr/bin/env python3
"""
scripts/runtime/vulkan_queue/probe_queue_fill.py

Linux Python ctypes probe for Lavapipe software Vulkan queue fill & memory readback:
1. Initialize Lavapipe instance and CPU physical device
2. Create logical device and queue
3. Create 256-byte buffer (TRANSFER_DST) and allocate HOST_VISIBLE memory
4. Record vkCmdFillBuffer with pattern 0x1234ABCD
5. Submit with fence and wait (up to 3 seconds)
6. Map memory and verify every uint32 word equals 0x1234ABCD
7. Clean up all resources in reverse order
"""

import ctypes
import json
import os
import struct
import sys
import time

VK_RESULT_NAMES = {
    0: "VK_SUCCESS",
    1: "VK_NOT_READY",
    2: "VK_TIMEOUT",
    3: "VK_EVENT_SET",
    4: "VK_EVENT_RESET",
    5: "VK_INCOMPLETE",
    -1: "VK_ERROR_OUT_OF_HOST_MEMORY",
    -2: "VK_ERROR_OUT_OF_DEVICE_MEMORY",
    -3: "VK_ERROR_INITIALIZATION_FAILED",
    -4: "VK_ERROR_DEVICE_LOST",
    -5: "VK_ERROR_MEMORY_MAP_FAILED",
    -6: "VK_ERROR_LAYER_NOT_PRESENT",
    -7: "VK_ERROR_EXTENSION_NOT_PRESENT",
    -8: "VK_ERROR_FEATURE_NOT_PRESENT",
    -9: "VK_ERROR_INCOMPATIBLE_DRIVER",
    -10: "VK_ERROR_TOO_MANY_OBJECTS",
    -11: "VK_ERROR_FORMAT_NOT_SUPPORTED",
    -12: "VK_ERROR_FRAGMENTED_POOL",
    -13: "VK_ERROR_UNKNOWN",
}

def vk_res_str(code):
    return VK_RESULT_NAMES.get(code, f"UNKNOWN_RESULT_{code}")

# --- Vulkan Structure Definitions (AArch64 64-bit C ABI) ---

class VkApplicationInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 0
        ("pNext", ctypes.c_void_p),
        ("pApplicationName", ctypes.c_char_p),
        ("applicationVersion", ctypes.c_uint32),
        ("pEngineName", ctypes.c_char_p),
        ("engineVersion", ctypes.c_uint32),
        ("apiVersion", ctypes.c_uint32),
    ]

class VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 1
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("pApplicationInfo", ctypes.POINTER(VkApplicationInfo)),
        ("enabledLayerCount", ctypes.c_uint32),
        ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32),
        ("ppEnabledExtensionNames", ctypes.c_void_p),
    ]

class VkExtent3D(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("depth", ctypes.c_uint32),
    ]

class VkQueueFamilyProperties(ctypes.Structure):
    _fields_ = [
        ("queueFlags", ctypes.c_uint32),
        ("queueCount", ctypes.c_uint32),
        ("timestampValidBits", ctypes.c_uint32),
        ("minImageTransferGranularity", VkExtent3D),
    ]

class VkDeviceQueueCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 2
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("queueFamilyIndex", ctypes.c_uint32),
        ("queueCount", ctypes.c_uint32),
        ("pQueuePriorities", ctypes.POINTER(ctypes.c_float)),
    ]

class VkDeviceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 3
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("queueCreateInfoCount", ctypes.c_uint32),
        ("pQueueCreateInfos", ctypes.POINTER(VkDeviceQueueCreateInfo)),
        ("enabledLayerCount", ctypes.c_uint32),
        ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32),
        ("ppEnabledExtensionNames", ctypes.c_void_p),
        ("pEnabledFeatures", ctypes.c_void_p),
    ]

class VkBufferCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 12
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("size", ctypes.c_uint64),
        ("usage", ctypes.c_uint32),
        ("sharingMode", ctypes.c_int),
        ("queueFamilyIndexCount", ctypes.c_uint32),
        ("pQueueFamilyIndices", ctypes.c_void_p),
    ]

class VkMemoryRequirements(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint64),
        ("alignment", ctypes.c_uint64),
        ("memoryTypeBits", ctypes.c_uint32),
    ]

class VkMemoryType(ctypes.Structure):
    _fields_ = [
        ("propertyFlags", ctypes.c_uint32),
        ("heapIndex", ctypes.c_uint32),
    ]

class VkMemoryHeap(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint64),
        ("flags", ctypes.c_uint32),
    ]

class VkPhysicalDeviceMemoryProperties(ctypes.Structure):
    _fields_ = [
        ("memoryTypeCount", ctypes.c_uint32),
        ("memoryTypes", VkMemoryType * 32),
        ("memoryHeapCount", ctypes.c_uint32),
        ("memoryHeaps", VkMemoryHeap * 16),
    ]

class VkMemoryAllocateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 5
        ("pNext", ctypes.c_void_p),
        ("allocationSize", ctypes.c_uint64),
        ("memoryTypeIndex", ctypes.c_uint32),
    ]

class VkCommandPoolCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 39
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("queueFamilyIndex", ctypes.c_uint32),
    ]

class VkCommandBufferAllocateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 40
        ("pNext", ctypes.c_void_p),
        ("commandPool", ctypes.c_uint64),
        ("level", ctypes.c_int),
        ("commandBufferCount", ctypes.c_uint32),
    ]

class VkCommandBufferBeginInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 42
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("pInheritanceInfo", ctypes.c_void_p),
    ]

class VkSubmitInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 4
        ("pNext", ctypes.c_void_p),
        ("waitSemaphoreCount", ctypes.c_uint32),
        ("pWaitSemaphores", ctypes.c_void_p),
        ("pWaitDstStageMask", ctypes.c_void_p),
        ("commandBufferCount", ctypes.c_uint32),
        ("pCommandBuffers", ctypes.POINTER(ctypes.c_void_p)),
        ("signalSemaphoreCount", ctypes.c_uint32),
        ("pSignalSemaphores", ctypes.c_void_p),
    ]

class VkFenceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 8
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
    ]

class VkMappedMemoryRange(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 6
        ("pNext", ctypes.c_void_p),
        ("memory", ctypes.c_uint64),
        ("offset", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
    ]

def verify_pattern_data(raw_bytes: bytes, pattern: int = 0x1234ABCD, size: int = 256):
    if len(raw_bytes) != size:
        return False, "SIZE_MISMATCH", {"expected": size, "actual": len(raw_bytes)}
    word_count = size // 4
    words = struct.unpack(f"<{word_count}I", raw_bytes)
    mismatches = []
    for i, w in enumerate(words):
        if w != pattern:
            mismatches.append({"index": i, "expected": hex(pattern), "actual": hex(w)})
            if len(mismatches) >= 5:
                break
    if mismatches:
        return False, "PATTERN_MISMATCH", {"mismatch_count": len(mismatches), "first": mismatches[0]}
    return True, "PATTERN_MATCH_OK", {"words_matched": word_count, "pattern": hex(pattern)}

def run_queue_fill_probe():
    report = {
        "status": "RUNNING",
        "stages": {},
        "readback_verdict": None,
        "cleanup": {},
        "error": None,
    }

    # 1. Preload LLVM 23.1
    llvm_path = "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/lib/libLLVM.so.23.1"
    if os.path.isfile(llvm_path):
        try:
            ctypes.CDLL(llvm_path, ctypes.RTLD_GLOBAL)
            report["stages"]["llvm_preload"] = "OK"
        except Exception as e:
            report["stages"]["llvm_preload"] = f"FAILED: {e}"

    # 2. Load Vulkan Loader
    try:
        vk = ctypes.CDLL("libvulkan.so.1")
        report["stages"]["loader_load"] = "OK"
    except Exception as e:
        report["status"] = "FAIL"
        report["error"] = f"dlopen libvulkan.so.1 failed: {e}"
        print(json.dumps(report, indent=2))
        return report

    # 3. Create Instance
    vkCreateInstance = vk.vkCreateInstance
    vkCreateInstance.restype = ctypes.c_int
    vkCreateInstance.argtypes = [ctypes.POINTER(VkInstanceCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]

    app_info = VkApplicationInfo(
        sType=0,
        pNext=None,
        pApplicationName=b"QueueFillProbe",
        applicationVersion=1,
        pEngineName=b"ProbeEngine",
        engineVersion=1,
        apiVersion=(1 << 22) | (0 << 12) | 0,
    )
    inst_info = VkInstanceCreateInfo(
        sType=1,
        pNext=None,
        flags=0,
        pApplicationInfo=ctypes.pointer(app_info),
        enabledLayerCount=0,
        ppEnabledLayerNames=None,
        enabledExtensionCount=0,
        ppEnabledExtensionNames=None,
    )
    instance = ctypes.c_void_p(0)
    res = vkCreateInstance(ctypes.byref(inst_info), None, ctypes.byref(instance))
    report["stages"]["create_instance"] = {"res": res, "status": vk_res_str(res)}
    if res != 0:
        report["status"] = "FAIL"
        report["error"] = f"vkCreateInstance failed: {vk_res_str(res)}"
        print(json.dumps(report, indent=2))
        return report

    # 4. Enumerate Physical Devices & Find CPU/Lavapipe
    vkEnumeratePhysicalDevices = vk.vkEnumeratePhysicalDevices
    vkEnumeratePhysicalDevices.restype = ctypes.c_int
    vkEnumeratePhysicalDevices.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p)]

    dev_count = ctypes.c_uint32(0)
    vkEnumeratePhysicalDevices(instance, ctypes.byref(dev_count), None)
    if dev_count.value == 0:
        report["status"] = "FAIL"
        report["error"] = "No physical devices found"
        vk.vkDestroyInstance(instance, None)
        print(json.dumps(report, indent=2))
        return report

    devices = (ctypes.c_void_p * dev_count.value)()
    res = vkEnumeratePhysicalDevices(instance, ctypes.byref(dev_count), devices)
    phys_dev = devices[0]
    report["stages"]["physical_device"] = {"count": dev_count.value, "handle": hex(phys_dev if phys_dev is not None else 0)}

    # 5. Query Queue Family Properties
    vkGetPhysicalDeviceQueueFamilyProperties = vk.vkGetPhysicalDeviceQueueFamilyProperties
    vkGetPhysicalDeviceQueueFamilyProperties.restype = None
    vkGetPhysicalDeviceQueueFamilyProperties.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(VkQueueFamilyProperties)]

    q_count = ctypes.c_uint32(0)
    vkGetPhysicalDeviceQueueFamilyProperties(phys_dev, ctypes.byref(q_count), None)
    q_props = (VkQueueFamilyProperties * q_count.value)()
    vkGetPhysicalDeviceQueueFamilyProperties(phys_dev, ctypes.byref(q_count), q_props)

    queue_family_index = None
    for idx, qp in enumerate(q_props):
        # Flags: GRAPHICS=1, COMPUTE=2, TRANSFER=4
        if qp.queueFlags & 0x7:
            queue_family_index = idx
            break

    if queue_family_index is None:
        report["status"] = "FAIL"
        report["error"] = "No suitable transfer/compute queue family found"
        vk.vkDestroyInstance(instance, None)
        print(json.dumps(report, indent=2))
        return report

    report["stages"]["queue_family"] = {"index": queue_family_index, "flags": q_props[queue_family_index].queueFlags}

    # 6. Create Device
    vkCreateDevice = vk.vkCreateDevice
    vkCreateDevice.restype = ctypes.c_int
    vkCreateDevice.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkDeviceCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]

    priority = ctypes.c_float(1.0)
    q_create = VkDeviceQueueCreateInfo(
        sType=2,
        pNext=None,
        flags=0,
        queueFamilyIndex=queue_family_index,
        queueCount=1,
        pQueuePriorities=ctypes.pointer(priority),
    )
    dev_info = VkDeviceCreateInfo(
        sType=3,
        pNext=None,
        flags=0,
        queueCreateInfoCount=1,
        pQueueCreateInfos=ctypes.pointer(q_create),
        enabledLayerCount=0,
        ppEnabledLayerNames=None,
        enabledExtensionCount=0,
        ppEnabledExtensionNames=None,
        pEnabledFeatures=None,
    )
    device = ctypes.c_void_p(0)
    res = vkCreateDevice(phys_dev, ctypes.byref(dev_info), None, ctypes.byref(device))
    report["stages"]["create_device"] = {"res": res, "status": vk_res_str(res)}
    if res != 0:
        report["status"] = "FAIL"
        report["error"] = f"vkCreateDevice failed: {vk_res_str(res)}"
        vk.vkDestroyInstance(instance, None)
        print(json.dumps(report, indent=2))
        return report

    # 7. Get Device Queue
    vkGetDeviceQueue = vk.vkGetDeviceQueue
    vkGetDeviceQueue.restype = None
    vkGetDeviceQueue.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    queue = ctypes.c_void_p(0)
    vkGetDeviceQueue(device, queue_family_index, 0, ctypes.byref(queue))
    report["stages"]["get_queue"] = {"handle": hex(queue.value)}

    # 8. Create Buffer (256 bytes, TRANSFER_DST)
    buffer_size = 256
    vkCreateBuffer = vk.vkCreateBuffer
    vkCreateBuffer.restype = ctypes.c_int
    vkCreateBuffer.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkBufferCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]

    buf_info = VkBufferCreateInfo(
        sType=12,
        pNext=None,
        flags=0,
        size=buffer_size,
        usage=2,  # VK_BUFFER_USAGE_TRANSFER_DST_BIT
        sharingMode=0,  # VK_SHARING_MODE_EXCLUSIVE
        queueFamilyIndexCount=0,
        pQueueFamilyIndices=None,
    )
    buffer = ctypes.c_uint64(0)
    res = vkCreateBuffer(device, ctypes.byref(buf_info), None, ctypes.byref(buffer))
    report["stages"]["create_buffer"] = {"res": res, "status": vk_res_str(res), "handle": hex(buffer.value)}
    if res != 0:
        report["status"] = "FAIL"
        report["error"] = f"vkCreateBuffer failed: {vk_res_str(res)}"
        vk.vkDestroyDevice(device, None)
        vk.vkDestroyInstance(instance, None)
        print(json.dumps(report, indent=2))
        return report

    # 9. Get Buffer Memory Requirements & Memory Properties
    vkGetBufferMemoryRequirements = vk.vkGetBufferMemoryRequirements
    vkGetBufferMemoryRequirements.restype = None
    vkGetBufferMemoryRequirements.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.POINTER(VkMemoryRequirements)]

    mem_reqs = VkMemoryRequirements()
    vkGetBufferMemoryRequirements(device, buffer.value, ctypes.byref(mem_reqs))

    vkGetPhysicalDeviceMemoryProperties = vk.vkGetPhysicalDeviceMemoryProperties
    vkGetPhysicalDeviceMemoryProperties.restype = None
    vkGetPhysicalDeviceMemoryProperties.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkPhysicalDeviceMemoryProperties)]

    mem_props = VkPhysicalDeviceMemoryProperties()
    vkGetPhysicalDeviceMemoryProperties(phys_dev, ctypes.byref(mem_props))

    # Select HOST_VISIBLE memory type
    chosen_type_idx = None
    is_coherent = False
    for i in range(mem_props.memoryTypeCount):
        if (mem_reqs.memoryTypeBits & (1 << i)):
            flags = mem_props.memoryTypes[i].propertyFlags
            if flags & 0x00000002:  # VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT
                chosen_type_idx = i
                is_coherent = bool(flags & 0x00000004)  # VK_MEMORY_PROPERTY_HOST_COHERENT_BIT
                if is_coherent:
                    break

    if chosen_type_idx is None:
        report["status"] = "FAIL"
        report["error"] = "No HOST_VISIBLE memory type found for buffer"
        vk.vkDestroyBuffer(device, buffer.value, None)
        vk.vkDestroyDevice(device, None)
        vk.vkDestroyInstance(instance, None)
        print(json.dumps(report, indent=2))
        return report

    report["stages"]["memory_selection"] = {
        "type_index": chosen_type_idx,
        "is_coherent": is_coherent,
        "required_size": mem_reqs.size,
    }

    # 10. Allocate & Bind Memory
    vkAllocateMemory = vk.vkAllocateMemory
    vkAllocateMemory.restype = ctypes.c_int
    vkAllocateMemory.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkMemoryAllocateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]

    alloc_info = VkMemoryAllocateInfo(
        sType=5,
        pNext=None,
        allocationSize=mem_reqs.size,
        memoryTypeIndex=chosen_type_idx,
    )
    device_memory = ctypes.c_uint64(0)
    res = vkAllocateMemory(device, ctypes.byref(alloc_info), None, ctypes.byref(device_memory))
    report["stages"]["allocate_memory"] = {"res": res, "status": vk_res_str(res), "handle": hex(device_memory.value)}
    if res != 0:
        report["status"] = "FAIL"
        report["error"] = f"vkAllocateMemory failed: {vk_res_str(res)}"
        vk.vkDestroyBuffer(device, buffer.value, None)
        vk.vkDestroyDevice(device, None)
        vk.vkDestroyInstance(instance, None)
        print(json.dumps(report, indent=2))
        return report

    vkBindBufferMemory = vk.vkBindBufferMemory
    vkBindBufferMemory.restype = ctypes.c_int
    vkBindBufferMemory.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
    res = vkBindBufferMemory(device, buffer.value, device_memory.value, 0)
    report["stages"]["bind_buffer"] = {"res": res, "status": vk_res_str(res)}
    if res != 0:
        report["status"] = "FAIL"
        report["error"] = f"vkBindBufferMemory failed: {vk_res_str(res)}"
        vk.vkFreeMemory(device, device_memory.value, None)
        vk.vkDestroyBuffer(device, buffer.value, None)
        vk.vkDestroyDevice(device, None)
        vk.vkDestroyInstance(instance, None)
        print(json.dumps(report, indent=2))
        return report

    # 11. Create Command Pool
    vkCreateCommandPool = vk.vkCreateCommandPool
    vkCreateCommandPool.restype = ctypes.c_int
    vkCreateCommandPool.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkCommandPoolCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]

    cp_info = VkCommandPoolCreateInfo(
        sType=39,
        pNext=None,
        flags=2,  # VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT
        queueFamilyIndex=queue_family_index,
    )
    cmd_pool = ctypes.c_uint64(0)
    res = vkCreateCommandPool(device, ctypes.byref(cp_info), None, ctypes.byref(cmd_pool))
    report["stages"]["create_command_pool"] = {"res": res, "status": vk_res_str(res)}
    if res != 0:
        report["status"] = "FAIL"
        report["error"] = f"vkCreateCommandPool failed: {vk_res_str(res)}"
        vk.vkFreeMemory(device, device_memory.value, None)
        vk.vkDestroyBuffer(device, buffer.value, None)
        vk.vkDestroyDevice(device, None)
        vk.vkDestroyInstance(instance, None)
        print(json.dumps(report, indent=2))
        return report

    # 12. Allocate Command Buffer
    vkAllocateCommandBuffers = vk.vkAllocateCommandBuffers
    vkAllocateCommandBuffers.restype = ctypes.c_int
    vkAllocateCommandBuffers.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkCommandBufferAllocateInfo), ctypes.POINTER(ctypes.c_void_p)]

    cb_alloc = VkCommandBufferAllocateInfo(
        sType=40,
        pNext=None,
        commandPool=cmd_pool.value,
        level=0,  # VK_COMMAND_BUFFER_LEVEL_PRIMARY
        commandBufferCount=1,
    )
    cmd_buf = ctypes.c_void_p(0)
    res = vkAllocateCommandBuffers(device, ctypes.byref(cb_alloc), ctypes.byref(cmd_buf))
    report["stages"]["allocate_command_buffer"] = {"res": res, "status": vk_res_str(res)}
    if res != 0:
        report["status"] = "FAIL"
        report["error"] = f"vkAllocateCommandBuffers failed: {vk_res_str(res)}"
        vk.vkDestroyCommandPool(device, cmd_pool.value, None)
        vk.vkFreeMemory(device, device_memory.value, None)
        vk.vkDestroyBuffer(device, buffer.value, None)
        vk.vkDestroyDevice(device, None)
        vk.vkDestroyInstance(instance, None)
        print(json.dumps(report, indent=2))
        return report

    # 13. Create Fence
    vkCreateFence = vk.vkCreateFence
    vkCreateFence.restype = ctypes.c_int
    vkCreateFence.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkFenceCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]

    fence_info = VkFenceCreateInfo(sType=8, pNext=None, flags=0)
    fence = ctypes.c_uint64(0)
    res = vkCreateFence(device, ctypes.byref(fence_info), None, ctypes.byref(fence))
    report["stages"]["create_fence"] = {"res": res, "status": vk_res_str(res)}

    # 14. Record vkCmdFillBuffer
    vkBeginCommandBuffer = vk.vkBeginCommandBuffer
    vkBeginCommandBuffer.restype = ctypes.c_int
    vkBeginCommandBuffer.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkCommandBufferBeginInfo)]

    begin_info = VkCommandBufferBeginInfo(sType=42, pNext=None, flags=1, pInheritanceInfo=None)
    res = vkBeginCommandBuffer(cmd_buf, ctypes.byref(begin_info))
    report["stages"]["begin_command_buffer"] = {"res": res, "status": vk_res_str(res)}

    vkCmdFillBuffer = vk.vkCmdFillBuffer
    vkCmdFillBuffer.restype = None
    vkCmdFillBuffer.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32]
    # Fill 256 bytes with 0x1234ABCD
    pattern = 0x1234ABCD
    vkCmdFillBuffer(cmd_buf, buffer.value, 0, buffer_size, pattern)
    report["stages"]["cmd_fill_buffer"] = {"pattern": hex(pattern), "size": buffer_size}

    vkEndCommandBuffer = vk.vkEndCommandBuffer
    vkEndCommandBuffer.restype = ctypes.c_int
    vkEndCommandBuffer.argtypes = [ctypes.c_void_p]
    res = vkEndCommandBuffer(cmd_buf)
    report["stages"]["end_command_buffer"] = {"res": res, "status": vk_res_str(res)}

    # 15. Queue Submit
    vkQueueSubmit = vk.vkQueueSubmit
    vkQueueSubmit.restype = ctypes.c_int
    vkQueueSubmit.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(VkSubmitInfo), ctypes.c_uint64]

    submit_info = VkSubmitInfo(
        sType=4,
        pNext=None,
        waitSemaphoreCount=0,
        pWaitSemaphores=None,
        pWaitDstStageMask=None,
        commandBufferCount=1,
        pCommandBuffers=ctypes.pointer(cmd_buf),
        signalSemaphoreCount=0,
        pSignalSemaphores=None,
    )
    t_submit = time.time()
    res = vkQueueSubmit(queue, 1, ctypes.byref(submit_info), fence.value)
    report["stages"]["queue_submit"] = {"res": res, "status": vk_res_str(res)}

    # 16. Wait for Fences (3.0 seconds max)
    vkWaitForFences = vk.vkWaitForFences
    vkWaitForFences.restype = ctypes.c_int
    vkWaitForFences.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint32, ctypes.c_uint64]

    fence_timeout_ns = 3000000000  # 3 seconds
    fences_arr = (ctypes.c_uint64 * 1)(fence.value)
    res = vkWaitForFences(device, 1, fences_arr, 1, fence_timeout_ns)
    elapsed_fence = time.time() - t_submit
    report["stages"]["wait_fence"] = {
        "res": res,
        "status": vk_res_str(res),
        "elapsed_sec": elapsed_fence,
    }

    # 17. Memory Map & Readback
    if res == 0:
        vkMapMemory = vk.vkMapMemory
        vkMapMemory.restype = ctypes.c_int
        vkMapMemory.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]

        mapped_ptr = ctypes.c_void_p(0)
        res_map = vkMapMemory(device, device_memory.value, 0, buffer_size, 0, ctypes.byref(mapped_ptr))
        report["stages"]["map_memory"] = {"res": res_map, "status": vk_res_str(res_map)}

        if res_map == 0:
            if not is_coherent:
                vkInvalidateMappedMemoryRanges = vk.vkInvalidateMappedMemoryRanges
                vkInvalidateMappedMemoryRanges.restype = ctypes.c_int
                vkInvalidateMappedMemoryRanges.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(VkMappedMemoryRange)]
                mem_range = VkMappedMemoryRange(
                    sType=6,
                    pNext=None,
                    memory=device_memory.value,
                    offset=0,
                    size=buffer_size,
                )
                vkInvalidateMappedMemoryRanges(device, 1, ctypes.byref(mem_range))

            read_bytes = ctypes.string_at(mapped_ptr.value, buffer_size)
            matched, reason, details = verify_pattern_data(read_bytes, pattern, buffer_size)
            report["readback_verdict"] = {
                "matched": matched,
                "reason": reason,
                "details": details,
            }
            if matched:
                report["status"] = "SUCCESS"
            else:
                report["status"] = "FAIL"
                report["error"] = f"Memory readback mismatch: {reason}"

            vkUnmapMemory = vk.vkUnmapMemory
            vkUnmapMemory.restype = None
            vkUnmapMemory.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
            vkUnmapMemory(device, device_memory.value)
            report["stages"]["unmap_memory"] = "OK"
    else:
        report["status"] = "FAIL"
        report["error"] = f"Fence wait failed or timed out: {vk_res_str(res)}"

    # 18. Cleanup in strict reverse order
    try:
        vk.vkDestroyFence(device, fence.value, None)
        report["cleanup"]["fence"] = "DESTROYED"
        vk.vkFreeCommandBuffers(device, cmd_pool.value, 1, ctypes.byref(cmd_buf))
        report["cleanup"]["command_buffer"] = "FREED"
        vk.vkDestroyCommandPool(device, cmd_pool.value, None)
        report["cleanup"]["command_pool"] = "DESTROYED"
        vk.vkDestroyBuffer(device, buffer.value, None)
        report["cleanup"]["buffer"] = "DESTROYED"
        vk.vkFreeMemory(device, device_memory.value, None)
        report["cleanup"]["memory"] = "FREED"
        vk.vkDestroyDevice(device, None)
        report["cleanup"]["device"] = "DESTROYED"
        vk.vkDestroyInstance(instance, None)
        report["cleanup"]["instance"] = "DESTROYED"
    except Exception as e:
        report["cleanup"]["error"] = str(e)

    print(json.dumps(report, indent=2))
    return report

if __name__ == "__main__":
    run_queue_fill_probe()
