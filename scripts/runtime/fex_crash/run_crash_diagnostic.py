#!/usr/bin/env python3
"""
scripts/runtime/fex_crash/run_crash_diagnostic.py

Runs hello-x64.exe under elfuse-crash-derived to capture:
1) exact [HOST_CRASH] handler output in stderr (phase, faulting thread, si_addr, backtrace)
2) stdout (verifying X64_FEX_OK)
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

argv = [
    str(elfuse),
    "--user", f"{os.getuid()}:{os.getgid()}",
    "--sysroot", str(root),
    "--timeout", "55",
    str(bundle / "files" / "bin-arm64" / "wine"),
    "C:\\hello-x64.exe"
]

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
print("Launching hello-x64.exe crash observation run under backend supervisor...")
res = run_isolated(argv, log_root, timeout=60, extra_env=env)

print("Exit code:", res["exit"])
print("Target exit:", res.get("target_exit"))
print("Timed out:", res["timed_out"])
print("Seconds:", res["seconds"])
print("Run dir:", res["run_dir"])

stdout_text = Path(res["stdout"]).read_text().strip()
stderr_text = Path(res["stderr"]).read_text()
print("STDOUT:", repr(stdout_text))

lines = stderr_text.splitlines()
print(f"Total stderr lines: {len(lines)}")

print("=== HOST CRASH OUTPUT ===")
for l in lines:
    if "[HOST_CRASH]" in l:
        print("  ", l)

print("=== RECENT STDERR (LAST 25 LINES) ===")
for l in lines[-25:]:
    print("  ", l)
