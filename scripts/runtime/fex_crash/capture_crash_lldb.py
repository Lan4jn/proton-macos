#!/usr/bin/env python3
"""
scripts/runtime/fex_crash/capture_crash_lldb.py

Runs hello-x64.exe under owned LLDB batch mode to capture
the exact host crash PC, fault thread, and backtrace on SIGSEGV.
"""

import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[3]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.process import run_isolated

elfuse = LAB / "sources" / "elfuse-fex-derived" / "build" / "elfuse"
root = LAB / "fixtures" / "runtime" / "arch-case"
bundle = LAB / "fixtures" / "runtime" / "proton-derived"
prefix = LAB / "fixtures" / "runtime" / "fex-crash" / "pfx"

elfuse_args = [
    str(elfuse),
    "--user", f"{os.getuid()}:{os.getgid()}",
    "--sysroot", str(root),
    "--timeout", "60",
    str(bundle / "files" / "bin-arm64" / "wine"),
    "C:\\hello-x64.exe"
]

# Configure LLDB batch mode with signal handling and crash command hooks
lldb_argv = [
    "lldb",
    "--no-lldbinit",
    "--batch",
    "-o", "process handle -s false -p true -n true SIGUSR2",
    "-o", "process handle -s false -p true -n true SIGBUS",
    "-o", "process handle -s false -p true -n true SIGALRM",
    "-o", "process handle -s false -p true -n true SIGCHLD",
    "-o", "process handle -s true -p false -n true SIGSEGV",
    "-o", "run",
    "-k", "thread list",
    "-k", "thread backtrace all",
    "-k", "register read",
    "-k", "quit 11",
    "--",
] + elfuse_args

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
print("Launching LLDB crash capture under backend supervisor...")
res = run_isolated(lldb_argv, log_root, timeout=75, extra_env=env)

print("Exit code:", res["exit"])
print("Target exit:", res.get("target_exit"))
print("Timed out:", res["timed_out"])
print("Seconds:", res["seconds"])
print("Run dir:", res["run_dir"])
print("Cleanup errors:", res["cleanup_errors"])

stdout_text = Path(res["stdout"]).read_text()
stderr_text = Path(res["stderr"]).read_text()

print(f"Stdout ({len(stdout_text)} bytes):")
print(stdout_text[:1000])

print(f"Stderr ({len(stderr_text)} bytes):")
print(stderr_text[:1000])
