#!/usr/bin/env python3
"""
scripts/runtime/fex_init/test_derived_x64.py

Runs minimal-x64.exe under elfuse-fex-derived to observe:
1) exact mmap rejection warning from mem.c
2) whether prctl PR_SET_MEM_MODEL or FEXI is invoked by libarm64ecfex
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
prefix = LAB / "fixtures" / "runtime" / "fex-init" / "pfx"

argv = [
    str(elfuse),
    "--user", f"{os.getuid()}:{os.getgid()}",
    "--sysroot", str(root),
    "--timeout", "25",
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
res = run_isolated(argv, log_root, timeout=30, extra_env=env)

print("Exit code:", res["exit"])
print("Target exit:", res.get("target_exit"))
print("Timed out:", res["timed_out"])
print("Run dir:", res["run_dir"])

stderr_lines = Path(res["stderr"]).read_text().splitlines()
print("Total stderr lines:", len(stderr_lines))

print("=== Relevant warning/error lines from elfuse-fex-derived ===")
for l in stderr_lines:
    if any(k in l for k in ["infra reserve", "prctl", "libarm64ecfex", "try_map_free_area"]):
        print("  ", l)
