#!/usr/bin/env python3
"""
scripts/runtime/fex_init/run_x64_test_controlled.py

Structured test runner for x64 PE under elfuse-fex-derived with shifted layout.
Extracts four precise diagnostic fields:
- error_observed (True/False/UNKNOWN)
- fex_module_marker (True/False)
- target_entry (True/False)
- timeout (True/False)
"""

import json
import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[3]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.process import run_isolated
from scripts.runtime.fex_init.diagnostics import (
    classify_run_outcome,
    extract_run_context_metadata,
)


def run_test(target_name: str, timeout: int = 50, elfuse_flavor: str = "derived"):
    if elfuse_flavor == "derived":
        elfuse = LAB / "sources" / "elfuse-fex-derived" / "build" / "elfuse"
    else:
        elfuse = LAB / "sources" / "elfuse" / "build" / "elfuse"

    root = LAB / "fixtures" / "runtime" / "arch-case"
    bundle = LAB / "fixtures" / "runtime" / "proton-derived"
    prefix = LAB / "fixtures" / "runtime" / "fex-init" / "pfx"

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
    stdout_text = Path(res["stdout"]).read_text()

    target_path = prefix / "drive_c" / target_name
    meta = extract_run_context_metadata(
        binary_path=elfuse,
        target_pe_path=target_path,
        prefix_path=prefix,
    )

    structured_result = classify_run_outcome(
        target_name=target_name,
        res=res,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        elfuse_flavor=elfuse_flavor,
        metadata=meta,
    )

    print(json.dumps(structured_result, indent=2))
    return structured_result


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "minimal-arm64.exe"
    flavor = sys.argv[2] if len(sys.argv) > 2 else "derived"
    timeout_sec = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    run_test(target, timeout=timeout_sec, elfuse_flavor=flavor)
