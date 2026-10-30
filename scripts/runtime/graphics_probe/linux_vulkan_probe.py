#!/usr/bin/env python3
"""
Linux Vulkan Loader & Device Enumeration Probe
Runs under Linux Python inside the sysroot via elfuse.
"""

import ctypes
import json
import os
import sys

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

class VkApplicationInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 0 = VK_STRUCTURE_TYPE_APPLICATION_INFO
        ("pNext", ctypes.c_void_p),
        ("pApplicationName", ctypes.c_char_p),
        ("applicationVersion", ctypes.c_uint32),
        ("pEngineName", ctypes.c_char_p),
        ("engineVersion", ctypes.c_uint32),
        ("apiVersion", ctypes.c_uint32),
    ]

class VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int),  # 1 = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("pApplicationInfo", ctypes.POINTER(VkApplicationInfo)),
        ("enabledLayerCount", ctypes.c_uint32),
        ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32),
        ("ppEnabledExtensionNames", ctypes.c_void_p),
    ]

def probe_vulkan():
    report = {
        "platform": sys.platform,
        "python_version": sys.version,
        "loader": {
            "resolved_path": None,
            "dlopen_success": False,
            "dlopen_error": None,
        },
        "icd_configs": [],
        "instance_version": None,
        "create_instance": {
            "called": False,
            "vk_result_code": None,
            "vk_result_name": None,
            "instance_created": False,
        },
        "physical_devices": {
            "enumerate_called": False,
            "vk_result_code": None,
            "vk_result_name": None,
            "device_count_valid": False,
            "device_count": None,
            "devices": [],
        },
        "verdict": None,
    }

    # 1. 检查 ICD 配置文件
    icd_dirs = ["/usr/share/vulkan/icd.d", "/etc/vulkan/icd.d"]
    for d in icd_dirs:
        if os.path.isdir(d):
            for fname in os.listdir(d):
                if fname.endswith(".json"):
                    fpath = os.path.join(d, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            content = json.load(f)
                    except Exception as e:
                        content = {"parse_error": str(e)}
                    report["icd_configs"].append({
                        "path": fpath,
                        "content": content
                    })

    # 2. 定位并动态加载 libvulkan
    loader_candidates = [
        "libvulkan.so.1",
        "libvulkan.so",
        "/usr/lib/libvulkan.so.1",
        "/usr/lib/libvulkan.so",
    ]
    vk = None
    for cand in loader_candidates:
        try:
            vk = ctypes.CDLL(cand)
            report["loader"]["resolved_path"] = cand
            report["loader"]["dlopen_success"] = True
            break
        except Exception as e:
            report["loader"]["dlopen_error"] = str(e)

    if not vk:
        report["verdict"] = "VULKAN_LOADER_NOT_FOUND"
        print(json.dumps(report, indent=2))
        return report

    # 3. 检查 vkEnumerateInstanceVersion
    if hasattr(vk, "vkEnumerateInstanceVersion"):
        try:
            vkEnumerateInstanceVersion = vk.vkEnumerateInstanceVersion
            vkEnumerateInstanceVersion.restype = ctypes.c_int
            vkEnumerateInstanceVersion.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
            api_ver = ctypes.c_uint32(0)
            res = vkEnumerateInstanceVersion(ctypes.byref(api_ver))
            val = api_ver.value
            major = val >> 22
            minor = (val >> 12) & 0x3ff
            patch = val & 0xfff
            report["instance_version"] = {
                "raw": val,
                "formatted": f"{major}.{minor}.{patch}",
                "vk_result": res,
            }
        except Exception as e:
            report["instance_version"] = {"error": str(e)}

    # 4. 调用 vkCreateInstance
    if not hasattr(vk, "vkCreateInstance"):
        report["verdict"] = "VK_CREATE_INSTANCE_SYMBOL_MISSING"
        print(json.dumps(report, indent=2))
        return report

    vkCreateInstance = vk.vkCreateInstance
    vkCreateInstance.restype = ctypes.c_int
    vkCreateInstance.argtypes = [
        ctypes.POINTER(VkInstanceCreateInfo),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]

    app_info = VkApplicationInfo(
        sType=0,
        pNext=None,
        pApplicationName=b"VulkanCapabilityProbe",
        applicationVersion=1,
        pEngineName=b"ProbeEngine",
        engineVersion=1,
        apiVersion=(1 << 22) | (0 << 12) | 0,  # 1.0.0
    )

    create_info = VkInstanceCreateInfo(
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
    report["create_instance"]["called"] = True
    try:
        ret = vkCreateInstance(
            ctypes.byref(create_info),
            None,
            ctypes.byref(instance),
        )
        report["create_instance"]["vk_result_code"] = ret
        report["create_instance"]["vk_result_name"] = VK_RESULT_NAMES.get(ret, f"VK_UNKNOWN_RESULT_{ret}")
    except Exception as e:
        report["create_instance"]["exception"] = str(e)
        report["verdict"] = "VK_CREATE_INSTANCE_EXCEPTION"
        print(json.dumps(report, indent=2))
        return report

    if ret != 0:
        report["create_instance"]["instance_created"] = False
        report["verdict"] = f"INSTANCE_CREATION_FAILED_{report['create_instance']['vk_result_name']}"
        print(json.dumps(report, indent=2))
        return report

    report["create_instance"]["instance_created"] = True

    # 5. 调用 vkEnumeratePhysicalDevices
    if hasattr(vk, "vkEnumeratePhysicalDevices"):
        report["physical_devices"]["enumerate_called"] = True
        vkEnumeratePhysicalDevices = vk.vkEnumeratePhysicalDevices
        vkEnumeratePhysicalDevices.restype = ctypes.c_int
        vkEnumeratePhysicalDevices.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        dev_count = ctypes.c_uint32(0)
        try:
            res_dev = vkEnumeratePhysicalDevices(instance, ctypes.byref(dev_count), None)
            report["physical_devices"]["vk_result_code"] = res_dev
            report["physical_devices"]["vk_result_name"] = VK_RESULT_NAMES.get(res_dev, f"VK_UNKNOWN_{res_dev}")

            if res_dev == 0:
                report["physical_devices"]["device_count_valid"] = True
                report["physical_devices"]["device_count"] = dev_count.value
                if dev_count.value > 0:
                    dev_array_type = ctypes.c_void_p * dev_count.value
                    dev_array = dev_array_type()
                    vkEnumeratePhysicalDevices(instance, ctypes.byref(dev_count), dev_array)
                    for i in range(dev_count.value):
                        report["physical_devices"]["devices"].append(hex(dev_array[i] or 0))
                    report["verdict"] = "VULKAN_DEVICE_AVAILABLE"
                else:
                    report["verdict"] = "VULKAN_ZERO_DEVICES_ENUMERATED"
            else:
                # 枚举失败，count 无效不可信
                report["physical_devices"]["device_count_valid"] = False
                report["physical_devices"]["device_count"] = None
                report["verdict"] = "VK_DEVICE_ENUMERATION_FAILED"
        except Exception as e:
            report["physical_devices"]["exception"] = str(e)
            report["verdict"] = "ENUMERATE_DEVICES_EXCEPTION"

    # 销毁实例
    if hasattr(vk, "vkDestroyInstance") and instance.value:
        vkDestroyInstance = vk.vkDestroyInstance
        vkDestroyInstance.restype = None
        vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        try:
            vkDestroyInstance(instance, None)
        except Exception:
            pass

    print(json.dumps(report, indent=2))
    return report

if __name__ == "__main__":
    probe_vulkan()
