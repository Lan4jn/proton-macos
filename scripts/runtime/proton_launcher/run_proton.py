#!/usr/bin/env python3
"""
scripts/runtime/proton_launcher/run_proton.py

Controlled launcher runner for unmodified Valve ARM64 Proton Python launcher.
Executes Proton via true Linux Python 3 under elfuse in an isolated prefix,
capturing stdout, stderr, process tree cleanup, and exit codes for x64 PE targets.
"""

import argparse
import json
import os
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.backend.bundle import build_plan
from scripts.backend.process import run_isolated

LOGS_DIR = LAB_ROOT / "logs" / "proton-launcher"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def run_target(
    target_name: str = "minimal-x64.exe",
    verb: str = "run",
    elfuse_path: str = "sources/elfuse-crash-derived/build/elfuse-candidate",
    timeout_sec: int = 60,
    winedebug: str = "+loaddll,+process"
):
    manifest = LAB_ROOT / "artifacts" / "public-proton" / "bundle.json"
    sysroot = LAB_ROOT / "fixtures" / "runtime" / "arch-case"
    prefix = LAB_ROOT / "fixtures" / "runtime" / "proton-launcher" / "compat" / "pfx"
    linux_python = LAB_ROOT / "fixtures" / "runtime" / "arch-case" / "usr" / "bin" / "python3"
    runtime_bundle = LAB_ROOT / "fixtures" / "runtime" / "proton-derived"

    target_win_path = f"C:\\{target_name}"

    print(f"Building execution plan for verb={verb}, target={target_win_path}...")
    plan = build_plan(
        manifest=str(manifest),
        sysroot=str(sysroot),
        prefix=str(prefix),
        arguments=[verb, target_win_path],
        engine="proton",
        linux_python=str(linux_python),
        runtime_bundle=str(runtime_bundle),
        elfuse_path=str(LAB_ROOT / elfuse_path if not os.path.isabs(elfuse_path) else elfuse_path),
    )

    plan_file = LOGS_DIR / "plan.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    print(f"Saved plan to {plan_file} (Status: {plan.get('status')})")

    if plan.get("status") != "PLAN_READY":
        print(f"[ERROR] Plan not ready: {plan.get('reason')}", file=sys.stderr)
        return {"status": "BLOCKED", "plan": plan}

    argv = plan["argv"]
    env = plan["env"]
    env["WINEDEBUG"] = winedebug
    env["PROTON_USE_ARM64"] = "1"
    env["WINEESYNC"] = "0"
    env["WINEFSYNC"] = "0"
    env["PROTON_NO_ESYNC"] = "1"
    env["PROTON_NO_FSYNC"] = "1"
    env["PROTON_NO_NTSYNC"] = "1"

    print("==========================================================")
    print("Launching Unmodified Proton Launcher under Linux Python...")
    print(f"  Target: {target_name}")
    print(f"  Verb: {verb}")
    print(f"  Elfuse: {elfuse_path}")
    print(f"  Timeout: {timeout_sec}s")
    print("==========================================================")

    res = run_isolated(argv, LOGS_DIR, timeout=timeout_sec, extra_env=env)

    stdout_path = Path(res["stdout"])
    stderr_path = Path(res["stderr"])

    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    stderr_lines = stderr_text.splitlines()

    print(f"Run completed in {res['seconds']:.2f}s.")
    print(f"  Exit code: {res['exit']}")
    print(f"  Target exit code: {res.get('target_exit')}")
    print(f"  Timed out: {res['timed_out']}")
    print(f"  Run directory: {res['run_dir']}")
    print(f"  Stdout length: {len(stdout_text)}")
    print(f"  Stderr lines: {len(stderr_lines)}")

    if stdout_text:
        print(f"  STDOUT: {stdout_text}")

    has_x64_fex_ok = "X64_FEX_OK" in stdout_text
    has_host_crash = any("[HOST_CRASH]" in l for l in stderr_lines)

    result_summary = {
        "target": target_name,
        "verb": verb,
        "elfuse_path": elfuse_path,
        "argv": argv,
        "exit": res["exit"],
        "target_exit": res.get("target_exit"),
        "timed_out": res["timed_out"],
        "seconds": res["seconds"],
        "stdout": stdout_text,
        "has_x64_fex_ok": has_x64_fex_ok,
        "has_host_crash": has_host_crash,
        "run_dir": str(res["run_dir"]),
        "cleanup_errors": res.get("cleanup_errors", []),
    }

    result_file = LOGS_DIR / f"result_{target_name.replace('.exe', '')}_{verb}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result_summary, f, indent=2)

    return result_summary


def main():
    parser = argparse.ArgumentParser(description="Run target PE through unmodified Proton Python launcher")
    parser.add_argument("--target", default="minimal-x64.exe", help="Target PE filename in drive_c")
    parser.add_argument("--verb", default="run", choices=["run", "waitforexitandrun", "runinprefix"], help="Proton verb")
    parser.add_argument("--elfuse", default="sources/elfuse-crash-derived/build/elfuse-candidate", help="Path to elfuse binary")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")
    parser.add_argument("--winedebug", default="+loaddll,+process", help="WINEDEBUG string")
    args = parser.parse_args()

    res = run_target(
        target_name=args.target,
        verb=args.verb,
        elfuse_path=args.elfuse,
        timeout_sec=args.timeout,
        winedebug=args.winedebug
    )

    if res.get("timed_out"):
        sys.exit(124)
    target_rc = res.get("target_exit")
    if target_rc is not None:
        sys.exit(target_rc)
    sys.exit(res.get("exit", 1))


if __name__ == "__main__":
    main()
