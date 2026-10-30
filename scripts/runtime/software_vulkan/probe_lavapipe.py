#!/usr/bin/env python3
"""
scripts/runtime/software_vulkan/probe_lavapipe.py

Linux Python ctypes probe for Lavapipe (CPU software rasterizer Vulkan driver).
Inspects dynamic loading, instance creation, and physical device enumeration/properties.
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

VK_DEVICE_TYPE_NAMES = {
    0: "VK_PHYSICAL_DEVICE_TYPE_OTHER",
    1: "VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU",
    2: "VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU",
    3: "VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU",
    4: "VK_PHYSICAL_DEVICE_TYPE_CPU",
}

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

class VkPhysicalDevicePropertiesMinimal(ctypes.Structure):
    _fields_ = [
        ("apiVersion", ctypes.c_uint32),
        ("driverVersion", ctypes.c_uint32),
        ("vendorID", ctypes.c_uint32),
        ("deviceID", ctypes.c_uint32),
        ("deviceType", ctypes.c_int),
        ("deviceName", ctypes.c_char * 256),
        ("pipelineCacheUUID", ctypes.c_uint8 * 16),
        ("remainingLimitsData", ctypes.c_uint8 * 820),
    ]

def probe():
    report = {
        "platform": sys.platform,
        "python_version": sys.version,
        "env": {
            "VK_ICD_FILENAMES": os.environ.get("VK_ICD_FILENAMES"),
            "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH"),
        },
        "llvm_preload": {
            "attempted": False,
            "success": False,
            "error": None,
        },
        "loader": {
            "resolved_path": None,
            "dlopen_success": False,
            "dlopen_error": None,
        },
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

    # 1. 自动预加载 LLVM 23.1
    llvm_candidates = [
        "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/lib/libLLVM.so.23.1",
        "/usr/lib/libLLVM.so.23.1",
    ]
    for lp in llvm_candidates:
        if os.path.isfile(lp):
            report["llvm_preload"]["attempted"] = True
            try:
                ctypes.CDLL(lp, ctypes.RTLD_GLOBAL)
                report["llvm_preload"]["success"] = True
                break
            except Exception as e:
                report["llvm_preload"]["error"] = str(e)

    # 2. 动态加载 libvulkan loader
    loader_paths = ["libvulkan.so.1", "/usr/lib/libvulkan.so.1"]
    vk = None
    for p in loader_paths:
        try:
            vk = ctypes.CDLL(p)
            report["loader"]["resolved_path"] = p
            report["loader"]["dlopen_success"] = True
            break
        except Exception as e:
            report["loader"]["dlopen_error"] = str(e)

    if not vk:
        report["verdict"] = "LOADER_DLOPEN_FAILED"
        print(json.dumps(report, indent=2))
        return report

    # 3. 实例版本
    if hasattr(vk, "vkEnumerateInstanceVersion"):
        try:
            vkEnumerateInstanceVersion = vk.vkEnumerateInstanceVersion
            vkEnumerateInstanceVersion.restype = ctypes.c_int
            vkEnumerateInstanceVersion.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
            api_ver = ctypes.c_uint32(0)
            res = vkEnumerateInstanceVersion(ctypes.byref(api_ver))
            val = api_ver.value
            report["instance_version"] = {
                "raw": val,
                "formatted": f"{val >> 22}.{(val >> 12) & 0x3ff}.{val & 0xfff}",
                "vk_result": res,
            }
        except Exception as e:
            report["instance_version"] = {"error": str(e)}

    # 4. 创建实例
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
        pApplicationName=b"LavapipeSoftwareProbe",
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
        ret = vkCreateInstance(ctypes.byref(create_info), None, ctypes.byref(instance))
        report["create_instance"]["vk_result_code"] = ret
        report["create_instance"]["vk_result_name"] = VK_RESULT_NAMES.get(ret, f"VK_UNKNOWN_{ret}")
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

    # 5. 枚举物理设备
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
            res_count = vkEnumeratePhysicalDevices(instance, ctypes.byref(dev_count), None)
            report["physical_devices"]["vk_result_code"] = res_count
            report["physical_devices"]["vk_result_name"] = VK_RESULT_NAMES.get(res_count, f"VK_UNKNOWN_{res_count}")

            if res_count == 0:
                report["physical_devices"]["device_count_valid"] = True
                report["physical_devices"]["device_count"] = dev_count.value

                if dev_count.value > 0:
                    dev_array_type = ctypes.c_void_p * dev_count.value
                    dev_array = dev_array_type()
                    vkEnumeratePhysicalDevices(instance, ctypes.byref(dev_count), dev_array)

                    vkGetPhysicalDeviceProperties = getattr(vk, "vkGetPhysicalDeviceProperties", None)
                    if vkGetPhysicalDeviceProperties:
                        vkGetPhysicalDeviceProperties.restype = None
                        vkGetPhysicalDeviceProperties.argtypes = [
                            ctypes.c_void_p,
                            ctypes.POINTER(VkPhysicalDevicePropertiesMinimal),
                        ]

                    for i in range(dev_count.value):
                        dev_handle = dev_array[i]
                        dev_info = {
                            "index": i,
                            "handle": hex(dev_handle or 0),
                            "properties": None,
                        }
                        if vkGetPhysicalDeviceProperties:
                            props = VkPhysicalDevicePropertiesMinimal()
                            try:
                                vkGetPhysicalDeviceProperties(dev_handle, ctypes.byref(props))
                                dev_name = props.deviceName.decode("utf-8", errors="replace").strip()
                                type_name = VK_DEVICE_TYPE_NAMES.get(props.deviceType, f"UNKNOWN_{props.deviceType}")
                                dev_info["properties"] = {
                                    "device_name": dev_name,
                                    "device_type": type_name,
                                    "vendor_id": hex(props.vendorID),
                                    "device_id": hex(props.deviceID),
                                    "api_version": f"{props.apiVersion >> 22}.{(props.apiVersion >> 12) & 0x3ff}.{props.apiVersion & 0xfff}",
                                    "driver_version": hex(props.driverVersion),
                                }
                            except Exception as pe:
                                dev_info["properties_error"] = str(pe)
                        report["physical_devices"]["devices"].append(dev_info)

                    report["verdict"] = "LAVAPIPE_SOFTWARE_DEVICE_ENUMERATED"
                else:
                    report["verdict"] = "VULKAN_ZERO_DEVICES_ENUMERATED"
            else:
                report["physical_devices"]["device_count_valid"] = False
                report["physical_devices"]["device_count"] = None
                report["verdict"] = "VK_DEVICE_ENUMERATION_FAILED"
        except Exception as e:
            report["physical_devices"]["exception"] = str(e)
            report["verdict"] = "ENUMERATE_DEVICES_EXCEPTION"

    # 6. 销毁实例
    if hasattr(vk, "vkDestroyInstance") and instance.value:
        try:
            vk.vkDestroyInstance.restype = None
            vk.vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            vk.vkDestroyInstance(instance, None)
        except Exception:
            pass

    print(json.dumps(report, indent=2))
    return report

if __name__ == "__main__":
    probe()
