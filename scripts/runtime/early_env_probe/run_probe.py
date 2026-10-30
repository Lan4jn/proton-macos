#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/runtime/early_env_probe/run_probe.py

Task-50 rapid diagnostic probe:
Isolates --clear-env vs clean_env allowlist in Wine early initialization.
Runs exactly 4 controlled probes (inner timeout 3s, outer 5s, no PE execution):
- Case A1: /bin/sh -c true with task 48 --clear-env profile
- Case A2: /bin/sh -c 'LD_LIBRARY_PATH=... exec wine --version' with task 48 --clear-env profile
- Case B1: /bin/sh -c true with existing clean_env allowlist (HOME/PATH/LANG/TMPDIR, no --clear-env)
- Case B2: /bin/sh -c 'LD_LIBRARY_PATH=... exec wine --version' with existing clean_env allowlist
"""

import os
import sys
import json
import shlex
import time
import subprocess
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab")
sys.path.insert(0, str(LAB))

from scripts.backend.process import run_isolated

LOG_ROOT = LAB / "logs/early-env-probe"
LOG_ROOT.mkdir(parents=True, exist_ok=True)

ELFUSE_BIN = LAB / "sources/elfuse-socket-derived/build/elfuse"
SYSROOT = LAB / "fixtures/runtime/arch-case"
SH_BIN = SYSROOT / "bin/sh"
PROTON_BUNDLE = LAB / "fixtures/runtime/proton-derived"
WINE_BIN = PROTON_BUNDLE / "files/bin-arm64/wine"
WINESERVER_BIN = PROTON_BUNDLE / "files/bin-arm64/wineserver"
WINE_UNIX_LIB = PROTON_BUNDLE / "files/lib/wine/aarch64-unix"
PROTON_LIB = PROTON_BUNDLE / "files/lib"
LAVAPIPE_LIB = LAB / "fixtures/runtime/lavapipe-derived/usr/lib"
ARCH_LIB = SYSROOT / "usr/lib"

FULL_LD_PATH = f"{LAVAPIPE_LIB}:{WINE_UNIX_LIB}:{PROTON_LIB}:{ARCH_LIB}"
PFX_DIR = LAB / "fixtures/runtime/early-env-probe/pfx"
LAB_S = LAB / ".s"

# Wine env common overrides
WINE_COMMON_VARS = [
    f"WINEPREFIX={PFX_DIR}",
    "WINEESYNC=0",
    "WINEFSYNC=0",
    "PROTON_NO_ESYNC=1",
    "PROTON_NO_FSYNC=1",
    "PROTON_NO_NTSYNC=1",
    "PROTON_USE_ARM64=1",
    "WINEDEBUG=+loaddll,+process,+seh",
    f"WINESERVER={WINESERVER_BIN}",
    f"WINELOADER={WINE_BIN}",
]

def run_probe(case_name, argv, extra_env=None):
    print(f"\n==========================================")
    print(f"Running {case_name}")
    print(f"Command: {' '.join(argv)}")
    start = time.time()
    res = run_isolated(
        argv,
        LOG_ROOT,
        timeout=5,
        extra_env=extra_env,
        cwd=LAB,
    )
    elapsed = time.time() - start
    stdout = Path(res["stdout"]).read_text(encoding="utf-8", errors="replace").strip()
    stderr = Path(res["stderr"]).read_text(encoding="utf-8", errors="replace").strip()

    first_stderr = "\n".join(stderr.splitlines()[:10])
    last_stderr = "\n".join(stderr.splitlines()[-10:])

    print(f"Elapsed: {elapsed:.2f}s | Exit: {res['exit']} | Target Exit: {res.get('target_exit')} | Timed Out: {res['timed_out']}")
    if stdout:
        print(f"Stdout:\n{stdout}")
    if stderr:
        print(f"Stderr (excerpt):\n{first_stderr}")
        if len(stderr.splitlines()) > 20:
            print("...")
            print(f"{last_stderr}")

    return {
        "case": case_name,
        "argv": argv,
        "exit_code": res["exit"],
        "target_exit": res.get("target_exit"),
        "timed_out": res["timed_out"],
        "elapsed_sec": elapsed,
        "stdout": stdout,
        "stderr_head": first_stderr,
        "stderr_tail": last_stderr,
        "run_dir": res.get("run_dir"),
    }

def main():
    results = {}

    # Common native env passed to elfuse
    native_env = {
        "ELFUSE_ABSOCK_BASE": str(LAB_S),
    }

    # -------------------------------------------------------------
    # Case A1: shell true with task 48 clear-env profile
    # -------------------------------------------------------------
    argv_a1 = [
        str(ELFUSE_BIN),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(SYSROOT),
        "--timeout", "3",
        "--clear-env",
    ]
    for ev in WINE_COMMON_VARS:
        argv_a1.extend(["--env", ev])
    argv_a1.extend([
        str(SH_BIN),
        "-c",
        "true",
    ])
    results["Case_A1"] = run_probe("Case A1: /bin/sh -c true (--clear-env)", argv_a1, native_env)

    # -------------------------------------------------------------
    # Case A2: Wine --version with task 48 clear-env profile
    # -------------------------------------------------------------
    wine_cmd_a2 = (
        f"export LD_LIBRARY_PATH={shlex.quote(FULL_LD_PATH)}; "
        f"exec {shlex.quote(str(WINE_BIN))} --version"
    )
    argv_a2 = [
        str(ELFUSE_BIN),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(SYSROOT),
        "--timeout", "3",
        "--clear-env",
    ]
    for ev in WINE_COMMON_VARS:
        argv_a2.extend(["--env", ev])
    argv_a2.extend([
        str(SH_BIN),
        "-c",
        wine_cmd_a2,
    ])
    results["Case_A2"] = run_probe("Case A2: Wine --version (--clear-env)", argv_a2, native_env)

    # -------------------------------------------------------------
    # Case B1: shell true with existing clean_env allowlist (no --clear-env)
    # -------------------------------------------------------------
    argv_b1 = [
        str(ELFUSE_BIN),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(SYSROOT),
        "--timeout", "3",
    ]
    for ev in WINE_COMMON_VARS:
        argv_b1.extend(["--env", ev])
    argv_b1.extend([
        str(SH_BIN),
        "-c",
        "true",
    ])
    results["Case_B1"] = run_probe("Case B1: /bin/sh -c true (clean_env allowlist)", argv_b1, native_env)

    # -------------------------------------------------------------
    # Case B2: Wine --version with existing clean_env allowlist (no --clear-env)
    # -------------------------------------------------------------
    wine_cmd_b2 = (
        f"export LD_LIBRARY_PATH={shlex.quote(FULL_LD_PATH)}; "
        f"exec {shlex.quote(str(WINE_BIN))} --version"
    )
    argv_b2 = [
        str(ELFUSE_BIN),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(SYSROOT),
        "--timeout", "3",
    ]
    for ev in WINE_COMMON_VARS:
        argv_b2.extend(["--env", ev])
    argv_b2.extend([
        str(SH_BIN),
        "-c",
        wine_cmd_b2,
    ])
    results["Case_B2"] = run_probe("Case B2: Wine --version (clean_env allowlist)", argv_b2, native_env)

    out_json = LOG_ROOT / "early_env_probe_results.json"
    out_json.write_text(json.dumps(results, indent=2))
    print(f"\nAll 4 cases completed. Summary saved to {out_json}")

if __name__ == "__main__":
    main()
