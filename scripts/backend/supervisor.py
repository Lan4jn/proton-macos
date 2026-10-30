#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Controlled session supervisor for Proton macOS Lab backend.
Executes the target process within the supervisor's new session/process group.
Holds the process group leader identity until the parent runner completes cleanup,
preventing PID reuse hazards and ensuring clean descendant termination.

Supported Boundary:
Guarantees cleanup of all child and descendant processes that remain in the
supervisor's process group. Processes that explicitly detach via setsid()
cannot be reached via the group and are outside process group control.
"""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 6 or sys.argv[5] != "--":
        sys.stderr.write("Usage: supervisor.py <status_file> <status_fd> <ctl_fd> <work_dir> -- <cmd...>\n")
        sys.exit(1)

    status_file = Path(sys.argv[1])
    status_fd = int(sys.argv[2])
    ctl_fd = int(sys.argv[3])
    work_dir = Path(sys.argv[4])
    cmd = sys.argv[6:]

    status_data = {
        "target_exit": None,
        "supervisor_pid": os.getpid(),
        "error": None,
    }

    # Install a CAUGHT signal handler for SIGTERM throughout the supervisor lifetime.
    # POSIX guarantees that when exec() is called in child, caught handlers are reset to SIG_DFL.
    # This prevents the child from inheriting SIG_IGN, while ensuring supervisor catches SIGTERM
    # and maintains its PGID identity instead of dying prematurely when runner sends group SIGTERM.
    term_received = False

    def sigterm_handler(signum, frame):
        nonlocal term_received
        term_received = True

    signal.signal(signal.SIGTERM, sigterm_handler)

    try:
        # Launch target command in supervisor's process group.
        # Kernel resets SIGTERM to SIG_DFL in child because parent had a caught handler.
        child = subprocess.Popen(
            cmd,
            cwd=work_dir,
            restore_signals=True,
        )
        rc = child.wait()
        status_data["target_exit"] = rc
    except Exception as e:
        status_data["error"] = str(e)
        status_data["target_exit"] = 127

    # Write status file atomically in the run directory before notifying parent
    try:
        status_file.write_text(json.dumps(status_data) + "\n")
    except OSError as e:
        sys.stderr.write(f"Supervisor failed to write status: {e}\n")

    # Notify parent runner via status_fd that target execution settled
    try:
        os.write(status_fd, b"DONE\n")
        os.close(status_fd)
    except OSError:
        pass

    # Wait on ctl_fd until parent closes it or sends SIGKILL to the process group.
    # When parent disconnects or terminates, os.read returns EOF (empty bytes).
    try:
        while True:
            chunk = os.read(ctl_fd, 1024)
            if not chunk:
                break
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
