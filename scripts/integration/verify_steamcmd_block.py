#!/usr/bin/env python3
"""
scripts/integration/verify_steamcmd_block.py

Isolated SteamCMD anonymous blocker verifier.
Parses output semantics for ownership and subscription barriers.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def parse_steamcmd_output(text: str) -> dict:
    is_ownersonly = bool(re.search(r'"section_type"\s+"ownersonly"', text, re.IGNORECASE))
    app_name_match = re.search(r'"name"\s+"([^"]+)"', text)
    app_name = app_name_match.group(1) if app_name_match else None

    is_anonymous_blocked = "Not for anonymous users" in text
    has_no_subscription = bool(re.search(r"Failed to install app '\d+' \(No subscription\)", text))

    error_lines = [
        line.strip()
        for line in text.splitlines()
        if "ERROR!" in line or "Not for anonymous users" in line
    ]

    return {
        "is_ownersonly": is_ownersonly,
        "app_name": app_name,
        "is_anonymous_blocked": is_anonymous_blocked,
        "has_no_subscription": has_no_subscription,
        "error_lines": error_lines,
    }


def run_probe(steamcmd_bin: Path, home_dir: Path, tmp_dir: Path, log_file: Path, timeout_sec: int = 120):
    home_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / "Library" / "Application Support").mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["TMPDIR"] = str(tmp_dir)

    cmd = [
        str(steamcmd_bin),
        "+login", "anonymous",
        "+app_info_print", "4427310",
        "+app_license_request", "4427310",
        "+app_update", "4427310", "validate",
        "+quit"
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
        output = proc.stdout
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        output = (e.stdout or "") + f"\n[TIMEOUT] Process timed out after {timeout_sec} seconds."
        exit_code = 124

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(output)

    analysis = parse_steamcmd_output(output)
    return exit_code, analysis, output


def main():
    parser = argparse.ArgumentParser(description="Verify SteamCMD anonymous block for Proton ARM64")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds")
    parser.add_argument("--log-out", type=str, default=None, help="Path to write log")
    args = parser.parse_args()

    lab_root = Path(__file__).resolve().parent.parent.parent
    steamcmd_bin = lab_root / "scripts" / "proton" / "tools" / "steamcmd" / "steamcmd.sh"
    home_dir = lab_root / "fixtures" / "integration" / "steamcmd_home"
    tmp_dir = lab_root / "fixtures" / "integration" / "tmp"
    log_file = Path(args.log_out) if args.log_out else (lab_root / "logs" / "integration" / "steamcmd_anonymous_verify.log")

    if not steamcmd_bin.exists():
        print(f"[ERROR] steamcmd not found at {steamcmd_bin}", file=sys.stderr)
        sys.exit(1)

    print(f"Running isolated probe with timeout={args.timeout}s...")
    exit_code, analysis, _ = run_probe(steamcmd_bin, home_dir, tmp_dir, log_file, timeout_sec=args.timeout)

    print(f"Exit code: {exit_code}")
    print(f"ownersonly metadata: {analysis['is_ownersonly']}")
    print(f"Anonymous blocked: {analysis['is_anonymous_blocked']}")
    print(f"No subscription error: {analysis['has_no_subscription']}")
    for err in analysis["error_lines"]:
        print(f"  Error: {err}")

    if analysis["is_anonymous_blocked"] and analysis["has_no_subscription"]:
        print("[VERDICT] BLOCKED: Confirmed official Steam depot authentication barrier.")
        sys.exit(0)
    elif exit_code == 124:
        print("[VERDICT] TIMEOUT: Network query timed out.")
        sys.exit(10)
    else:
        print("[VERDICT] UNKNOWN: Did not encounter expected barrier.")
        sys.exit(1)


if __name__ == "__main__":
    main()
