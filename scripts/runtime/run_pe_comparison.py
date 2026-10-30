#!/usr/bin/env python3
"""
scripts/runtime/run_pe_comparison.py

Runs comparative execution between ARM64 PE and x64 PE
to separate Wine bootstrapping behavior from FEX binary translation.
"""

import argparse
import json
import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.runtime.safe_process import run_safe_isolated


def run_target(target_name: str, timeout: int = 30, winedebug: str = "+loaddll,+process"):
    elfuse = LAB / "sources" / "elfuse" / "build" / "elfuse"
    root = LAB / "fixtures" / "runtime" / "arch-case"
    bundle = LAB / "fixtures" / "runtime" / "proton-derived"
    prefix = LAB / "fixtures" / "runtime" / "pe-worker" / "pfx"

    win_path = f"C:\\{target_name}"

    argv = [
        str(elfuse),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(root),
        "--timeout", str(timeout),
        str(bundle / "files" / "bin-arm64" / "wine"),
        win_path
    ]

    env = {
        "WINEPREFIX": str(prefix),
        "WINEESYNC": "0",
        "WINEFSYNC": "0",
        "WINEDEBUG": winedebug,
        "PROTON_NO_ESYNC": "1",
        "PROTON_NO_FSYNC": "1",
        "PROTON_NO_NTSYNC": "1",
        "WINESERVER": str(bundle / "files" / "bin-arm64" / "wineserver"),
        "WINELOADER": str(bundle / "files" / "bin-arm64" / "wine"),
    }

    log_root = LAB / "logs" / "runtime-worker"
    result = run_safe_isolated(argv, log_root, timeout=timeout + 5, extra_env=env)
    return result


def main():
    parser = argparse.ArgumentParser(description="Run ARM64 vs x64 PE comparison")
    parser.add_argument("--timeout", type=int, default=25, help="Execution timeout in seconds")
    parser.add_argument("--winedebug", type=str, default="+loaddll,+process", help="WINEDEBUG string")
    args = parser.parse_args()

    results = {}

    for target in ["minimal-arm64.exe", "minimal-x64.exe"]:
        print(f"==========================================================")
        print(f"Executing target: {target} (timeout={args.timeout}s)...")
        res = run_target(target, timeout=args.timeout, winedebug=args.winedebug)
        results[target] = {
            "run_dir": res["run_dir"],
            "exit": res["exit"],
            "target_exit": res.get("target_exit"),
            "timed_out": res["timed_out"],
            "seconds": res["seconds"],
            "cleanup_errors": res["cleanup_errors"],
            "stdout": res["stdout"],
            "stderr": res["stderr"],
        }
        print(f"  Run dir: {res['run_dir']}")
        print(f"  Exit code: {res['exit']} (target_exit: {res.get('target_exit')})")
        print(f"  Timed out: {res['timed_out']}")
        print(f"  Elapsed: {res['seconds']}s")
        print(f"  Cleanup errors: {res['cleanup_errors']}")

        stderr_lines = Path(res["stderr"]).read_text().splitlines()
        print(f"  Stderr total lines: {len(stderr_lines)}")
        print("  Stderr sample (last 10 lines):")
        for line in stderr_lines[-10:]:
            print(f"    {line}")

    summary_file = LAB / "logs" / "runtime-worker" / "pe-comparison-summary.json"
    summary_file.write_text(json.dumps(results, indent=2) + "\n")
    print("==========================================================")
    print(f"Comparison complete. Summary written to {summary_file}")


if __name__ == "__main__":
    main()
