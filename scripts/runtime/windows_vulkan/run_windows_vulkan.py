#!/usr/bin/env python3
"""
scripts/runtime/windows_vulkan/run_windows_vulkan.py

Controlled runner for Windows x64 Vulkan enumeration PE under Wine/FEX.
Uses final elfuse-lifecycle-derived runtime (f2a678dd...) and direct Wine
to avoid GUI desktop window issues in headless environments.
Configures lavapipe derived ICD and LD_LIBRARY_PATH for software Vulkan.
"""

import json
import os
import sys
import time
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.backend.process import run_isolated
from scripts.runtime.windows_vulkan.classifier import classify_vulkan_run, parse_vulkan_trace

LOGS_DIR = LAB_ROOT / "logs" / "windows-vulkan"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def main():
    elfuse_bin = LAB_ROOT / "sources" / "elfuse-lifecycle-derived" / "build" / "elfuse"
    sysroot = LAB_ROOT / "fixtures" / "runtime" / "arch-case"
    derived_root = LAB_ROOT / "fixtures" / "runtime" / "lavapipe-derived"
    derived_lib = derived_root / "usr" / "lib"
    icd_json = derived_root / "usr" / "share" / "vulkan" / "icd.d" / "lvp_icd.json"
    proton_bundle = LAB_ROOT / "fixtures" / "runtime" / "proton-derived"
    wine_bin = proton_bundle / "files" / "bin-arm64" / "wine"
    wineserver_bin = proton_bundle / "files" / "bin-arm64" / "wineserver"
    wine_unix_lib = proton_bundle / "files" / "lib" / "wine" / "aarch64-unix"
    prefix = LAB_ROOT / "fixtures" / "runtime" / "windows-vulkan" / "pfx"

    target_win_path = "C:\\vk_enum_x64.exe"
    timeout_sec = 100

    # Pass LD_LIBRARY_PATH inside the guest shell command line rather than host extra_env
    # to avoid host loader injection security rejection in process.py.
    guest_cmd = f'LD_LIBRARY_PATH="{derived_lib}:{wine_unix_lib}:{proton_bundle / "files/lib"}" "{wine_bin}" "{target_win_path}"'

    env = {
        "WINEPREFIX": str(prefix),
        "WINESERVER": str(wineserver_bin),
        "WINELOADER": str(wine_bin),
        "WINEDEBUG": "+loaddll,+process,+vulkan",
        "WINEDLLOVERRIDES": "explorer.exe=d",
        "WINEESYNC": "0",
        "WINEFSYNC": "0",
        "PROTON_NO_ESYNC": "1",
        "PROTON_NO_FSYNC": "1",
        "PROTON_NO_NTSYNC": "1",
        "PROTON_USE_ARM64": "1",
        "VK_ICD_FILENAMES": str(icd_json),
    }

    argv = [
        str(elfuse_bin),
        "--user", "501:20",
        "--sysroot", str(sysroot),
        "--timeout", "85",
        str(sysroot / "usr" / "bin" / "sh"),
        "-c",
        guest_cmd
    ]

    print("==========================================================")
    print("Task-35: Windows x64 Vulkan Enumeration under Wine/FEX")
    print(f"  Elfuse: {elfuse_bin}")
    print(f"  Target: {target_win_path}")
    print(f"  Prefix: {prefix}")
    print(f"  VK_ICD_FILENAMES: {icd_json}")
    print(f"  Timeout: {timeout_sec}s")
    print("==========================================================")

    t0 = time.monotonic()
    res = run_isolated(argv, LOGS_DIR, timeout=timeout_sec, extra_env=env)
    elapsed = time.monotonic() - t0

    stdout_path = Path(res["stdout"])
    stderr_path = Path(res["stderr"])

    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")

    parsed = parse_vulkan_trace(stderr_text, stdout_text)
    classification = classify_vulkan_run(
        stdout_text,
        stderr_text,
        res["exit"],
        res.get("target_exit"),
        res["timed_out"],
        res.get("cleanup_errors")
    )

    summary = {
        "elfuse_runtime": str(elfuse_bin),
        "target": target_win_path,
        "prefix": str(prefix),
        "argv": argv,
        "env_overrides": {k: env[k] for k in ["WINEPREFIX", "WINEDEBUG", "VK_ICD_FILENAMES"]},
        "guest_cmd": guest_cmd,
        "exit": res["exit"],
        "target_exit": res.get("target_exit"),
        "timed_out": res["timed_out"],
        "elapsed_seconds": round(elapsed, 2),
        "stdout": stdout_text,
        "has_win_x64_vulkan_ok": parsed["has_win_x64_vulkan_ok"],
        "device_name": parsed["device_name"],
        "device_type": parsed["device_type_int"],
        "vulkan_1_loaded": parsed["vulkan_1_loaded"],
        "winevulkan_dll_loaded": parsed["winevulkan_dll_loaded"],
        "fex_loaded": parsed["fex_loaded"],
        "winevulkan_unix_active": parsed["winevulkan_unix_active"],
        "classification": classification,
        "run_dir": str(res["run_dir"]),
        "cleanup_errors": res.get("cleanup_errors", []),
        "vulkan_trace_sample": parsed["vulkan_trace_sample"],
    }

    result_json_path = LOGS_DIR / "windows_vulkan_result.json"
    with open(result_json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[RUN RESULT] Completed in {elapsed:.2f}s")
    print(f"  Exit code: {res['exit']}")
    print(f"  Target exit: {res.get('target_exit')}")
    print(f"  Timed out: {res['timed_out']}")
    print(f"  vulkan-1.dll Loaded: {parsed['vulkan_1_loaded']}")
    print(f"  winevulkan.dll Loaded: {parsed['winevulkan_dll_loaded']}")
    print(f"  FEX Loaded: {parsed['fex_loaded']}")
    print(f"  Winevulkan Unix Active: {parsed['winevulkan_unix_active']}")
    print(f"  Device Name: {parsed['device_name']}")
    print(f"  Device Type: {parsed['device_type_int']}")
    print(f"  Classification: {classification['verdict']} ({classification['stage']})")
    print(f"  Message: {classification['message']}")
    print(f"  SUCCESS (WIN_X64_VULKAN_OK): {parsed['has_win_x64_vulkan_ok']}")
    print(f"  Run directory: {res['run_dir']}")

    if stdout_text:
        print("\n=== STDOUT ===")
        print(stdout_text)

    if parsed["has_win_x64_vulkan_ok"] and res.get("target_exit") == 0:
        print("\n[VERDICT] PASS: Windows x64 Vulkan successfully enumerated Lavapipe CPU device!")
        sys.exit(0)
    elif res.get("target_exit") is not None:
        sys.exit(res["target_exit"])
    else:
        sys.exit(res.get("exit", 1))


if __name__ == "__main__":
    main()
