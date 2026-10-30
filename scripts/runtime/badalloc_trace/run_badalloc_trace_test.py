#!/usr/bin/env python3
"""
scripts/runtime/badalloc_trace/run_badalloc_trace_test.py

Comprehensive test harness for Linux ARM64 __cxa_throw interposer:
Suite A: Direct C++ ELF (throw_catch_test, dynamic libstdc++)
  - Run 1 (Baseline): Clean throw 42 -> catch 42 -> exit 0, no trace markers.
  - Run 2 (Interposed): LD_PRELOAD injection, captures [BADALLOC_TRACE], exact stack frames, exit 0.
Suite B: C main loading C++ DSO via dlopen(..., RTLD_LOCAL) (dlopen_main + plugin_cpp.so)
  - Run 3 (Baseline): Clean dlopen -> run_plugin_throw_catch -> exit 0, no trace markers.
  - Run 4 (Interposed): LD_PRELOAD with RTLD_NOLOAD fallback, captures [BADALLOC_TRACE], exact frames in plugin_cpp.so, exit 0.
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
    interposer_so = LAB_ROOT / "fixtures" / "runtime" / "badalloc-trace" / "libbadalloc_trace.so"
    test_exe = LAB_ROOT / "fixtures" / "runtime" / "badalloc-trace" / "throw_catch_test"
    dlopen_exe = LAB_ROOT / "fixtures" / "runtime" / "badalloc-trace" / "dlopen_main"
    plugin_so = LAB_ROOT / "fixtures" / "runtime" / "badalloc-trace" / "plugin_cpp.so"
    log_dir = LAB_ROOT / "logs" / "badalloc-trace"
    log_dir.mkdir(parents=True, exist_ok=True)

    hashes = {
        "elfuse_lifecycle_derived": sha256_file(elfuse_bin),
        "libbadalloc_trace_so": sha256_file(interposer_so),
        "throw_catch_test": sha256_file(test_exe),
        "dlopen_main": sha256_file(dlopen_exe),
        "plugin_cpp_so": sha256_file(plugin_so),
    }

    print("================================================================")
    print("Task-39: Linux ARM64 __cxa_throw Interposer Verification Harness")
    print(f"  elfuse SHA-256:         {hashes['elfuse_lifecycle_derived']}")
    print(f"  interposer SHA-256:     {hashes['libbadalloc_trace_so']}")
    print(f"  test binary SHA-256:    {hashes['throw_catch_test']}")
    print(f"  dlopen main SHA-256:    {hashes['dlopen_main']}")
    print(f"  plugin DSO SHA-256:     {hashes['plugin_cpp_so']}")
    print("================================================================")

    report = {
        "hashes": hashes,
        "suite_a_direct": {},
        "suite_b_dlopen_local": {},
        "verdict": "FAIL",
    }

    # -------------------------------------------------------------
    # Suite A: Direct C++ Binary
    # -------------------------------------------------------------
    print("\n--- [SUITE A.1] Baseline Direct C++ (No LD_PRELOAD) ---")
    argv_a1 = [
        str(elfuse_bin),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(sysroot),
        "--timeout", "10",
        str(test_exe),
    ]
    r_a1 = run_isolated(argv_a1, log_dir, timeout=15)
    out_a1 = Path(r_a1["stdout"]).read_text().strip()
    err_a1 = Path(r_a1["stderr"]).read_text().strip()
    a1_ok = (r_a1["exit"] == 0 and r_a1.get("target_exit") == 0 and "THROW_CATCH_42_OK" in out_a1 and "[BADALLOC_TRACE]" not in err_a1)
    print(f"  exit={r_a1['exit']}, target={r_a1.get('target_exit')}, stdout='{out_a1}', passed={a1_ok}")
    report["suite_a_direct"]["baseline"] = {"passed": a1_ok, "run_dir": r_a1["run_dir"]}

    print("\n--- [SUITE A.2] Interposed Direct C++ (With LD_PRELOAD) ---")
    argv_a2 = [
        str(elfuse_bin),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(sysroot),
        "--timeout", "10",
        "--env", f"LD_PRELOAD={interposer_so}",
        str(test_exe),
    ]
    r_a2 = run_isolated(argv_a2, log_dir, timeout=15)
    out_a2 = Path(r_a2["stdout"]).read_text().strip()
    err_a2 = Path(r_a2["stderr"]).read_text()
    trace_a2 = [l for l in err_a2.splitlines() if "[BADALLOC_TRACE]" in l]
    a2_ok = (r_a2["exit"] == 0 and r_a2.get("target_exit") == 0 and "THROW_CATCH_42_OK" in out_a2 and
             "[BADALLOC_TRACE] === C++ EXCEPTION THROWN ===" in err_a2 and
             any("throw_catch_test" in l for l in trace_a2))
    print(f"  exit={r_a2['exit']}, target={r_a2.get('target_exit')}, stdout='{out_a2}', trace_lines={len(trace_a2)}, passed={a2_ok}")
    report["suite_a_direct"]["interposed"] = {"passed": a2_ok, "trace_count": len(trace_a2), "run_dir": r_a2["run_dir"]}

    # -------------------------------------------------------------
    # Suite B: C Main with RTLD_LOCAL C++ DSO
    # -------------------------------------------------------------
    print("\n--- [SUITE B.1] Baseline C Main dlopen(RTLD_LOCAL) (No LD_PRELOAD) ---")
    argv_b1 = [
        str(elfuse_bin),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(sysroot),
        "--timeout", "10",
        str(dlopen_exe),
        str(plugin_so),
    ]
    r_b1 = run_isolated(argv_b1, log_dir, timeout=15)
    out_b1 = Path(r_b1["stdout"]).read_text().strip()
    err_b1 = Path(r_b1["stderr"]).read_text().strip()
    b1_ok = (r_b1["exit"] == 0 and r_b1.get("target_exit") == 0 and "DLOPEN_PLUGIN_42_OK" in out_b1 and "[BADALLOC_TRACE]" not in err_b1)
    print(f"  exit={r_b1['exit']}, target={r_b1.get('target_exit')}, stdout='{out_b1}', passed={b1_ok}")
    report["suite_b_dlopen_local"]["baseline"] = {"passed": b1_ok, "run_dir": r_b1["run_dir"]}

    print("\n--- [SUITE B.2] Interposed C Main dlopen(RTLD_LOCAL) (With LD_PRELOAD & RTLD_NOLOAD fallback) ---")
    argv_b2 = [
        str(elfuse_bin),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(sysroot),
        "--timeout", "10",
        "--env", f"LD_PRELOAD={interposer_so}",
        str(dlopen_exe),
        str(plugin_so),
    ]
    r_b2 = run_isolated(argv_b2, log_dir, timeout=15)
    out_b2 = Path(r_b2["stdout"]).read_text().strip()
    err_b2 = Path(r_b2["stderr"]).read_text()
    trace_b2 = [l for l in err_b2.splitlines() if "[BADALLOC_TRACE]" in l]
    b2_ok = (r_b2["exit"] == 0 and r_b2.get("target_exit") == 0 and "DLOPEN_PLUGIN_42_OK" in out_b2 and
             "[BADALLOC_TRACE] === C++ EXCEPTION THROWN ===" in err_b2 and
             any("plugin_cpp.so" in l for l in trace_b2))
    print(f"  exit={r_b2['exit']}, target={r_b2.get('target_exit')}, stdout='{out_b2}', trace_lines={len(trace_b2)}, passed={b2_ok}")
    for l in trace_b2:
        print("   ", l)
    report["suite_b_dlopen_local"]["interposed"] = {"passed": b2_ok, "trace_count": len(trace_b2), "run_dir": r_b2["run_dir"]}

    all_passed = a1_ok and a2_ok and b1_ok and b2_ok
    summary_file = log_dir / "interposer_verification_summary.json"
    if all_passed:
        report["verdict"] = "CXA_THROW_INTERPOSER_VERIFIED"
        summary_file.write_text(json.dumps(report, indent=2) + "\n")
        print("\n>>> VERDICT: CXA_THROW_INTERPOSER_VERIFIED (SUITE A & B ALL PASSED) <<<")
        return 0
    else:
        report["verdict"] = "FAILED"
        summary_file.write_text(json.dumps(report, indent=2) + "\n")
        print("\n>>> VERDICT: FAILED <<<")
        return 1

if __name__ == "__main__":
    sys.exit(main())
