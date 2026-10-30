#!/usr/bin/env python3
"""
Test Wine --version execution using safe_process.
"""
import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.runtime.safe_process import run_safe_isolated

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
    "--version"
]

env = {
    "WINEPREFIX": str(prefix),
    "WINEESYNC": "0",
    "WINEFSYNC": "0",
    "WINEDEBUG": "-all",
    "PROTON_NO_ESYNC": "1",
    "PROTON_NO_FSYNC": "1",
    "PROTON_NO_NTSYNC": "1",
    "WINESERVER": str(bundle / "files" / "bin-arm64" / "wineserver"),
    "WINELOADER": str(bundle / "files" / "bin-arm64" / "wine"),
}

prefix.mkdir(parents=True, exist_ok=True)
res = run_safe_isolated(argv, LAB / "logs" / "runtime-worker", timeout=20, extra_env=env)
print("Exit:", res["exit"])
print("Timed out:", res["timed_out"])
print("Stdout:", Path(res["stdout"]).read_text().strip())
print("Stderr:", Path(res["stderr"]).read_text().strip()[:200])
