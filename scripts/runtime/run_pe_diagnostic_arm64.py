#!/usr/bin/env python3
"""
Single-shot test of minimal-arm64.exe with resolved kernel32/ntdll symlinks.
"""

import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.process import run_isolated

elfuse = LAB / "sources" / "elfuse" / "build" / "elfuse"
root = LAB / "fixtures" / "runtime" / "arch-case"
bundle = LAB / "fixtures" / "runtime" / "proton-derived"
prefix = LAB / "fixtures" / "runtime" / "pe-worker" / "pfx"

argv = [
    str(elfuse),
    "--user", f"{os.getuid()}:{os.getgid()}",
    "--sysroot", str(root),
    "--timeout", "15",
    str(bundle / "files" / "bin-arm64" / "wine"),
    "C:\\minimal-arm64.exe"
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

log_root = LAB / "logs" / "runtime-worker"
res = run_isolated(argv, log_root, timeout=20, extra_env=env)

print("Exit code:", res["exit"])
print("Target exit:", res.get("target_exit"))
print("Timed out:", res["timed_out"])
print("Seconds:", res["seconds"])
print("Run dir:", res["run_dir"])
print("Cleanup errors:", res["cleanup_errors"])

stderr_text = Path(res["stderr"]).read_text()
print("Stderr lines:", len(stderr_text.splitlines()))
for l in stderr_text.splitlines()[-20:]:
    print("  ", l)
