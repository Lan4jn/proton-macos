#!/usr/bin/env python3
"""
scripts/runtime/win32u_v3_e2e/run_v3_e2e.py
Executes three isolated comparative end-to-end runs of vk_enum_arm64.exe under elfuse:
1. original (4f6013fa...)
2. pristine (be356a89...)
3. patched  (b6e7b1ea...)
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

RT = REPO_ROOT / "sources/elfuse-once478-derived/build/elfuse"
SRC_PFX = REPO_ROOT / "fixtures/runtime/futex-args-vulkan/pfx"
BASE_ARGV_FILE = REPO_ROOT / "logs/vulkan-null-driver/result.json"

LOG_DIR = REPO_ROOT / "logs/win32u-v3-e2e"

EXTRA_ENV = {
    "ELFUSE_DIAG_SESSION_SHARED": "1",
    "ELFUSE_IO_TRANSACTION_OBSERVE": "1",
    "ELFUSE_FIXTURE_IDENTITY": "1",
    "ELFUSE_FUTEX_OWNER_OBSERVE": "1",
    "ELFUSE_FUTEX_TARGET_UADDR": "0x20102d478",
    "ELFUSE_THREAD_LIFETIME_OBSERVE": "1",
    "ELFUSE_ONCE_PANORAMA_OBSERVE": "1",
    "ELFUSE_ONCE_COUNT_OBSERVE": "1",
    "ELFUSE_ONCE_TRACE_OBSERVE": "1",
    "ELFUSE_ONCE_COUNT_UADDR": "0x20102d478",
    "ELFUSE_ONCE_TRACE_UADDR": "0x20102d478",
}

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def run_trial(label, wine_tree_dir, timeout=62):
    print(f"\n========================================================")
    print(f"Starting Trial: {label.upper()}")
    print(f"========================================================")

    trial_log_dir = LOG_DIR / label
    if trial_log_dir.exists():
        shutil.rmtree(trial_log_dir)
    trial_log_dir.mkdir(parents=True, exist_ok=True)

    pfx = trial_log_dir / "pfx"
    shutil.copytree(SRC_PFX, pfx, symlinks=True)

    wine_root = wine_tree_dir / "files"
    wine_bin = wine_root / "bin-arm64/wine"
    server_bin = wine_root / "bin-arm64/wineserver"
    win32u_so = wine_root / "lib/wine/aarch64-unix/win32u.so"
    relay = f"{wine_root}/lib/wine/aarch64-unix:{wine_root}/lib/wine"

    so_sha = sha256_file(win32u_so)
    rt_sha = sha256_file(RT)
    probe_bin = pfx / "drive_c/vk_enum_arm64.exe"
    probe_sha = sha256_file(probe_bin)

    print(f"  Wine Root:  {wine_root}")
    print(f"  win32u.so:  {win32u_so} (SHA256: {so_sha})")
    print(f"  Runtime:    {RT} (SHA256: {rt_sha})")
    print(f"  Probe:      {probe_bin} (SHA256: {probe_sha})")

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
            a = a.replace("/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix", str(wine_root / "lib/wine/aarch64-unix"))
            a = a.replace("/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib", str(wine_root / "lib"))
        argv[i] = a

    start_time = time.monotonic()
    trial_env = dict(EXTRA_ENV)
    trial_env["WINEDLLPATH"] = relay
    res = run_isolated(argv, trial_log_dir, timeout=timeout, extra_env=trial_env)
    duration = time.monotonic() - start_time

    stdout_text = Path(res["stdout"]).read_text(errors="replace")
    stderr_text = Path(res["stderr"]).read_text(errors="replace")

    # Analysis
    steps = [x for x in stdout_text.splitlines() if "[WIN_ARM64_VK] Step " in x]
    vk_ret = [x for x in stdout_text.splitlines() if "vkCreateInstance" in x and ("return" in x.lower() or "vk_success" in x.lower() or "result" in x.lower())]
    step4 = [x for x in stdout_text.splitlines() if "Step 4" in x]
    device_lines = [x for x in stdout_text.splitlines() if "device" in x.lower() or "gpu" in x.lower()]

    so_load_lines = [x for x in stderr_text.splitlines() if "win32u.so" in x and "calling init" in x]
    futex_lines = [x for x in stderr_text.splitlines() if "FUTEX" in x and ("20102d440" in x or "20102d478" in x)]
    once440_lines = [x for x in stderr_text.splitlines() if "0x20102d440" in x]
    once478_lines = [x for x in stderr_text.splitlines() if "0x20102d478" in x]

    receipt = {
        "label": label,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(duration, 2),
        "exit_code": res["exit"],
        "timed_out": res["timed_out"],
        "runtime_sha256": rt_sha,
        "win32u_sha256": so_sha,
        "probe_sha256": probe_sha,
        "stdout_steps": steps,
        "vk_create_instance_output": vk_ret,
        "step4_reached": bool(step4),
        "module_loaded": bool(so_load_lines),
        "futex_wait_count": len(futex_lines),
        "once_440_event_count": len(once440_lines),
        "once_478_event_count": len(once478_lines),
        "stdout_path": str(res["stdout"]),
        "stderr_path": str(res["stderr"])
    }

    receipt_path = trial_log_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2))
    print(f"Trial {label} completed in {duration:.1f}s, exit code: {res['exit']}, timed_out: {res['timed_out']}")
    print(f"  Steps reached: {steps}")
    print(f"  Step 4 reached: {bool(step4)}")
    print(f"  vkCreateInstance output: {vk_ret}")
    print(f"  Futex 0x20102d440 lines: {len(once440_lines)}, 0x20102d478 lines: {len(once478_lines)}")
    print(f"  Receipt saved: {receipt_path}")

    return receipt

def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    deploy_root = REPO_ROOT / "sources/proton-v3-deploy"

    trials = [
        ("original", deploy_root / "original"),
        ("pristine", deploy_root / "pristine"),
        ("patched",  deploy_root / "patched")
    ]

    all_receipts = {}
    for label, wine_dir in trials:
        all_receipts[label] = run_trial(label, wine_dir, timeout=62)

    master_receipt_path = LOG_DIR / "receipt.json"
    master_receipt_path.write_text(json.dumps(all_receipts, indent=2))
    print(f"\nAll 3 trials completed! Master receipt emitted to {master_receipt_path}")

if __name__ == '__main__':
    main()
