#!/usr/bin/env python3
"""
scripts/runtime/badalloc_phase/run_badalloc_phase_test.py

Automated test harness for Task-47 (v3 Phase-Instrumented C++ Observer).
Tests all 4 cases across both Baseline (no LD_PRELOAD) and Interposed (with libbadalloc_phase.so):
Case 1: Pure C main (only libc, constructor resolution deferred, exit 0)
Case 2: Direct C++ application (throw 42 / catch int, exit 0)
Case 3: Pure C main loading C++ DSO via dlopen(..., RTLD_LOCAL) (exit 0)
Case 4: Direct call to std::__throw_bad_alloc() helper (helper entry + __cxa_throw entry, exit 0)
"""

import hashlib
import json
import os
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.backend.process import run_isolated

def sha256_file(p: Path) -> str:
    if not p.is_file():
        return "NOT_FOUND"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def main():
    elfuse_bin = LAB_ROOT / "sources" / "elfuse-lifecycle-derived" / "build" / "elfuse"
    sysroot = LAB_ROOT / "fixtures" / "runtime" / "arch-case"
    tracer_so = LAB_ROOT / "fixtures" / "runtime" / "badalloc-phase" / "libbadalloc_phase.so"
    dir_phase = LAB_ROOT / "fixtures" / "runtime" / "badalloc-phase"
    log_dir = LAB_ROOT / "logs" / "badalloc-phase"
    log_dir.mkdir(parents=True, exist_ok=True)

    test_pure_c = dir_phase / "test_pure_c"
    test_throw42 = dir_phase / "test_throw42"
    test_dlopen = dir_phase / "test_dlopen_local"
    plugin_so = dir_phase / "plugin_cpp.so"
    test_bad_alloc = dir_phase / "test_bad_alloc"

    hashes = {
        "elfuse_lifecycle_derived": sha256_file(elfuse_bin),
        "libbadalloc_phase_so": sha256_file(tracer_so),
        "test_pure_c": sha256_file(test_pure_c),
        "test_throw42": sha256_file(test_throw42),
        "test_dlopen_local": sha256_file(test_dlopen),
        "plugin_cpp_so": sha256_file(plugin_so),
        "test_bad_alloc": sha256_file(test_bad_alloc),
    }

    print("================================================================")
    print("Task-47: Linux ARM64 C++ Observer v3 Phase-Marker Test Suite")
    print(f"  elfuse SHA-256:             {hashes['elfuse_lifecycle_derived']}")
    print(f"  libbadalloc_phase_so SHA:   {hashes['libbadalloc_phase_so']}")
    print("================================================================")

    test_matrix = [
        {
            "id": "CASE1_PURE_C",
            "desc": "Case 1: Pure C main (only libc, deferred resolve)",
            "cmd": [str(test_pure_c)],
            "expected_stdout": "CASE1_PURE_C_OK",
            "required_interposed_markers": [
                "[PHASE_TRACE] INIT_ENTER",
                "[PHASE_TRACE] INIT_RESOLVE_DEFERRED",
                "[PHASE_TRACE] INIT_DONE",
            ],
            "prohibited_interposed_markers": [
                "[PHASE_TRACE] THROW_ENTER",
                "FATAL",
            ]
        },
        {
            "id": "CASE2_DIRECT_THROW42",
            "desc": "Case 2: Direct C++ throw 42 / catch int",
            "cmd": [str(test_throw42)],
            "expected_stdout": "CASE2_THROW42_OK",
            "required_interposed_markers": [
                "[PHASE_TRACE] INIT_ENTER",
                "[PHASE_TRACE] RESOLVE_NEXT_OK: __cxa_throw",
                "[PHASE_TRACE] THROW_ENTER | caller_pc:",
                "[PHASE_TRACE] BACKTRACE_ENTER",
                "[PHASE_TRACE] BACKTRACE_DONE",
                "[PHASE_TRACE] FORWARD_ENTER: calling real __cxa_throw",
            ],
            "prohibited_interposed_markers": ["FATAL", "THROW_RESOLVE_FAIL"]
        },
        {
            "id": "CASE3_DLOPEN_LOCAL",
            "desc": "Case 3: C main loading C++ DSO via dlopen(RTLD_LOCAL)",
            "cmd": [str(test_dlopen), str(plugin_so)],
            "expected_stdout": "CASE3_DLOPEN_OK",
            "required_interposed_markers": [
                "[PHASE_TRACE] INIT_ENTER",
                "[PHASE_TRACE] INIT_RESOLVE_DEFERRED",
                "[PHASE_TRACE] THROW_ENTER | caller_pc:",
                "[PHASE_TRACE] RESOLVE_NOLOAD_OK: __cxa_throw in libstdc++.so.6",
                "[PHASE_TRACE] BACKTRACE_ENTER",
                "[PHASE_TRACE] FORWARD_ENTER: calling real __cxa_throw",
            ],
            "prohibited_interposed_markers": ["FATAL", "THROW_RESOLVE_FAIL"]
        },
        {
            "id": "CASE4_THROW_BAD_ALLOC",
            "desc": "Case 4: Direct call to std::__throw_bad_alloc() helper",
            "cmd": [str(test_bad_alloc)],
            "expected_stdout": "CASE4_BAD_ALLOC_OK",
            "required_interposed_markers": [
                "[PHASE_TRACE] INIT_ENTER",
                "[PHASE_TRACE] THROW_BAD_ALLOC_HELPER_ENTER | caller_pc:",
                "[PHASE_TRACE] HELPER_BACKTRACE_ENTER",
                "[PHASE_TRACE] HELPER_FORWARD_ENTER: calling real _ZSt17__throw_bad_allocv",
                "[PHASE_TRACE] THROW_ENTER | caller_pc:",
            ],
            "prohibited_interposed_markers": ["FATAL", "HELPER_RESOLVE_FAIL"]
        },
    ]

    summary = {
        "hashes": hashes,
        "cases": {},
        "all_passed": True,
    }

    for t in test_matrix:
        cid = t["id"]
        print(f"\n--- Testing {t['desc']} ---")

        # 1. Baseline Run (No LD_PRELOAD)
        argv_base = [
            str(elfuse_bin),
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--sysroot", str(sysroot),
            "--timeout", "10",
        ] + t["cmd"]

        r_base = run_isolated(argv_base, log_dir, timeout=12)
        out_base = Path(r_base["stdout"]).read_text(encoding="utf-8", errors="replace").strip()
        err_base = Path(r_base["stderr"]).read_text(encoding="utf-8", errors="replace")

        base_clean = (r_base["exit"] == 0 and
                      r_base.get("target_exit") == 0 and
                      t["expected_stdout"] in out_base and
                      "[PHASE_TRACE]" not in err_base and
                      "[BADALLOC_TRACE]" not in err_base)

        print(f"  [Baseline] exit={r_base['exit']}, stdout_match={'YES' if t['expected_stdout'] in out_base else 'NO'}, trace_clean={'YES' if base_clean else 'NO'}")

        # 2. Interposed Run (With libbadalloc_phase.so via --env LD_PRELOAD)
        argv_inter = [
            str(elfuse_bin),
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--sysroot", str(sysroot),
            "--timeout", "10",
            "--env", f"LD_PRELOAD={tracer_so}",
        ] + t["cmd"]

        r_inter = run_isolated(argv_inter, log_dir, timeout=12)
        out_inter = Path(r_inter["stdout"]).read_text(encoding="utf-8", errors="replace").strip()
        err_inter = Path(r_inter["stderr"]).read_text(encoding="utf-8", errors="replace")

        # Check required markers
        missing_markers = [m for m in t["required_interposed_markers"] if m not in err_inter]
        prohibited_seen = [m for m in t["prohibited_interposed_markers"] if m in err_inter]

        inter_pass = (r_inter["exit"] == 0 and
                      r_inter.get("target_exit") == 0 and
                      t["expected_stdout"] in out_inter and
                      not missing_markers and
                      not prohibited_seen)

        print(f"  [Interposed] exit={r_inter['exit']}, stdout_match={'YES' if t['expected_stdout'] in out_inter else 'NO'}, all_markers={'YES' if not missing_markers else 'NO'}")
        if missing_markers:
            print(f"    Missing required markers: {missing_markers}")
        if prohibited_seen:
            print(f"    Saw prohibited markers: {prohibited_seen}")

        case_ok = base_clean and inter_pass
        if not case_ok:
            summary["all_passed"] = False

        summary["cases"][cid] = {
            "description": t["desc"],
            "baseline_passed": base_clean,
            "interposed_passed": inter_pass,
            "overall_passed": case_ok,
            "base_run_dir": r_base["run_dir"],
            "inter_run_dir": r_inter["run_dir"],
            "missing_markers": missing_markers,
            "prohibited_seen": prohibited_seen,
        }

    summary_file = log_dir / "phase_verification_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\n================================================================")
    print(f"Overall Test Suite Result: {'PASS (ALL 4 CASES VERIFIED)' if summary['all_passed'] else 'FAIL'}")
    print(f"Summary written to: {summary_file}")
    print("================================================================")

    return 0 if summary["all_passed"] else 1

if __name__ == "__main__":
    sys.exit(main())
