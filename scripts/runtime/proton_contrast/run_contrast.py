#!/usr/bin/env python3
"""
scripts/runtime/proton_contrast/run_contrast.py

Sequential contrast experiment runner for old candidate vs new lifecycle runtime
under the unmodified Proton Python launcher + true Linux Python 3.
Evaluates:
  - Old runtime: sources/elfuse-crash-derived/build/elfuse-candidate (f83455b0...)
  - New runtime: sources/elfuse-lifecycle-derived/build/elfuse (f2a678dd...)
Both run with identical arguments, identical environment, and identical snapshot prefixes.
Tracing: WINEDEBUG="+process,+loaddll"
Timeout: 140s outer supervisor watchdog.
"""

import json
import os
import sys
import time
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.backend.bundle import build_plan
from scripts.backend.process import run_isolated

LOGS_DIR = LAB_ROOT / "logs" / "proton-contrast"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def parse_trace(stderr_text: str):
    lines = stderr_text.splitlines()

    events = []
    fex_loaded = False
    hello_started = False
    hello_exited = False
    target_exit_code = None

    for line in lines:
        if "Loaded" in line and "libarm64ecfex.dll" in line:
            fex_loaded = True
            events.append(("FEX_DLL_LOADED", line.strip()))
        elif "NtCreateUserProcess" in line and "hello-x64.exe" in line:
            hello_started = True
            events.append(("HELLO_PROCESS_CREATED", line.strip()))
        elif "NtTerminateProcess" in line and "hello-x64" in line:
            hello_exited = True
            events.append(("HELLO_PROCESS_TERMINATED", line.strip()))
        elif "exit_code 0" in line and ("NtTerminateProcess" in line or "process_exiting" in line):
            events.append(("PROCESS_EXIT_0", line.strip()))
        elif "wineboot" in line and "NtCreateUserProcess" in line:
            events.append(("WINEBOOT_STARTED", line.strip()))
        elif "services.exe" in line and "NtCreateUserProcess" in line:
            events.append(("SERVICES_STARTED", line.strip()))
        elif "[HOST_CRASH]" in line:
            events.append(("HOST_CRASH", line.strip()))

    last_lines = [l.strip() for l in lines[-20:]] if lines else []

    return {
        "total_stderr_lines": len(lines),
        "fex_loaded": fex_loaded,
        "hello_started": hello_started,
        "hello_exited": hello_exited,
        "key_events": events[:30],
        "last_stderr_lines": last_lines,
    }


def execute_run(label: str, elfuse_rel_path: str, compat_dir: Path, timeout_sec: int = 140):
    manifest = LAB_ROOT / "artifacts" / "public-proton" / "bundle.json"
    sysroot = LAB_ROOT / "fixtures" / "runtime" / "arch-case"
    linux_python = LAB_ROOT / "fixtures" / "runtime" / "arch-case" / "usr" / "bin" / "python3"
    runtime_bundle = LAB_ROOT / "fixtures" / "runtime" / "proton-derived"
    elfuse_abs = LAB_ROOT / elfuse_rel_path
    prefix = compat_dir / "pfx"

    target_win_path = "C:\\hello-x64.exe"
    verb = "runinprefix"

    print(f"\n==========================================================")
    print(f"[{label.upper()} RUN] Building plan...")
    print(f"  Runtime: {elfuse_abs}")
    print(f"  Compat: {compat_dir}")
    print(f"  Prefix: {prefix}")
    print(f"  Target: {target_win_path} (Verb: {verb})")
    print(f"  Timeout: {timeout_sec}s")
    print(f"==========================================================")

    plan = build_plan(
        manifest=str(manifest),
        sysroot=str(sysroot),
        prefix=str(prefix),
        arguments=[verb, target_win_path],
        engine="proton",
        linux_python=str(linux_python),
        runtime_bundle=str(runtime_bundle),
        elfuse_path=str(elfuse_abs),
    )

    if plan.get("status") != "PLAN_READY":
        print(f"[ERROR] Plan failed: {plan.get('reason')}", file=sys.stderr)
        return {"status": "BLOCKED", "plan": plan}

    argv = plan["argv"]
    env = plan["env"]
    env["WINEDEBUG"] = "+process,+loaddll"
    env["PROTON_USE_ARM64"] = "1"
    env["WINEESYNC"] = "0"
    env["WINEFSYNC"] = "0"
    env["PROTON_NO_ESYNC"] = "1"
    env["PROTON_NO_FSYNC"] = "1"
    env["PROTON_NO_NTSYNC"] = "1"

    plan_record_file = LOGS_DIR / f"plan_{label}.json"
    with open(plan_record_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)

    t0 = time.monotonic()
    res = run_isolated(argv, LOGS_DIR, timeout=timeout_sec, extra_env=env)
    elapsed = time.monotonic() - t0

    stdout_path = Path(res["stdout"])
    stderr_path = Path(res["stderr"])

    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")

    has_x64_fex_ok = "X64_FEX_OK" in stdout_text
    trace_info = parse_trace(stderr_text)

    summary = {
        "label": label,
        "elfuse_path": str(elfuse_abs),
        "runtime_sha256": plan["runtime_descriptor"]["sha256"],
        "argv": argv,
        "exit": res["exit"],
        "target_exit": res.get("target_exit"),
        "timed_out": res["timed_out"],
        "elapsed_seconds": round(elapsed, 2),
        "stdout": stdout_text,
        "has_x64_fex_ok": has_x64_fex_ok,
        "run_dir": str(res["run_dir"]),
        "cleanup_errors": res.get("cleanup_errors", []),
        "trace_analysis": trace_info,
    }

    print(f"[{label.upper()} RESULT]")
    print(f"  Exit code: {res['exit']}")
    print(f"  Target exit: {res.get('target_exit')}")
    print(f"  Timed out: {res['timed_out']}")
    print(f"  Elapsed: {elapsed:.2f}s")
    print(f"  STDOUT: {repr(stdout_text)}")
    print(f"  Has X64_FEX_OK: {has_x64_fex_ok}")
    print(f"  FEX DLL loaded: {trace_info['fex_loaded']}")
    print(f"  Hello started: {trace_info['hello_started']}")
    print(f"  Total stderr lines: {trace_info['total_stderr_lines']}")
    print(f"  Run directory: {res['run_dir']}")

    res_file = LOGS_DIR / f"summary_{label}.json"
    with open(res_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def main():
    old_elfuse = "sources/elfuse-crash-derived/build/elfuse-candidate"
    new_elfuse = "sources/elfuse-lifecycle-derived/build/elfuse"

    old_compat = LAB_ROOT / "fixtures" / "runtime" / "proton-contrast" / "old" / "compat"
    new_compat = LAB_ROOT / "fixtures" / "runtime" / "proton-contrast" / "new" / "compat"

    print("==========================================================")
    print("STARTING SEQUENTIAL PROTON CONTRAST EXPERIMENT")
    print("==========================================================")

    # 1. Run OLD candidate first
    print("\n--- PHASE 1: OLD CANDIDATE RUN ---")
    old_res = execute_run("old", old_elfuse, old_compat, timeout_sec=140)

    # Allow system / HVF resources to settle
    print("\nWaiting 5 seconds for system settling before phase 2...")
    time.sleep(5)

    # 2. Run NEW lifecycle runtime second
    print("\n--- PHASE 2: NEW LIFECYCLE RUN ---")
    new_res = execute_run("new", new_elfuse, new_compat, timeout_sec=140)

    # Combine comparison
    contrast = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "old_candidate": {
            "sha256": old_res.get("runtime_sha256"),
            "exit": old_res.get("exit"),
            "target_exit": old_res.get("target_exit"),
            "timed_out": old_res.get("timed_out"),
            "elapsed_seconds": old_res.get("elapsed_seconds"),
            "has_x64_fex_ok": old_res.get("has_x64_fex_ok"),
            "fex_loaded": old_res.get("trace_analysis", {}).get("fex_loaded"),
            "hello_started": old_res.get("trace_analysis", {}).get("hello_started"),
            "run_dir": old_res.get("run_dir"),
        },
        "new_lifecycle": {
            "sha256": new_res.get("runtime_sha256"),
            "exit": new_res.get("exit"),
            "target_exit": new_res.get("target_exit"),
            "timed_out": new_res.get("timed_out"),
            "elapsed_seconds": new_res.get("elapsed_seconds"),
            "has_x64_fex_ok": new_res.get("has_x64_fex_ok"),
            "fex_loaded": new_res.get("trace_analysis", {}).get("fex_loaded"),
            "hello_started": new_res.get("trace_analysis", {}).get("hello_started"),
            "run_dir": new_res.get("run_dir"),
        },
        "stage_difference_summary": {
            "old_last_lines": old_res.get("trace_analysis", {}).get("last_stderr_lines"),
            "new_last_lines": new_res.get("trace_analysis", {}).get("last_stderr_lines"),
        }
    }

    comparison_file = LOGS_DIR / "contrast_report.json"
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(contrast, f, indent=2)

    print("\n==========================================================")
    print("CONTRAST EXPERIMENT COMPLETED")
    print(f"Report saved to {comparison_file}")
    print("==========================================================")


if __name__ == "__main__":
    main()
