#!/usr/bin/env python3
"""
scripts/runtime/wine_badalloc/test_run_classifier.py

Offline classifier unit tests validating exact status extraction and
classification across all 3 historical runs in logs/wine-badalloc/:
- run-2hb_cnux: PREP_FAIL_BROKEN_VULKAN_SYMLINK (LoadLibrary GetLastError 126)
- run-tkhs_6ra: PREP_FAIL_MISSING_DEPENDENCIES (user32.dll / ucrtbase.dll not found, GetLastError 126)
- run-qgaia7if: VULKAN_LOADED_BLOCKED_IN_CREATE_INSTANCE_TIMEOUT (vkCreateInstance entered, wine 85s timeout rc=-15, NO_TRACE)
"""

import json
from pathlib import Path
import sys

LAB_ROOT = Path(__file__).resolve().parents[3]
LOGS_DIR = LAB_ROOT / "logs" / "wine-badalloc"

def classify_wine_run(run_dir: Path) -> dict:
    wine_out = run_dir / "wine_stdout.log"
    wine_err = run_dir / "wine_stderr.log"
    ctrl_out = run_dir / "stdout.log"

    out_txt = wine_out.read_text(encoding="utf-8", errors="replace") if wine_out.is_file() else ""
    err_txt = wine_err.read_text(encoding="utf-8", errors="replace") if wine_err.is_file() else ""
    ctrl_txt = ctrl_out.read_text(encoding="utf-8", errors="replace") if ctrl_out.is_file() else ""

    trace_lines = [l for l in err_txt.splitlines() if "[BADALLOC_TRACE]" in l]
    badalloc_lines = [l for l in err_txt.splitlines() if "bad_alloc" in l]

    has_trace = len(trace_lines) > 0
    has_badalloc = len(badalloc_lines) > 0

    # Check DLL errors
    missing_user32 = "Library user32.dll" in err_txt and "not found" in err_txt
    missing_ucrtbase = "Library ucrtbase.dll" in err_txt and "not found" in err_txt
    loadlib_fail_126 = 'LoadLibraryA("vulkan-1.dll") failed. GetLastError=126' in out_txt

    # Check Vulkan progress
    vulkan_loaded = "SUCCESS: vulkan-1.dll loaded" in out_txt
    vk_create_entered = "trace:vulkan:vkCreateInstance" in err_txt or "vkCreateInstance" in err_txt
    wine_timed_out = "Wine reached maximum observation window (85.0s). Terminating..." in ctrl_txt or "Wine terminated on timeout (rc: -15)" in ctrl_txt

    if loadlib_fail_126 and (missing_user32 or missing_ucrtbase):
        classification = "PREP_FAIL_MISSING_DEPENDENCIES"
    elif loadlib_fail_126:
        classification = "PREP_FAIL_BROKEN_VULKAN_SYMLINK"
    elif vk_create_entered and wine_timed_out and not has_trace:
        classification = "VULKAN_LOADED_BLOCKED_IN_CREATE_INSTANCE_TIMEOUT"
    elif has_trace:
        classification = "BADALLOC_TRACE_CAPTURED"
    else:
        classification = "UNKNOWN_OUTCOME"

    return {
        "run_dir": run_dir.name,
        "classification": classification,
        "loadlib_fail_126": loadlib_fail_126,
        "missing_dependencies": missing_user32 or missing_ucrtbase,
        "vulkan_loaded": vulkan_loaded,
        "vk_create_entered": vk_create_entered,
        "wine_timed_out": wine_timed_out,
        "badalloc_trace_captured": has_trace,
        "std_bad_alloc_seen": has_badalloc,
        "observation_goal_reached": has_trace,
    }

def main():
    runs = {
        "run-2hb_cnux": "PREP_FAIL_BROKEN_VULKAN_SYMLINK",
        "run-tkhs_6ra": "PREP_FAIL_MISSING_DEPENDENCIES",
        "run-qgaia7if": "VULKAN_LOADED_BLOCKED_IN_CREATE_INSTANCE_TIMEOUT",
    }

    all_ok = True
    print("Testing offline run classification against historical logs...")
    for run_name, expected_class in runs.items():
        run_path = LOGS_DIR / run_name
        if not run_path.is_dir():
            print(f"  FAIL: {run_name} directory not found")
            all_ok = False
            continue
        res = classify_wine_run(run_path)
        actual_class = res["classification"]
        matched = (actual_class == expected_class)
        if not matched:
            all_ok = False
        print(f"  [{'PASS' if matched else 'FAIL'}] {run_name}: {actual_class} (expected: {expected_class})")
        print(f"         vulkan_loaded={res['vulkan_loaded']}, vk_create={res['vk_create_entered']}, timeout={res['wine_timed_out']}, trace={res['badalloc_trace_captured']}")

    if all_ok:
        print("\nALL 3 RUN CLASSIFICATION CHECKS PASSED.")
        return 0
    else:
        print("\nRUN CLASSIFICATION FAILED.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
