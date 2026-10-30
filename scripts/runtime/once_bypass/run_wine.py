#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_wine.py: Execute Wine Windows ARM64 vk_enum_arm64.exe with or without diagnostic once bypass.
Follows lab standards:
- Distinct run directories
- Copy clean COW prefix
- Check validity thresholds (Step 3 + ENTER)
- Record full structured receipt JSON
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab")
ELFUSE = LAB / "sources/elfuse-once-bypass-derived/build/elfuse"
SYSROOT = LAB / "fixtures/runtime/arch-case"
PROTON = LAB / "fixtures/runtime/proton-derived"
LAVAPIPE = LAB / "fixtures/runtime/lavapipe-derived"
LOGS_BASE = LAB / "logs/once-bypass"

def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def execute_measurement(mode_name: str, enable_bypass: bool, timeout_sec: int = 62):
    run_id = f"run-{os.urandom(4).hex()}"
    run_dir = LOGS_BASE / mode_name / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Isolated clean prefix
    pfx_dir = run_dir / "pfx"
    src_pfx = LAB / "fixtures/runtime/stream-identity-vulkan/pfx"
    if src_pfx.exists():
        shutil.copytree(src_pfx, pfx_dir, symlinks=True)
    else:
        pfx_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["WINEPREFIX"] = str(pfx_dir)
    env["WINEESYNC"] = "0"
    env["WINEFSYNC"] = "0"
    env["PROTON_NO_ESYNC"] = "1"
    env["PROTON_NO_FSYNC"] = "1"
    env["PROTON_NO_NTSYNC"] = "1"
    env["PROTON_USE_ARM64"] = "1"
    env["WINESERVER"] = str(PROTON / "files/bin-arm64/wineserver")
    env["WINELOADER"] = str(PROTON / "files/bin-arm64/wine")
    env["WINEDEBUG"] = "+timestamp,+winstation,+vulkan,+explorer,+driver"
    env["VK_ICD_FILENAMES"] = str(LAVAPIPE / "usr/share/vulkan/icd.d/lvp_icd.json")
    
    # Lab Diagnostic gates
    env["ELFUSE_DIAG_SESSION_SHARED"] = "1"
    env["ELFUSE_FUTEX_OWNER_OBSERVE"] = "1"
    env["ELFUSE_FUTEX_TARGET_UADDR"] = "0x20102d440"
    env["ELFUSE_IO_TRANSACTION_OBSERVE"] = "1"

    if enable_bypass:
        env["ELFUSE_DIAG_ONCE_BYPASS"] = "1"
    else:
        env.pop("ELFUSE_DIAG_ONCE_BYPASS", None)

    guest_script = (
        "unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES; "
        f"export LD_LIBRARY_PATH={LAVAPIPE}/usr/lib:{PROTON}/files/lib/wine/aarch64-unix:{PROTON}/files/lib:{SYSROOT}/usr/lib; "
        f"exec {PROTON}/files/bin-arm64/wine 'C:\\vk_enum_arm64.exe'"
    )

    cmd = [
        str(ELFUSE),
        "--user", "501:20",
        "--sysroot", str(SYSROOT),
        "--timeout", str(timeout_sec),
        str(SYSROOT / "usr/bin/sh"),
        "-c", guest_script
    ]

    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    dt = time.time() - t0

    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    stdout_path.write_text(proc.stdout)
    stderr_path.write_text(proc.stderr)

    stdout_bytes = len(proc.stdout.encode("utf-8"))
    stderr_bytes = len(proc.stderr.encode("utf-8"))

    has_step3 = "[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)..." in proc.stdout
    target_futex_enters = [l for l in proc.stderr.splitlines() if "FUTEX_OWNER_ENTER" in l and "0x20102d440" in l]
    has_target_enter = len(target_futex_enters) >= 1
    run_valid = has_step3 and (has_target_enter or enable_bypass)
    validity_status = "VALID" if run_valid else "run_valid=false / NOT_REPRODUCED"

    bypass_lines = [l for l in proc.stderr.splitlines() if "[DIAGNOSTIC] ONCE_DEADLOCK_BYPASSED" in l]

    receipt = {
        "mode": mode_name,
        "is_diagnostic_borrowed": True,
        "enable_bypass": enable_bypass,
        "runtime_sha256": compute_sha256(ELFUSE),
        "run_valid": run_valid,
        "validity_status": validity_status,
        "result": {
            "exit": proc.returncode,
            "timed_out": proc.returncode == 124,
            "seconds": dt,
            "run_dir": str(run_dir)
        },
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "stdout": proc.stdout,
        "has_step3": has_step3,
        "target_futex_enters": target_futex_enters,
        "bypass_events": bypass_lines,
        "diagnostic_disclaimer": "BORROWED/DIAGNOSTIC ONLY. NOT A FIX. DOES NOT PROVE VULKAN EXECUTION SUCCEEDED OR ABI CORRECTNESS."
    }

    receipt_file = LOGS_BASE / mode_name / "receipt.json"
    with open(receipt_file, "w") as f:
        json.dump(receipt, f, indent=2)

    return receipt

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "bypass"
    bypass_flag = mode == "bypass"
    res = execute_measurement(mode, enable_bypass=bypass_flag)
    print(f"MEASUREMENT_{mode.upper()}_DONE: exit={res['result']['exit']} seconds={res['result']['seconds']:.2f} valid={res['run_valid']}")
    print(f"Bypass Events Count: {len(res['bypass_events'])}")
