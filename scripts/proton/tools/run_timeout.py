#!/usr/bin/env python3
"""
scripts/proton/tools/run_timeout.py
Execute a command with an explicit timeout (in seconds) and environment variables,
capturing output without modifying existing files unless requested.
Exits with:
  - The command's exit code if it finished in time.
  - 124 if the command timed out.
  - 127 if the command executable was not found.
"""
import sys
import subprocess
import os

def main():
    if len(sys.argv) < 3:
        print("Usage: run_timeout.py <seconds> <cmd...>", file=sys.stderr)
        sys.exit(2)

    try:
        timeout_sec = float(sys.argv[1])
    except ValueError:
        print(f"Invalid timeout: {sys.argv[1]}", file=sys.stderr)
        sys.exit(2)

    cmd = sys.argv[2:]

    try:
        proc = subprocess.run(
            cmd,
            timeout=timeout_sec,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=os.environ
        )
        sys.exit(proc.returncode)
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] Command timed out after {timeout_sec} seconds: {' '.join(cmd)}", file=sys.stderr)
        sys.exit(124)
    except FileNotFoundError:
        print(f"[ERROR] Command not found: {cmd[0]}", file=sys.stderr)
        sys.exit(127)
    except Exception as e:
        print(f"[ERROR] Execution failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
