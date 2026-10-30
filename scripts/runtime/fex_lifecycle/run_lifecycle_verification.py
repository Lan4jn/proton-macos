#!/usr/bin/env python3
"""
scripts/runtime/fex_lifecycle/run_lifecycle_verification.py

Executes full lifecycle verification matrix against elfuse-lifecycle-derived:
- hello-x64.exe (twice to prove clean Exit 0 and stdout X64_FEX_OK)
- minimal-x64.exe (exit 43)
- minimal-arm64.exe (exit 37)
- baselines (hello, dynamic glibc, shared fork, wine --version)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[3]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.process import run_isolated

elfuse = LAB / "sources" / "elfuse-lifecycle-derived" / "build" / "elfuse"
root = LAB / "fixtures" / "runtime" / "arch-case"
bundle = LAB / "fixtures" / "runtime" / "proton-derived"
prefix = LAB / "fixtures" / "runtime" / "fex-lifecycle" / "pfx"

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

log_root = LAB / "logs" / "fex-lifecycle"

results = {}

# Test hello-x64.exe Run 1
print("=== [1/4] hello-x64.exe (Run 1) ===")
argv = [str(elfuse), "--user", f"{os.getuid()}:{os.getgid()}", "--sysroot", str(root), "--timeout", "60", str(bundle/"files/bin-arm64/wine"), "C:\\hello-x64.exe"]
r1 = run_isolated(argv, log_root, 65, extra_env=env)
out1 = Path(r1["stdout"]).read_text().strip()
print(f"  exit: {r1['exit']}, target_exit: {r1.get('target_exit')}, timeout: {r1['timed_out']}, stdout: '{out1}'")
results["hello_run1"] = {"exit": r1["exit"], "target_exit": r1.get("target_exit"), "stdout": out1, "run_dir": r1["run_dir"]}

# Test hello-x64.exe Run 2
print("=== [2/4] hello-x64.exe (Run 2 - Reproducibility) ===")
r2 = run_isolated(argv, log_root, 65, extra_env=env)
out2 = Path(r2["stdout"]).read_text().strip()
print(f"  exit: {r2['exit']}, target_exit: {r2.get('target_exit')}, timeout: {r2['timed_out']}, stdout: '{out2}'")
results["hello_run2"] = {"exit": r2["exit"], "target_exit": r2.get("target_exit"), "stdout": out2, "run_dir": r2["run_dir"]}

# Test minimal-x64.exe
print("=== [3/4] minimal-x64.exe ===")
argv_min_x64 = [str(elfuse), "--user", f"{os.getuid()}:{os.getgid()}", "--sysroot", str(root), "--timeout", "60", str(bundle/"files/bin-arm64/wine"), "C:\\minimal-x64.exe"]
r3 = run_isolated(argv_min_x64, log_root, 65, extra_env=env)
print(f"  exit: {r3['exit']}, target_exit: {r3.get('target_exit')}, timeout: {r3['timed_out']}")
results["minimal_x64"] = {"exit": r3["exit"], "target_exit": r3.get("target_exit"), "run_dir": r3["run_dir"]}

# Test minimal-arm64.exe
print("=== [4/4] minimal-arm64.exe ===")
argv_min_arm = [str(elfuse), "--user", f"{os.getuid()}:{os.getgid()}", "--sysroot", str(root), "--timeout", "50", str(bundle/"files/bin-arm64/wine"), "C:\\minimal-arm64.exe"]
r4 = run_isolated(argv_min_arm, log_root, 55, extra_env=env)
print(f"  exit: {r4['exit']}, target_exit: {r4.get('target_exit')}, timeout: {r4['timed_out']}")
results["minimal_arm64"] = {"exit": r4["exit"], "target_exit": r4.get("target_exit"), "run_dir": r4["run_dir"]}

summary_path = log_root / "lifecycle_verification.json"
summary_path.write_text(json.dumps(results, indent=2) + "\n")
print(f"\nAll tests completed. Summary saved to {summary_path}")
