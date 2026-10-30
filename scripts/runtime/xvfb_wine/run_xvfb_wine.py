#!/usr/bin/env python3
"""
scripts/runtime/xvfb_wine/run_xvfb_wine.py

Host runner that executes controller.py under elfuse-lifecycle-derived.
Tracks host /tmp/elfuse-absock-* before and after the run.
"""

import os
import sys
import glob
import time
import subprocess
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
LOGS_DIR = LAB_ROOT / "logs" / "xvfb-wine"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def get_absock_dirs():
    return set(glob.glob("/tmp/elfuse-absock-*"))


def main():
    elfuse_bin = LAB_ROOT / "sources" / "elfuse-lifecycle-derived" / "build" / "elfuse"
    sysroot = LAB_ROOT / "fixtures" / "runtime" / "arch-case"
    python_bin = sysroot / "usr" / "bin" / "python3"
    controller_script = LAB_ROOT / "scripts" / "runtime" / "xvfb_wine" / "controller.py"

    run_dir = LOGS_DIR / f"run-{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)

    absock_before = get_absock_dirs()

    cmd = [
        str(elfuse_bin),
        "--user", "501:20",
        "--sysroot", str(sysroot),
        "--timeout", "140",
        str(python_bin),
        str(controller_script),
    ]

    env = os.environ.copy()
    env["LAB_ROOT"] = str(LAB_ROOT)
    env["RUN_DIR"] = str(run_dir)

    print(f"[HOST_RUNNER] Invoking: {' '.join(cmd)}")
    start = time.time()
    res = subprocess.run(cmd, env=env)
    elapsed = time.time() - start

    absock_after = get_absock_dirs()
    new_absock = absock_after - absock_before

    summary = {
        "exit_code": res.returncode,
        "elapsed_sec": elapsed,
        "run_dir": str(run_dir),
        "new_absock_dirs_on_host": list(new_absock),
    }

    import json
    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[HOST_RUNNER] Completed in {elapsed:.2f}s with exit code {res.returncode}")
    print(f"[HOST_RUNNER] New host absock dirs: {new_absock}")


if __name__ == "__main__":
    main()
