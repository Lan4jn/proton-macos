#!/usr/bin/env python3
"""
scripts/runtime/fex_init/test_shifted_x64.py

Runs minimal-x64.exe under elfuse-fex-derived (with shifted 12GiB layout)
to verify whether try_map_free_area EINVAL is eliminated and observe FEX behavior.
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
print("Seconds:", res["seconds"])
print("Run dir:", res["run_dir"])

stderr_text = Path(res["stderr"]).read_text()
lines = stderr_text.splitlines()
print("Total stderr lines:", len(lines))

print("=== Checking for try_map_free_area in stderr ===")
has_try_map = False
for l in lines:
    if "try_map_free_area" in l:
        print("  FOUND:", l)
        has_try_map = True

if not has_try_map:
    print("  CONFIRMED: try_map_free_area mmap() error is COMPLETELY GONE!")

print("=== Checking for libarm64ecfex loading ===")
for l in lines[-25:]:
    print("  ", l)
