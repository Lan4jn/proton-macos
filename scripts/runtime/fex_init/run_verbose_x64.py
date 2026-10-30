#!/usr/bin/env python3
"""
scripts/runtime/fex_init/run_verbose_x64.py

Runs minimal-x64.exe with elfuse --verbose to capture the exact
Linux syscalls executed right after libarm64ecfex.dll is loaded.
"""

import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[3]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.process import run_isolated

elfuse = LAB / "sources" / "elfuse" / "build" / "elfuse"
root = LAB / "fixtures" / "runtime" / "arch-case"
bundle = LAB / "fixtures" / "runtime" / "proton-derived"
prefix = LAB / "fixtures" / "runtime" / "fex-init" / "pfx"

argv = [
    str(elfuse),
    "--verbose",
    "--user", f"{os.getuid()}:{os.getgid()}",
    "--sysroot", str(root),
    "--timeout", "10",
    str(bundle / "files" / "bin-arm64" / "wine"),
    "C:\\minimal-x64.exe"
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

log_root = LAB / "logs" / "fex-init"
res = run_isolated(argv, log_root, timeout=12, extra_env=env)

print("Exit:", res["exit"])
print("Target exit:", res.get("target_exit"))
print("Timed out:", res["timed_out"])
print("Run dir:", res["run_dir"])

stderr_path = Path(res["stderr"])
lines = stderr_path.read_text().splitlines()
print("Total stderr lines:", len(lines))

# Search for the position of libarm64ecfex
fex_idx = -1
for i, line in enumerate(lines):
    if "libarm64ecfex.dll" in line:
        fex_idx = i
        break

if fex_idx != -1:
    print(f"libarm64ecfex loaded at line {fex_idx}:")
    for l in lines[max(0, fex_idx - 5):min(len(lines), fex_idx + 40)]:
        print("  ", l)
else:
    print("libarm64ecfex not reached yet in this short run; last 25 lines:")
    for l in lines[-25:]:
        print("  ", l)
