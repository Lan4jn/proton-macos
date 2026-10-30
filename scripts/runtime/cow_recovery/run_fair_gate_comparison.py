#!/usr/bin/env python3
import json
import os
import sys
import shutil
import subprocess
import time
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(LAB))

from scripts.backend.steam_plan import (
    generate_compatibility_tool_vdfs,
    create_compat_tool_plan,
    apply_installation_plan,
    sha256_file
)
from scripts.backend.steam_handoff import prepare_runtime_tool

REAL_PATCHED_SO = LAB / "sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so"
REAL_SHIPPED_SO = LAB / "fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/win32u.so"
REAL_SHIPPED_VK = LAB / "fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/winevulkan.so"
ELFUSE_BIN = LAB / "sources/elfuse-once-panorama2-derived/build/elfuse"
SYSROOT_DIR = LAB / "fixtures/runtime/arch-case"
LAVAPIPE_LIB = LAB / "fixtures/runtime/lavapipe-derived/usr/lib"
LAVAPIPE_ICD = LAB / "fixtures/runtime/lavapipe-derived/usr/share/vulkan/icd.d/lvp_icd.json"

OUTPUT_DIR = LAB / "logs/cow-recovery/fair_comparison"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def run_single_comparison(label: str, gate_enabled: bool, timeout=115):
    print(f"\n========================================================")
    print(f"Starting Fair Comparison: {label} (GATE_ENABLED={gate_enabled}, timeout={timeout}s)")
    print(f"========================================================")

    subprocess.run(["killall", "-9", "elfuse"], capture_output=True)
    time.sleep(1)

    trial_dir = OUTPUT_DIR / label
    if trial_dir.exists():
        shutil.rmtree(trial_dir)
    trial_dir.mkdir(parents=True, exist_ok=True)

    fixture_steam_root = trial_dir / "steam_root"
    fixture_steam_root.mkdir(parents=True, exist_ok=True)

    source_tool_pkg = trial_dir / "source_proton_pkg"
    source_tool_pkg.mkdir(parents=True, exist_ok=True)

    shutil.copytree(LAB / "sources/wine-win32u-experimental/patched-full/files", source_tool_pkg / "files", symlinks=True)

    if (source_tool_pkg / "files/share").exists():
        if (source_tool_pkg / "files/share").is_symlink():
            (source_tool_pkg / "files/share").unlink()
        else:
            shutil.rmtree(source_tool_pkg / "files/share")
    shutil.copytree(LAB / "fixtures/runtime/proton-derived/files/share", source_tool_pkg / "files/share", symlinks=True)

    u_dst = source_tool_pkg / "files/lib/wine/aarch64-unix/win32u.so"
    if u_dst.exists():
        u_dst.chmod(0o755); u_dst.unlink()
    shutil.copyfile(REAL_SHIPPED_SO, u_dst); u_dst.chmod(0o755)

    v_dst = source_tool_pkg / "files/lib/wine/aarch64-unix/winevulkan.so"
    if v_dst.exists():
        v_dst.chmod(0o755); v_dst.unlink()
    shutil.copyfile(REAL_SHIPPED_VK, v_dst); v_dst.chmod(0o755)

    shutil.copyfile(LAB / "fixtures/runtime/proton-derived/proton", source_tool_pkg / "proton")
    shutil.copyfile(LAB / "fixtures/runtime/proton-derived/filelock.py", source_tool_pkg / "filelock.py")
    (source_tool_pkg / "version").write_text("experimental-11.0-20260924-arm64\n")

    tool_name = f"proton_arm64_{label}"
    display_name = f"Proton Experimental ({label})"

    pfx_dir = trial_dir / "pfx"
    shutil.copytree(LAB / "fixtures/runtime/futex-args-vulkan/pfx", pfx_dir, symlinks=True)

    guest_env = {
        "LD_LIBRARY_PATH": f"{LAVAPIPE_LIB}:{SYSROOT_DIR}/usr/lib"
    }

    diag_env = {
        "ELFUSE_IO_TRANSACTION_OBSERVE": "1",
        "ELFUSE_FIXTURE_IDENTITY": "1",
        "ELFUSE_FUTEX_OWNER_OBSERVE": "1",
        "ELFUSE_THREAD_LIFETIME_OBSERVE": "1",
        "ELFUSE_ONCE_PANORAMA_OBSERVE": "1",
        "ELFUSE_ONCE_COUNT_OBSERVE": "1",
        "ELFUSE_ONCE_TRACE_OBSERVE": "1",
        "VK_ICD_FILENAMES": str(LAVAPIPE_ICD),
        "WINEDEBUG": "+timestamp,+winstation,+vulkan,+explorer,+driver,warn+vulkan"
    }
    if gate_enabled:
        diag_env["ELFUSE_DIAG_SESSION_SHARED"] = "1"

    exec_logs_dir = trial_dir / "logs"
    prepare_runtime_tool(
        output_dir=source_tool_pkg,
        target_dir=fixture_steam_root / "compatibilitytools.d",
        execute_runtime=True,
        elfuse_path=ELFUSE_BIN,
        sysroot=SYSROOT_DIR,
        prefix=pfx_dir,
        runtime_bundle="$DIR",
        logs_dir=exec_logs_dir,
        guest_env=guest_env,
        diagnostic_env=diag_env,
        timeout=float(timeout)
    )

    generate_compatibility_tool_vdfs(
        output_dir=source_tool_pkg,
        tool_name=tool_name,
        display_name=display_name,
        wrapper_rel_path="proton-wrapper.sh"
    )

    plan = create_compat_tool_plan(
        fixture_steam_root=fixture_steam_root,
        source_tool_dir=source_tool_pkg,
        tool_name=tool_name,
        display_name=display_name,
        compat_modules=[{
            "target_rel_path": "files/lib/wine/aarch64-unix/win32u.so",
            "source_path": REAL_PATCHED_SO,
            "expected_orig_sha256": "4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5",
            "expected_arch": "aarch64"
        }]
    )

    manifest = apply_installation_plan(plan, fixture_steam_root)
    dest_tool_dir = fixture_steam_root / "compatibilitytools.d" / tool_name
    dest_wrapper = dest_tool_dir / "proton-wrapper.sh"

    shutil.rmtree(source_tool_pkg)

    print(f"Executing wrapper: {dest_wrapper} runinprefix C:\\vk_enum_arm64.exe")
    probe_cmd = [str(dest_wrapper), "runinprefix", "C:\\vk_enum_arm64.exe"]
    t0 = time.time()
    try:
        p = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout + 10)
        retcode = p.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        print("Wrapper call timed out!")
        retcode = 124
        timed_out = True
    duration = time.time() - t0

    runs = sorted(list(exec_logs_dir.glob("run-*")), key=lambda r: r.stat().st_mtime)
    latest_run = runs[-1] if runs else None

    run_stdout = ""
    run_stderr = ""
    if latest_run:
        if (latest_run / "stdout.log").exists():
            run_stdout = (latest_run / "stdout.log").read_text(errors="replace")
        if (latest_run / "stderr.log").exists():
            run_stderr = (latest_run / "stderr.log").read_text(errors="replace")

    (trial_dir / "stdout.log").write_text(run_stdout)
    (trial_dir / "stderr.log").write_text(run_stderr)

    steps = [l for l in run_stdout.splitlines() if "[WIN_ARM64_VK] Step" in l]
    print(f"Result {label}: exit={retcode}, timed_out={timed_out}, duration={duration:.2f}s, steps={len(steps)}")
    for s in steps:
        print(" ", s)

    return {
        "label": label,
        "gate_enabled": gate_enabled,
        "exit_code": retcode,
        "timed_out": timed_out,
        "duration_seconds": round(duration, 2),
        "steps": steps,
        "stdout_bytes": len(run_stdout.encode()),
        "run_dir": str(latest_run) if latest_run else None
    }

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "gate_off"
    gate_on = (mode == "gate_on")
    res = run_single_comparison(mode, gate_on, timeout=115)
    (OUTPUT_DIR / f"{mode}_result.json").write_text(json.dumps(res, indent=2) + "\n")
    print(f"Result saved to {mode}_result.json")
