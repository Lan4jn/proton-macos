#!/usr/bin/env python3
"""
scripts/runtime/fex_crash/test_all_regressions.py

Runs the complete regression test matrix against sources/elfuse-crash-derived/build/elfuse:
1. hello-x64.exe (must print X64_FEX_OK and exit 0)
2. minimal-x64.exe (must exit 43)
3. minimal-arm64.exe (must exit 37)
"""

import json
import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[3]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.process import run_isolated

elfuse = LAB / "sources" / "elfuse-crash-derived" / "build" / "elfuse"
root = LAB / "fixtures" / "runtime" / "arch-case"
bundle = LAB / "fixtures" / "runtime" / "proton-derived"
prefix = LAB / "fixtures" / "runtime" / "fex-crash" / "pfx"

env = {
    "WINEPREFIX": str(prefix),
    "WINEESYNC": "0",
    "WINEFSYNC": "0",
    "WINEDEBUG": "+loaddll,+process",
    "PROTON_NO_ESYNC": "1",
    "PROTON_NO_FSYNC": "1",
    "PROTON_NO_NTSYNC": "1",
    "WINESERVER": str(bundle / "files" / "bin-arm64" / "wineserver"),
    "WINELOADER": str(bundle / "files" / "bin-arm64" / "wine"),
}

log_root = LAB / "logs" / "fex-crash"

targets = [
    ("hello-x64.exe", 0, "X64_FEX_OK"),
    ("minimal-x64.exe", 43, None),
    ("minimal-arm64.exe", 37, None),
]

summary = {}

for name, expected_exit, expected_stdout in targets:
    print(f"=== Testing {name} (expected exit: {expected_exit}) ===")
    argv = [
        str(elfuse),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(root),
        "--timeout", "50",
        str(bundle / "files" / "bin-arm64" / "wine"),
        f"C:\\{name}"
    ]
    res = run_isolated(argv, log_root, timeout=55, extra_env=env)
    stdout_txt = Path(res["stdout"]).read_text().strip()
    stderr_lines = Path(res["stderr"]).read_text().splitlines()

    actual_target_exit = res.get("target_exit")
    exit_matched = (actual_target_exit == expected_exit)
    stdout_matched = (expected_stdout in stdout_txt) if expected_stdout else True

    has_crash_msg = any("[HOST_CRASH]" in l for l in stderr_lines)

    status = "PASS" if (exit_matched and stdout_matched and not res["timed_out"]) else "FAIL"

    summary[name] = {
        "status": status,
        "exit": res["exit"],
        "target_exit": actual_target_exit,
        "timed_out": res["timed_out"],
        "seconds": res["seconds"],
        "stdout": stdout_txt,
        "has_host_crash_log": has_crash_msg,
        "run_dir": res["run_dir"],
    }
    print(f"  Result: {status} | exit={res['exit']} target_exit={actual_target_exit} timed_out={res['timed_out']}")
    if expected_stdout:
        print(f"  Stdout check: {'MATCH' if stdout_matched else 'MISMATCH'} ({stdout_txt})")

print("\n=== SUMMARY ===")
print(json.dumps(summary, indent=2))
with open(LAB / "logs" / "fex-crash" / "regression_summary.json", "w") as f:
    json.dump(summary, f, indent=2)
