"""
scripts/runtime/windows_vulkan/classifier.py

Production classifier and trace parser for Windows x64 Vulkan enumeration experiments.
Applies strict loaddll anchoring, CPU/llvmpipe verification, and error isolation.
"""

import re
from typing import Dict, Any, List, Optional


def parse_vulkan_trace(stderr_text: str, stdout_text: str) -> Dict[str, Any]:
    stderr_lines = stderr_text.splitlines()

    # Strict regex loaddll anchors: must match successful build_module of the DLL
    vulkan_1_loaded = any(
        bool(re.search(r'trace:loaddll:build_module Loaded L"[^"]*\\vulkan-1\.dll"', l))
        for l in stderr_lines
    )
    winevulkan_dll_loaded = any(
        bool(re.search(r'trace:loaddll:build_module Loaded L"[^"]*\\winevulkan\.dll"', l))
        for l in stderr_lines
    )
    fex_loaded = any(
        bool(re.search(r'trace:loaddll:build_module Loaded L"[^"]*\\libarm64ecfex\.dll"', l))
        for l in stderr_lines
    )

    # Positive winevulkan unix-side initialization: requires active vulkan_init_once trace
    winevulkan_unix_active = any(
        "trace:vulkan:vulkan_init_once" in l or "trace:vulkan:DllMain" in l
        for l in stderr_lines
    )

    # Extract device properties from stdout if printed
    device_name: Optional[str] = None
    device_type_int: Optional[int] = None
    for line in stdout_text.splitlines():
        if "deviceName:" in line:
            device_name = line.split("deviceName:", 1)[1].strip()
        if "deviceType:" in line:
            parts = line.split("deviceType:", 1)[1].strip().split()
            if parts:
                try:
                    device_type_int = int(parts[0])
                except ValueError:
                    pass

    has_win_x64_vulkan_ok = "WIN_X64_VULKAN_OK" in stdout_text
    has_desktop_fail = any(
        "get_desktop_window failed to create desktop window" in l or
        "get_desktop_window failed to start explorer" in l
        for l in stderr_lines
    )
    has_instance_step = "[WIN_X64_VK] Step 3: Calling vkCreateInstance" in stdout_text
    has_instance_created = "[WIN_X64_VK] SUCCESS: VkInstance created" in stdout_text

    vulkan_traces = [l.strip() for l in stderr_lines if "vulkan" in l.lower() or "vk" in l.lower()]

    return {
        "vulkan_1_loaded": vulkan_1_loaded,
        "winevulkan_dll_loaded": winevulkan_dll_loaded,
        "fex_loaded": fex_loaded,
        "winevulkan_unix_active": winevulkan_unix_active,
        "has_win_x64_vulkan_ok": has_win_x64_vulkan_ok,
        "device_name": device_name,
        "device_type_int": device_type_int,
        "has_desktop_fail": has_desktop_fail,
        "has_instance_step": has_instance_step,
        "has_instance_created": has_instance_created,
        "total_stderr_lines": len(stderr_lines),
        "vulkan_trace_sample": vulkan_traces[:25],
    }


def classify_vulkan_run(
    stdout_text: str,
    stderr_text: str,
    exit_code: int,
    target_exit: Optional[int],
    timed_out: bool,
    cleanup_errors: Optional[List[str]] = None
) -> Dict[str, Any]:
    trace = parse_vulkan_trace(stderr_text, stdout_text)
    cleanup_errors = cleanup_errors or []

    # Strict success criteria:
    # 1. Output marker WIN_X64_VULKAN_OK present
    # 2. device_type is 4 (VK_PHYSICAL_DEVICE_TYPE_CPU)
    # 3. device_name contains llvmpipe or lavapipe
    # 4. Overall exit 0, target_exit 0, timed_out False
    # 5. cleanup_errors is empty
    is_cpu = (trace["device_type_int"] == 4)
    is_llvmpipe = bool(trace["device_name"] and any(
        x in trace["device_name"].lower() for x in ["llvmpipe", "lavapipe"]
    ))
    no_cleanup_errors = (len(cleanup_errors) == 0)

    if (
        trace["has_win_x64_vulkan_ok"] and
        is_cpu and
        is_llvmpipe and
        exit_code == 0 and
        target_exit == 0 and
        not timed_out and
        no_cleanup_errors
    ):
        return {
            "verdict": "WIN_X64_VULKAN_ENUM_SUCCESS",
            "stage": "COMPLETE",
            "message": "Windows x64 successfully enumerated Lavapipe CPU Vulkan device via Wine/FEX",
            "trace": trace,
        }
    elif timed_out and trace["has_instance_step"] and not trace["has_instance_created"] and trace["has_desktop_fail"]:
        return {
            "verdict": "VK_CREATE_INSTANCE_DESKTOP_WINDOW_TIMEOUT",
            "stage": "VK_CREATE_INSTANCE_SURFACE_PROBE",
            "message": "Timed out during vkCreateInstance: winex11.drv explorer.exe desktop window creation loop",
            "trace": trace,
        }
    elif timed_out and trace["has_instance_created"] and trace["has_desktop_fail"]:
        return {
            "verdict": "AFTER_INSTANCE_DESKTOP_WINDOW_TIMEOUT",
            "stage": "POST_INSTANCE_CREATION",
            "message": "Timed out after VkInstance was successfully created: desktop window failure in subsequent stage",
            "trace": trace,
        }
    elif exit_code == 10 or 'LoadLibraryA("vulkan-1.dll") failed' in stdout_text:
        return {
            "verdict": "VULKAN_DLL_LOAD_FAILURE",
            "stage": "LOAD_LIBRARY",
            "message": "LoadLibraryA failed to locate or load vulkan-1.dll",
            "trace": trace,
        }
    elif exit_code == 15 or target_exit == 15 or 'Device is not VK_PHYSICAL_DEVICE_TYPE_CPU' in stdout_text:
        return {
            "verdict": "NON_CPU_DEVICE_REJECTED",
            "stage": "DEVICE_PROPERTIES_CHECK",
            "message": "Device was enumerated but rejected because it is not a software CPU device",
            "trace": trace,
        }
    elif not no_cleanup_errors:
        return {
            "verdict": "CLEANUP_FAILURE",
            "stage": "PROCESS_CLEANUP",
            "message": f"Process group cleanup reported errors: {cleanup_errors}",
            "trace": trace,
        }
    else:
        return {
            "verdict": "UNKNOWN_ERROR",
            "stage": "UNKNOWN",
            "message": f"Non-zero exit (exit={exit_code}, target={target_exit}) without recognized signature",
            "trace": trace,
        }
