#!/usr/bin/env python3
"""
scripts/runtime/vk_layoutfix/run_layoutfix.py
Deploys layout-aligned win32u.so alongside shipped winevulkan.so (2786ca6f)
and tests vk_enum_arm64.exe to verify whether Step 4 device enumeration succeeds.
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

PROVEN_TEMPLATE = REPO_ROOT / "sources/wine-win32u-experimental/patched-full/files"
DEPLOY_ROOT = REPO_ROOT / "sources/wine-v3-layoutfix-build/deploy"
LOG_DIR = REPO_ROOT / "logs/vk-layoutfix"

PROBE_ORIG = REPO_ROOT / "fixtures/runtime/futex-args-vulkan/pfx/drive_c/vk_enum_arm64.exe"
PROBE_DIAG = REPO_ROOT / "sources/vk-probe-arm64/vk_enum_arm64_diag.exe"

ALIGNED_WIN32U = REPO_ROOT / "sources/wine-v3-layoutfix-build/target_build/dlls/win32u/win32u.so"
SHIPPED_WIN32U = REPO_ROOT / "fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/win32u.so"
SHIPPED_VULKAN = REPO_ROOT / "fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/winevulkan.so"

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

def setup_tree(target_dir, win32u_so):
    print(f"Setting up tree at {target_dir}...")
    files_dir = target_dir / "files"
    if files_dir.exists():
        shutil.rmtree(files_dir)
    
    shutil.copytree(PROVEN_TEMPLATE, files_dir, symlinks=True)

    dest_win32u = files_dir / "lib/wine/aarch64-unix/win32u.so"
    dest_vulkan = files_dir / "lib/wine/aarch64-unix/winevulkan.so"

    # Deploy win32u.so
    if dest_win32u.exists():
        dest_win32u.chmod(0o755)
        dest_win32u.unlink()
    shutil.copyfile(win32u_so, dest_win32u)
    dest_win32u.chmod(0o755)

    # Ensure winevulkan.so is shipped
    if dest_vulkan.exists():
        dest_vulkan.chmod(0o755)
        dest_vulkan.unlink()
    shutil.copyfile(SHIPPED_VULKAN, dest_vulkan)
    dest_vulkan.chmod(0o755)

    sha_u = sha256_file(dest_win32u)
    sha_v = sha256_file(dest_vulkan)
    print(f"  win32u.so deployed:     {dest_win32u} (SHA256: {sha_u})")
    print(f"  winevulkan.so deployed: {dest_vulkan} (SHA256: {sha_v})")
    return sha_u, sha_v

def run_trial(label, wine_tree_dir, probe_exe, timeout=90):
    print(f"\n========================================================")
    print(f"Starting Task-125 Trial: {label.upper()} (timeout={timeout}s)")
    print(f"========================================================")

    trial_log_dir = LOG_DIR / label
    if trial_log_dir.exists():
        shutil.rmtree(trial_log_dir)
    trial_log_dir.mkdir(parents=True, exist_ok=True)

    pfx = trial_log_dir / "pfx"
    shutil.copytree(SRC_PFX, pfx, symlinks=True)

    target_probe = pfx / "drive_c/vk_enum_arm64.exe"
    target_probe.chmod(0o755)
    shutil.copyfile(probe_exe, target_probe)

    wine_root = wine_tree_dir / "files"
    wine_bin = wine_root / "bin-arm64/wine"
    server_bin = wine_root / "bin-arm64/wineserver"
    win32u_so = wine_root / "lib/wine/aarch64-unix/win32u.so"
    winevulkan_so = wine_root / "lib/wine/aarch64-unix/winevulkan.so"
    relay = f"{wine_root}/lib/wine/aarch64-unix:{wine_root}/lib/wine"

    so_sha = sha256_file(win32u_so)
    vk_sha = sha256_file(winevulkan_so)
    rt_sha = sha256_file(RT)
    probe_sha = sha256_file(target_probe)

    print(f"  Wine Root:     {wine_root}")
    print(f"  win32u.so:     {win32u_so} (SHA256: {so_sha})")
    print(f"  winevulkan.so: {winevulkan_so} (SHA256: {vk_sha})")
    print(f"  Runtime:       {RT} (SHA256: {rt_sha})")
    print(f"  Probe:         {target_probe} (SHA256: {probe_sha})")

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
    res = run_isolated(argv, trial_log_dir, timeout=timeout, extra_env=trial_env)
    duration = time.monotonic() - start_time

    stdout_text = Path(res["stdout"]).read_text(errors="replace")
    stderr_text = Path(res["stderr"]).read_text(errors="replace")

    # Step parsing
    steps = [x for x in stdout_text.splitlines() if "[WIN_ARM64_VK] Step " in x]
    vk_ret = [x for x in stdout_text.splitlines() if "vkCreateInstance" in x and ("return" in x.lower() or "vk_success" in x.lower() or "result" in x.lower() or "error" in x.lower() or "created" in x.lower())]
    step4 = [x for x in stdout_text.splitlines() if "Step 4" in x]
    device_name = [x for x in stdout_text.splitlines() if "deviceName:" in x]
    device_count = [x for x in stdout_text.splitlines() if "Physical device count:" in x or "devCount returned=" in x]

    # Module load lines
    so_load_lines = [x for x in stderr_text.splitlines() if str(win32u_so) in x and "calling init" in x]
    vk_load_lines = [x for x in stderr_text.splitlines() if str(winevulkan_so) in x and "calling init" in x]

    # Dynamic extraction of ALL distinct once addresses (NO hardcoding!)
    distinct_once_uaddrs = set()
    once_entries = []
    for line in stderr_text.splitlines():
        if "x0_uaddr=" in line:
            parts = line.split("x0_uaddr=")
            if len(parts) > 1:
                uaddr = parts[1].split()[0]
                distinct_once_uaddrs.add(uaddr)
                once_entries.append(line)

    receipt = {
        "label": label,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(duration, 2),
        "exit_code": res["exit"],
        "timed_out": res["timed_out"],
        "runtime_sha256": rt_sha,
        "win32u_sha256": so_sha,
        "winevulkan_sha256": vk_sha,
        "probe_sha256": probe_sha,
        "stdout_steps": steps,
        "has_step3": any("Step 3" in s for s in steps),
        "step4_reached": bool(step4),
        "vk_create_instance_output": vk_ret,
        "device_count_output": device_count,
        "device_name": device_name,
        "module_load_confirmed": bool(so_load_lines) and bool(vk_load_lines),
        "distinct_once_uaddrs": sorted(list(distinct_once_uaddrs)),
        "stdout_path": str(res["stdout"]),
        "stderr_path": str(res["stderr"])
    }

    receipt_path = trial_log_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2))
    print(f"Trial {label} completed in {duration:.1f}s, exit code: {res['exit']}, timed_out: {res['timed_out']}")
    print(f"  Steps reached: {steps}")
    print(f"  has_step3: {receipt['has_step3']}, Step 4: {receipt['step4_reached']}")
    print(f"  vkCreateInstance output: {vk_ret}")
    print(f"  Device Count Output: {device_count}")
    print(f"  Device Name: {device_name}")
    print(f"  Receipt saved: {receipt_path}")

    return receipt

def main():
    DEPLOY_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Setup trees
    print("=== Deploying Layout-Fix Trees ===")
    setup_tree(DEPLOY_ROOT / "aligned_patched", ALIGNED_WIN32U)
    setup_tree(DEPLOY_ROOT / "shipped_baseline", SHIPPED_WIN32U)

    # 2. Control: Run shipped baseline to confirm deadlock behavior remains unchanged
    print("\n=== RUN 1: Shipped Baseline Control (Expecting Deadlock at 0x20102d440/478) ===")
    rec_base = run_trial("shipped_baseline", DEPLOY_ROOT / "shipped_baseline", PROBE_ORIG, timeout=90)

    # 3. Target: Run layout-aligned patched win32u with original probe!
    print("\n=== RUN 2: Layout-Aligned Patched win32u with Original Probe ===")
    rec_target_orig = run_trial("aligned_patched_orig_probe", DEPLOY_ROOT / "aligned_patched", PROBE_ORIG, timeout=90)

    # 4. Target Diag: Run layout-aligned patched win32u with diagnostic probe to observe Call 1 & Call 2 values!
    print("\n=== RUN 3: Layout-Aligned Patched win32u with Diagnostic Probe ===")
    rec_target_diag = run_trial("aligned_patched_diag_probe", DEPLOY_ROOT / "aligned_patched", PROBE_DIAG, timeout=90)

    # Master receipt
    master = {
        "shipped_baseline": rec_base,
        "aligned_patched_orig_probe": rec_target_orig,
        "aligned_patched_diag_probe": rec_target_diag
    }
    master_path = LOG_DIR / "receipt.json"
    master_path.write_text(json.dumps(master, indent=2))
    print(f"\nMaster receipt saved to {master_path}")

if __name__ == '__main__':
    main()
