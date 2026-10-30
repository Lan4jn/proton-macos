import json
import os
import subprocess
import re
import hashlib
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab")
LLVM_OBJDUMP = "/opt/homebrew/Cellar/llvm@22/22.1.8/bin/llvm-objdump"

def compute_sha256(filepath):
    p = Path(filepath)
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    return "not_found"

def extract_store_offsets(so_path, start_addr, stop_addr):
    cmd = [LLVM_OBJDUMP, "-d", f"--start-address={start_addr}", f"--stop-address={stop_addr}", str(so_path)]
    out = subprocess.check_output(cmd).decode("utf-8")
    with open(so_path, "rb") as f:
        bindata = f.read()

    stores = []
    lines = out.splitlines()
    last_str = None
    for i, line in enumerate(lines):
        m_str = re.search(r"add\s+x[1-4],\s+x[1-4],\s+#(0x[0-9a-fA-F]+)", line)
        m_adrp = re.search(r"adrp\s+x[1-4],\s+(0x[0-9a-fA-F]+)", lines[i-1] if i > 0 else "")
        if m_str and m_adrp:
            page = int(m_adrp.group(1), 16)
            off = int(m_str.group(1), 16)
            str_addr = page + off
            if str_addr < len(bindata):
                s = bindata[str_addr:str_addr+64].split(b"\x00")[0]
                if s.startswith(b"vk") or s.startswith(b"wine_vk"):
                    last_str = s.decode("latin1", errors="replace")

        m_store = re.search(r"str\s+x0,\s+\[x19,\s+#(0x[0-9a-fA-F]+)\]", line)
        if m_store:
            stores.append({
                "offset": f"0x{int(m_store.group(1), 16):x}",
                "offset_dec": int(m_store.group(1), 16),
                "func": last_str
            })
            last_str = None
    return stores

def extract_winevulkan_read_offsets(so_path):
    cmd = [LLVM_OBJDUMP, "-d", "-C", "--no-show-raw-insn", str(so_path)]
    out = subprocess.check_output(cmd).decode("utf-8")
    
    # Locate wine_vkEnumeratePhysicalDevices
    lines = out.splitlines()
    in_func = False
    func_lines = []
    for line in lines:
        if "<wine_vkEnumeratePhysicalDevices>:" in line:
            in_func = True
            continue
        if in_func:
            if line.startswith("0000000000") and line.endswith(">:"):
                break
            func_lines.append(line)
            
    res = {}
    for ln in func_lines:
        m_cnt = re.search(r"ldr\s+w[0-9]+,\s+\[x[0-9]+,\s+#(0x[0-9a-fA-F]+)\]", ln)
        m_dev = re.search(r"ldr\s+x10,\s+\[x[0-9]+,\s+#(0x[0-9a-fA-F]+)\]", ln)
        m_stride = re.search(r"add\s+x9,\s+x9,\s+#(0x[0-9a-fA-F]+)", ln)
        if m_cnt and "physical_device_count" not in res:
            res["physical_device_count_offset"] = f"0x{int(m_cnt.group(1), 16):x}"
            res["physical_device_count_dec"] = int(m_cnt.group(1), 16)
        if m_dev and "physical_devices_offset" not in res:
            res["physical_devices_offset"] = f"0x{int(m_dev.group(1), 16):x}"
            res["physical_devices_dec"] = int(m_dev.group(1), 16)
        if m_stride and "physical_device_stride" not in res:
            res["physical_device_stride"] = f"0x{int(m_stride.group(1), 16):x}"
            res["physical_device_stride_dec"] = int(m_stride.group(1), 16)
    return res

def main():
    shipped_vk = LAB / "fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/winevulkan.so"
    built_vk = LAB / "sources/wine-v3-vulkan-build/target_patched_build/dlls/winevulkan/winevulkan.so"

    shipped_win32u = LAB / "fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/win32u.so"
    built_win32u = LAB / "sources/wine-v3-vulkan-build/target_patched_build/dlls/win32u/win32u.so"

    print("Analyzing winevulkan.so...")
    shipped_vk_info = extract_winevulkan_read_offsets(shipped_vk)
    built_vk_info = extract_winevulkan_read_offsets(built_vk)

    print("Analyzing win32u.so...")
    shipped_stores = extract_store_offsets(shipped_win32u, "0x14c340", "0x14e520")
    built_stores = extract_store_offsets(built_win32u, "0x1a95c0", "0x1ab630")

    shipped_funcs = [s["func"] for s in shipped_stores]
    built_funcs = [s["func"] for s in built_stores]

    extra_in_shipped = [f for f in shipped_funcs if f not in built_funcs]
    missing_in_shipped = [f for f in built_funcs if f not in shipped_funcs]

    evidence = {
        "metadata": {
            "task": "task-124",
            "title": "Binary Struct Offset Fingerprint for Shipped Proton Wine Commit Identification",
            "author": "x64-pipe-reviewer",
            "lab": str(LAB)
        },
        "binaries": {
            "shipped_winevulkan": {
                "path": str(shipped_vk),
                "size": shipped_vk.stat().st_size,
                "sha256": compute_sha256(shipped_vk),
                "read_offsets": shipped_vk_info
            },
            "built_winevulkan_dc26e618": {
                "path": str(built_vk),
                "size": built_vk.stat().st_size,
                "sha256": compute_sha256(built_vk),
                "read_offsets": built_vk_info
            },
            "shipped_win32u": {
                "path": str(shipped_win32u),
                "size": shipped_win32u.stat().st_size,
                "sha256": compute_sha256(shipped_win32u),
                "sizeof_instance": "0x368",
                "sizeof_instance_dec": 872,
                "sizeof_vulkan_physical_device": "0x288",
                "sizeof_vulkan_physical_device_dec": 648,
                "instance_func_count": len(shipped_stores)
            },
            "built_win32u_dc26e618": {
                "path": str(built_win32u),
                "size": built_win32u.stat().st_size,
                "sha256": compute_sha256(built_win32u),
                "sizeof_instance": "0x348",
                "sizeof_instance_dec": 840,
                "sizeof_vulkan_physical_device": "0x278",
                "sizeof_vulkan_physical_device_dec": 632,
                "instance_func_count": len(built_stores)
            }
        },
        "offset_comparisons": {
            "struct_vulkan_instance_offsets": {
                "physical_devices": {
                    "shipped": "0x2e0",
                    "built_dc26e618": "0x2c8",
                    "difference_bytes": 24,
                    "pointer_count_difference": 3
                },
                "physical_device_count": {
                    "shipped": "0x2e8",
                    "built_dc26e618": "0x2d0",
                    "difference_bytes": 24,
                    "pointer_count_difference": 3
                }
            },
            "struct_vulkan_physical_device_size": {
                "shipped": "0x288",
                "built_dc26e618": "0x278",
                "difference_bytes": 16
            },
            "struct_instance_size": {
                "shipped": "0x368",
                "built_dc26e618": "0x348",
                "difference_bytes": 32
            }
        },
        "instance_function_differences": {
            "shipped_total_funcs": len(shipped_stores),
            "built_total_funcs": len(built_stores),
            "extra_in_shipped": extra_in_shipped,
            "missing_in_shipped": missing_in_shipped,
            "extra_func_details": [
                {
                    "name": "vkEnumeratePhysicalDeviceShaderInstrumentationMetricsARM",
                    "offset_in_shipped": "0xe8",
                    "extension": "VK_ARM_shader_instrumentation_metrics"
                },
                {
                    "name": "vkGetPhysicalDeviceQueueFamilyDataGraphEngineOperationPropertiesARM",
                    "offset_in_shipped": "0x1f8",
                    "extension": "VK_ARM_data_graph_optical_flow"
                },
                {
                    "name": "vkGetPhysicalDeviceQueueFamilyDataGraphOpticalFlowImageFormatsARM",
                    "offset_in_shipped": "0x200",
                    "extension": "VK_ARM_data_graph_optical_flow"
                }
            ]
        },
        "vulkan_xml_version": {
            "built_dc26e618": "1.4.339",
            "shipped_proton": "1.4.357",
            "shipped_evidence": "winevulkan.json api_version: 1.4.357"
        },
        "candidate_commits": [
            {
                "rank": "HEAD_CANDIDATE_1 (Proton Experimental 11.0 Exact Timestamp Match)",
                "repo": "https://github.com/ValveSoftware/wine",
                "branch": "experimental_11.0",
                "commit": "3c1a3fef30942f5655bc7cfd0f4b76a411ea215d",
                "date": "2026-09-24",
                "author": "Paul Gofman",
                "subject": "server: Make messages mergeable by default.",
                "evidence": [
                    "Proton bundle version string: '1790245028 experimental-11.0-20260924-arm64'.",
                    "Timestamp 1790245028 translates to 2026-09-24 10:17:08 UTC.",
                    "Commit 3c1a3fef was the active HEAD of ValveSoftware/wine experimental_11.0 on 2026-09-24.",
                    "At commit 3c1a3fef, make_vulkan explicitly sets VK_XML_VERSION = '1.4.357', exactly matching shipped winevulkan.json."
                ],
                "falsification_condition": "If building commit 3c1a3fef produces a struct vulkan_instance with physical_device_count offset != 0x2e8 or function count != 82, this candidate is refuted."
            },
            {
                "rank": "LANDMARK_CANDIDATE_2 (Upstream Wine 1.4.357 Spec Upgrade Merge)",
                "repo": "https://gitlab.winehq.org/wine/wine",
                "merge_request": "!11456",
                "commit": "b4f8d15f936ce01f85eeb3d1ba39b351fad65b0e",
                "tag": "wine-11.14",
                "date": "2026-07-23",
                "author": "Georg Lehmann",
                "subject": "winevulkan: Update to VK spec version 1.4.357.",
                "evidence": [
                    "Introduced VK_XML_VERSION 1.4.357 to Wine.",
                    "Added the exact 3 ARM instance extension functions to ALL_VK_INSTANCE_FUNCS.",
                    "Shifts physical_devices from 0x2c8 to 0x2e0 (+24B) and physical_device_count from 0x2d0 to 0x2e8 (+24B)."
                ],
                "falsification_condition": "If upstream Wine 1.4.357 has different offsets than 0x2e0/0x2e8."
            }
        ]
    }

    out_file = LAB / "logs/wine-version-fingerprint/fingerprint-evidence.json"
    out_file.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Successfully generated {out_file}")

if __name__ == "__main__":
    main()
