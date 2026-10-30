#!/usr/bin/env python3
"""
scripts/runtime/fex_init/test_layout_only_control.py

Tests minimal-x64.exe under layout-only elfuse-fex-derived (no prctl modification)
to determine whether layout shift alone is sufficient for x64 PE entry execution.
"""

import json
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
prefix = LAB / "fixtures" / "runtime" / "fex-init" / "pfx-layout-ctrl"

target_name = "minimal-x64.exe"
timeout = 60

argv = [
    str(elfuse),
    "--user", f"{os.getuid()}:{os.getgid()}",
    "--sysroot", str(root),
    "--timeout", str(timeout - 5),
    str(bundle / "files" / "bin-arm64" / "wine"),
    f"C:\\{target_name}"
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
res = run_isolated(argv, log_root, timeout=timeout, extra_env=env)

stderr_text = Path(res["stderr"]).read_text()
lines = stderr_text.splitlines()

    # Robust FEX marker classification
    has_loaded = any("Loaded" in l and "libarm64ecfex.dll" in l and "builtin" in l for l in lines)
    has_failed = any("could not load" in l and "libarm64ecfex.dll" in l for l in lines)
    fex_module_marker = has_loaded and not has_failed
    has_err_line = any("try_map_free_area" in l for l in lines)
    if has_err_line:
        error_observed = True
    elif fex_module_marker:
        error_observed = False
    else:
        error_observed = "UNKNOWN"

target_entry = (res.get("target_exit") == 43)
timeout_occurred = res["timed_out"]

result_data = {
    "experiment": "layout-only-control",
    "elfuse_binary_sha256": "0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7",
    "target": target_name,
    "run_dir": res["run_dir"],
    "exit": res["exit"],
    "target_exit": res.get("target_exit"),
    "seconds": res["seconds"],
    "error_observed": error_observed,
    "fex_module_marker": fex_module_marker,
    "target_entry": target_entry,
    "timeout": timeout_occurred,
    "stderr_lines_count": len(lines),
}

print(json.dumps(result_data, indent=2))
