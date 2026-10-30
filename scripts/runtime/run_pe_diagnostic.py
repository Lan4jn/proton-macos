#!/usr/bin/env python3
"""
scripts/runtime/run_pe_diagnostic.py

Runs x64 PE diagnostic using isolated prefix and safe_process runner.
"""

import argparse
import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.runtime.safe_process import run_safe_isolated


def run_diagnostic(winedebug="-all", timeout=30):
    elfuse = LAB / "sources" / "elfuse" / "build" / "elfuse"
    root = LAB / "fixtures" / "runtime" / "arch-case"
    bundle = LAB / "fixtures" / "runtime" / "proton-derived"
    prefix = LAB / "fixtures" / "runtime" / "pe-worker" / "pfx"

    argv = [
        str(elfuse),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(root),
        "--timeout", str(timeout),
        str(bundle / "files" / "bin-arm64" / "wine"),
        "C:\\hello-x64.exe"
    ]

    env = {
        "WINEPREFIX": str(prefix),
        "WINEESYNC": "0",
        "WINEFSYNC": "0",
        "WINEDEBUG": winedebug,
        "PROTON_NO_ESYNC": "1",
        "PROTON_NO_FSYNC": "1",
        "PROTON_NO_NTSYNC": "1",
        "WINESERVER": str(bundle / "files" / "bin-arm64" / "wineserver"),
        "WINELOADER": str(bundle / "files" / "bin-arm64" / "wine"),
    }

    log_root = LAB / "logs" / "runtime-worker"
    result = run_safe_isolated(argv, log_root, timeout=timeout + 5, extra_env=env)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--winedebug", default="-all")
    parser.add_argument("--timeout", type=int, default=25)
    args = parser.parse_args()

    print(f"Starting diagnostic with timeout={args.timeout}s, WINEDEBUG='{args.winedebug}'...")
    res = run_diagnostic(winedebug=args.winedebug, timeout=args.timeout)
    print("Run directory:", res["run_dir"])
    print("Exit:", res["exit"])
    print("Timed out:", res["timed_out"])
    print("Seconds:", res["seconds"])
    print("Cleanup errors:", res["cleanup_errors"])

    stdout_path = Path(res["stdout"])
    stderr_path = Path(res["stderr"])

    if stdout_path.exists():
        out = stdout_path.read_text().strip()
        print(f"Stdout ({len(out)} bytes): {out[:500]}")
    if stderr_path.exists():
        err = stderr_path.read_text().strip()
        print(f"Stderr ({len(err)} bytes):")
        for line in err.splitlines()[-25:]:
            print("  ", line)


if __name__ == "__main__":
    main()
