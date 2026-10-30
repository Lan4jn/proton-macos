#!/usr/bin/env python3
"""
scripts/runtime/wine_badalloc_control/run_control.py

Host runner for task-46:
- Uses elfuse-socket-derived runtime (06a2fceb...) with ELFUSE_ABSOCK_BASE set to lab/.s.
- Verifies lab/.s directory ownership, mode 0700, and non-symlink status.
- Tracks host /tmp/elfuse-absock-* and lab/.s before and after the run.
- Outer timeout 135s.
"""

import os
import sys
import glob
import stat
import time
import subprocess
import json
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
LOGS_DIR = LAB_ROOT / "logs" / "wine-badalloc-control"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def get_host_absock_dirs():
    return set(glob.glob("/tmp/elfuse-absock-*"))


def get_lab_absock_dirs(s_base: Path):
    if not s_base.exists():
        return set()
    return set(p.name for p in s_base.iterdir())


def verify_s_base(s_base: Path):
    if not s_base.exists():
        raise FileNotFoundError(f"Relay base {s_base} does not exist")
    st = os.lstat(str(s_base))
    if stat.S_ISLNK(st.st_mode):
        raise ValueError(f"Relay base {s_base} must not be a symlink")
    if stat.S_IMODE(st.st_mode) != 0o700:
        raise ValueError(f"Relay base {s_base} must have mode 0700 (got {oct(stat.S_IMODE(st.st_mode))})")
    if st.st_uid != os.getuid():
        raise PermissionError(f"Relay base {s_base} must be owned by current uid {os.getuid()} (got {st.st_uid})")
    print(f"[HOST_RUNNER] Verified {s_base}: mode=0700, uid={st.st_uid}, non-symlink")


def main():
    elfuse_bin = LAB_ROOT / "sources" / "elfuse-socket-derived" / "build" / "elfuse"
    sysroot = LAB_ROOT / "fixtures" / "runtime" / "arch-case"
    python_bin = sysroot / "usr" / "bin" / "python3"
    controller_script = LAB_ROOT / "scripts" / "runtime" / "wine_badalloc_control" / "controller.py"
    s_base = LAB_ROOT / ".s"

    verify_s_base(s_base)

    run_dir = LOGS_DIR / f"run-{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)

    host_absock_before = get_host_absock_dirs()
    lab_absock_before = get_lab_absock_dirs(s_base)

    cmd = [
        str(elfuse_bin),
        "--user", "501:20",
        "--sysroot", str(sysroot),
        "--timeout", "135",
        str(python_bin),
        str(controller_script),
    ]

    env = os.environ.copy()
    env["ELFUSE_ABSOCK_BASE"] = str(s_base)
    env["LAB_ROOT"] = str(LAB_ROOT)
    env["RUN_DIR"] = str(run_dir)

    print(f"[HOST_RUNNER] Invoking elfuse-socket-derived with ELFUSE_ABSOCK_BASE={s_base}")
    print(f"[HOST_RUNNER] Command: {' '.join(cmd)}")
    start = time.time()
    res = subprocess.run(cmd, env=env)
    elapsed = time.time() - start

    host_absock_after = get_host_absock_dirs()
    lab_absock_after = get_lab_absock_dirs(s_base)

    new_host_absock = host_absock_after - host_absock_before
    new_lab_absock = lab_absock_after - lab_absock_before

    summary = {
        "controller_exit_code": res.returncode,
        "runner_elapsed_sec": elapsed,
        "run_dir": str(run_dir),
        "new_host_absock_dirs": list(new_host_absock),
        "lab_absock_residual": list(lab_absock_after),
    }

    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[HOST_RUNNER] Completed in {elapsed:.2f}s with controller exit code {res.returncode}")
    print(f"[HOST_RUNNER] New host absock dirs (should be empty): {new_host_absock}")
    print(f"[HOST_RUNNER] Lab absock residual (should be empty if cleaned): {lab_absock_after}")


if __name__ == "__main__":
    main()
