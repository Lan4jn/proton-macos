#!/usr/bin/env python3
"""
scripts/runtime/vk_enum_step4/run_step4_diag.py
Runs the diagnostic ARM64 Vulkan probe (vk_enum_arm64_diag.exe) against patched win32u v3
to resolve count=17035872 and verify Step 4 device enumeration.
"""

import os
import sys
import json
import time
import shutil
import hashlib
from pathlib import Path

REPO_ROOT = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(REPO_ROOT))
from scripts.backend.process import run_isolated

RT = REPO_ROOT / "sources/elfuse-once-panorama2-derived/build/elfuse"
SRC_PFX = REPO_ROOT / "fixtures/runtime/futex-args-vulkan/pfx"
BASE_ARGV_FILE = REPO_ROOT / "logs/vulkan-null-driver/result.json"

LOG_DIR = REPO_ROOT / "logs/vk-step4"
DIAG_EXE = REPO_ROOT / "sources/vk-probe-arm64/vk_enum_arm64_diag.exe"
PATCHED_WINE_TREE = REPO_ROOT / "sources/wine-v3-vulkan-build/deploy/patched"

EXTRA_ENV = {
    "ELFUSE_DIAG_SESSION_SHARED": "1",
    "ELFUSE_IO_TRANSACTION_OBSERVE": "1",
    "ELFUSE_FIXTURE_IDENTITY": "1",
    "ELFUSE_FUTEX_OWNER_OBSERVE": "1",
    "ELFUSE_THREAD_LIFETIME_OBSERVE": "1",
    "ELFUSE_ONCE_PANORAMA_OBSERVE": "1",
    "ELFUSE_ONCE_COUNT_OBSERVE": "1",
    "ELFUSE_ONCE_TRACE_OBSERVE": "1",
}

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    trial_log_dir = LOG_DIR / "diag_run"
    if trial_log_dir.exists():
        shutil.rmtree(trial_log_dir)
    trial_log_dir.mkdir(parents=True, exist_ok=True)

    pfx = trial_log_dir / "pfx"
    shutil.copytree(SRC_PFX, pfx, symlinks=True)

    # Deploy diagnostic probe into pfx
    target_probe = pfx / "drive_c/vk_enum_arm64.exe"
    shutil.copyfile(DIAG_EXE, target_probe)

    wine_root = PATCHED_WINE_TREE / "files"
    wine_bin = wine_root / "bin-arm64/wine"
    server_bin = wine_root / "bin-arm64/wineserver"
    win32u_so = wine_root / "lib/wine/aarch64-unix/win32u.so"
    relay = f"{wine_root}/lib/wine/aarch64-unix:{wine_root}/lib/wine"

    so_sha = sha256_file(win32u_so)
    rt_sha = sha256_file(RT)
    probe_sha = sha256_file(target_probe)

    print("========================================================")
    print("Starting Step 4 Diagnostic Probe Execution (timeout=90s)")
    print("========================================================")
    print(f"  Wine Root:  {wine_root}")
    print(f"  win32u.so:  {win32u_so} (SHA256: {so_sha})")
    print(f"  Runtime:    {RT} (SHA256: {rt_sha})")
    print(f"  Probe:      {target_probe} (SHA256: {probe_sha})")

    base_data = json.loads(BASE_ARGV_FILE.read_text())["result"]
    argv = base_data["argv"][:]
    argv[0] = str(RT)

    for i, a in enumerate(argv):
        if a.startswith("WINEPREFIX="):
            a = f"WINEPREFIX={pfx}"
        elif a.startswith("WINELOADER="):
            a = f"WINELOADER={wine_bin}"
        elif a.startswith("WINESERVER="):
            a = f"WINESERVER={server_bin}"
        elif a.startswith("WINEDEBUG="):
            a = a + ",+loaddll,+vulkan"
        if a.startswith("unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;"):
            prefix = "unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;"
            a = a.replace(prefix, f"{prefix} export LD_DEBUG=libs; export WINEDLLPATH='{relay}';", 1)
            a = a.replace("/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wine", str(wine_bin))
            oldlib = "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib"
            a = a.replace(oldlib, str(wine_root / "lib"))
        argv[i] = a

    start_time = time.monotonic()
    trial_env = dict(EXTRA_ENV)
    trial_env["WINEDLLPATH"] = relay
    res = run_isolated(argv, trial_log_dir, timeout=90, extra_env=trial_env)
    duration = time.monotonic() - start_time

    stdout_text = Path(res["stdout"]).read_text(errors="replace")
    stderr_text = Path(res["stderr"]).read_text(errors="replace")

    print(f"Diagnostic probe run completed in {duration:.1f}s, exit code: {res['exit']}, timed_out: {res['timed_out']}")
    print("=== PROBE STDOUT ===")
    print(stdout_text)

    # Save outputs
    receipt = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(duration, 2),
        "exit_code": res["exit"],
        "timed_out": res["timed_out"],
        "runtime_sha256": rt_sha,
        "win32u_sha256": so_sha,
        "probe_diag_sha256": probe_sha,
        "stdout_full": stdout_text,
        "stdout_path": str(res["stdout"]),
        "stderr_path": str(res["stderr"])
    }

    receipt_path = LOG_DIR / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2))
    print(f"Receipt written to {receipt_path}")

if __name__ == '__main__':
    main()
