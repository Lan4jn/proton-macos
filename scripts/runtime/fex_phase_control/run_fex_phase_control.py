#!/usr/bin/env python3
"""
scripts/runtime/fex_phase_control/run_fex_phase_control.py

Host supervisor runner for Task-48:
Controlled dual-arm bare FEX hello comparison:
- Arm A (Baseline): No LD_PRELOAD (unset LD_PRELOAD)
- Arm B (Instrumented): With v3 phase observer libbadalloc_phase.so via LD_PRELOAD

Runtime: sources/elfuse-socket-derived/build/elfuse (06a2fceb...)
Relay: lab/.s (mode 0700, strict lstat validation)
Target: hello-x64.exe (26cccc8ced8...)
"""

import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.backend.process import run_isolated
from scripts.runtime.fex_phase_control.test_phase_classifier import classify_run

def sha256_file(p: Path) -> str:
    if not p.is_file():
        return "NOT_FOUND"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def check_dll_valid(p: Path) -> bool:
    if not p.exists():
        return False
    try:
        return p.resolve().is_file()
    except Exception:
        return False

def validate_prefix(pfx: Path) -> dict:
    sys32 = pfx / "drive_c" / "windows" / "system32"
    target_pe = pfx / "drive_c" / "hello-x64.exe"
    dlls = ["kernel32.dll", "kernelbase.dll", "ntdll.dll", "libarm64ecfex.dll", "user32.dll", "ucrtbase.dll"]
    res = {
        "pfx": str(pfx),
        "target_pe_exists": target_pe.is_file(),
        "target_pe_sha": sha256_file(target_pe),
        "dlls": {},
        "all_dlls_valid": True,
    }
    for d in dlls:
        dll_path = sys32 / d
        valid = check_dll_valid(dll_path)
        res["dlls"][d] = {"exists": valid, "target": str(dll_path.resolve()) if valid else "INVALID"}
        if not valid:
            res["all_dlls_valid"] = False
    return res

def main():
    elfuse_bin = LAB_ROOT / "sources" / "elfuse-socket-derived" / "build" / "elfuse"
    sysroot = LAB_ROOT / "fixtures" / "runtime" / "arch-case"
    sh_bin = sysroot / "usr" / "bin" / "sh"
    proton_derived = LAB_ROOT / "fixtures" / "runtime" / "proton-derived"
    wine_bin = proton_derived / "files" / "bin-arm64" / "wine"
    wineserver_bin = proton_derived / "files" / "bin-arm64" / "wineserver"
    tracer_so = LAB_ROOT / "fixtures" / "runtime" / "badalloc-phase" / "libbadalloc_phase.so"
    base_pfx = LAB_ROOT / "fixtures" / "runtime" / "fex-phase-control" / "baseline" / "pfx"
    inst_pfx = LAB_ROOT / "fixtures" / "runtime" / "fex-phase-control" / "instrumented" / "pfx"
    lab_s = LAB_ROOT / ".s"
    log_dir = LAB_ROOT / "logs" / "fex-phase-control"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 1. Strict lstat validation of lab/.s
    if os.path.islink(lab_s):
        raise RuntimeError(f"FATAL: {lab_s} is a symlink!")
    if not lab_s.is_dir():
        raise RuntimeError(f"FATAL: {lab_s} does not exist or is not a directory!")
    st = os.lstat(lab_s)
    if st.st_uid != os.getuid():
        raise RuntimeError(f"FATAL: {lab_s} UID ({st.st_uid}) != current UID ({os.getuid()})!")
    mode = st.st_mode & 0o777
    if mode != 0o700:
        raise RuntimeError(f"FATAL: {lab_s} mode ({oct(mode)}) is not 0700! Auto-chmod prohibited.")

    # 2. Hash & Prefix Preflight
    EXPECTED_ELFUSE = "06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d"
    EXPECTED_PE = "26cccc8ced8bb2037b2589f7d7af204ad98a27c4f7919bc7fc0dc21e032be9e7"
    EXPECTED_TRACER = "105aaa5a7b6956cfafa3561f0184f1533f29348fc556245a75c1d34e056fd173"

    actual_elfuse = sha256_file(elfuse_bin)
    actual_tracer = sha256_file(tracer_so)
    assert actual_elfuse == EXPECTED_ELFUSE, f"ELFUSE hash mismatch: {actual_elfuse}"
    assert actual_tracer == EXPECTED_TRACER, f"Tracer hash mismatch: {actual_tracer}"

    val_base = validate_prefix(base_pfx)
    val_inst = validate_prefix(inst_pfx)
    assert val_base["target_pe_sha"] == EXPECTED_PE, f"Base PE hash mismatch: {val_base['target_pe_sha']}"
    assert val_inst["target_pe_sha"] == EXPECTED_PE, f"Inst PE hash mismatch: {val_inst['target_pe_sha']}"
    assert val_base["all_dlls_valid"], f"Base prefix has invalid DLLs: {val_base}"
    assert val_inst["all_dlls_valid"], f"Inst prefix has invalid DLLs: {val_inst}"

    # 3. Construct LD_LIBRARY_PATH (exact task-46 value)
    lavapipe_lib = LAB_ROOT / "fixtures" / "runtime" / "lavapipe-derived" / "usr" / "lib"
    wine_unix_lib = proton_derived / "files" / "lib" / "wine" / "aarch64-unix"
    proton_files_lib = proton_derived / "files" / "lib"
    arch_lib = sysroot / "usr" / "lib"
    full_ld_path = f"{lavapipe_lib}:{wine_unix_lib}:{proton_files_lib}:{arch_lib}"

    # 4. Environment Delta Record
    common_wine_env = {
        "WINEESYNC": "0",
        "WINEFSYNC": "0",
        "PROTON_NO_ESYNC": "1",
        "PROTON_NO_FSYNC": "1",
        "PROTON_NO_NTSYNC": "1",
        "PROTON_USE_ARM64": "1",
        "WINEDEBUG": "+loaddll,+process,+seh",
        "WINESERVER": str(wineserver_bin),
        "WINELOADER": str(wine_bin),
    }

    env_delta = {
        "arm_a_baseline": {
            "WINEPREFIX": str(base_pfx),
            "LD_PRELOAD": None,  # Explicitly unset
            "LD_LIBRARY_PATH": full_ld_path,
            "target": "C:\\hello-x64.exe",
            **common_wine_env,
        },
        "arm_b_instrumented": {
            "WINEPREFIX": str(inst_pfx),
            "LD_PRELOAD": str(tracer_so),
            "LD_LIBRARY_PATH": full_ld_path,
            "target": "C:\\hello-x64.exe",
            **common_wine_env,
        },
        "native_extra_env": {
            "ELFUSE_ABSOCK_BASE": str(lab_s),
        },
        "removed_env": ["DISPLAY", "XAUTHORITY", "WINEDLLOVERRIDES"],
    }
    (log_dir / "env_delta.json").write_text(json.dumps(env_delta, indent=2) + "\n")

    print("================================================================")
    print("Task-48: FEX Bare Hello Dual-Arm Phase Observer Control Run")
    print(f"  elfuse:    {elfuse_bin} ({actual_elfuse[:16]}...)")
    print(f"  tracer:    {tracer_so} ({actual_tracer[:16]}...)")
    print(f"  target PE: {EXPECTED_PE[:16]}...")
    print(f"  relay:     {lab_s} (mode 0700)")
    print("================================================================")

    # -------------------------------------------------------------
    # ARM A: Baseline Run (No LD_PRELOAD)
    # -------------------------------------------------------------
    print("\n[ARM A] Launching Baseline Wine hello-x64 (unset LD_PRELOAD)...")
    sh_script_a = (
        f"export LD_LIBRARY_PATH={shlex.quote(full_ld_path)}; "
        f"unset LD_PRELOAD; "
        f"exec {shlex.quote(str(wine_bin))} 'C:\\hello-x64.exe'"
    )
    argv_a = [
        str(elfuse_bin),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(sysroot),
        "--timeout", "100",
        "--clear-env",
        "--env", f"WINEPREFIX={base_pfx}",
        "--env", "WINEESYNC=0",
        "--env", "WINEFSYNC=0",
        "--env", "PROTON_NO_ESYNC=1",
        "--env", "PROTON_NO_FSYNC=1",
        "--env", "PROTON_NO_NTSYNC=1",
        "--env", "PROTON_USE_ARM64=1",
        "--env", "WINEDEBUG=+loaddll,+process,+seh",
        "--env", f"WINESERVER={wineserver_bin}",
        "--env", f"WINELOADER={wine_bin}",
        str(sh_bin),
        "-c",
        sh_script_a,
    ]

    res_a = run_isolated(argv_a, log_dir, timeout=110, extra_env={"ELFUSE_ABSOCK_BASE": str(lab_s)})
    stdout_a = Path(res_a["stdout"]).read_text(encoding="utf-8", errors="replace").strip()
    stderr_a = Path(res_a["stderr"]).read_text(encoding="utf-8", errors="replace")

    class_a = classify_run(
        exit_code=res_a["exit"],
        target_exit=res_a.get("target_exit"),
        timed_out=res_a["timed_out"],
        stdout_text=stdout_a,
        stderr_text=stderr_a,
        cleanup_errors=res_a.get("cleanup_errors", []),
    )
    print(f"  [ARM A] exit={res_a['exit']}, target={res_a.get('target_exit')}, timed_out={res_a['timed_out']}, seconds={res_a['seconds']:.2f}s")
    print(f"  [ARM A] classification: {class_a['classification']}, is_success={class_a['is_success']}")
    print(f"  [ARM A] stdout: '{stdout_a}'")

    # -------------------------------------------------------------
    # ARM B: Instrumented Run (With LD_PRELOAD=libbadalloc_phase.so)
    # -------------------------------------------------------------
    print("\n[ARM B] Launching Instrumented Wine hello-x64 (with LD_PRELOAD)...")
    sh_script_b = (
        f"export LD_LIBRARY_PATH={shlex.quote(full_ld_path)}; "
        f"export LD_PRELOAD={shlex.quote(str(tracer_so))}; "
        f"exec {shlex.quote(str(wine_bin))} 'C:\\hello-x64.exe'"
    )
    argv_b = [
        str(elfuse_bin),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(sysroot),
        "--timeout", "100",
        "--clear-env",
        "--env", f"WINEPREFIX={inst_pfx}",
        "--env", "WINEESYNC=0",
        "--env", "WINEFSYNC=0",
        "--env", "PROTON_NO_ESYNC=1",
        "--env", "PROTON_NO_FSYNC=1",
        "--env", "PROTON_NO_NTSYNC=1",
        "--env", "PROTON_USE_ARM64=1",
        "--env", "WINEDEBUG=+loaddll,+process,+seh",
        "--env", f"WINESERVER={wineserver_bin}",
        "--env", f"WINELOADER={wine_bin}",
        str(sh_bin),
        "-c",
        sh_script_b,
    ]

    res_b = run_isolated(argv_b, log_dir, timeout=110, extra_env={"ELFUSE_ABSOCK_BASE": str(lab_s)})
    stdout_b = Path(res_b["stdout"]).read_text(encoding="utf-8", errors="replace").strip()
    stderr_b = Path(res_b["stderr"]).read_text(encoding="utf-8", errors="replace")

    class_b = classify_run(
        exit_code=res_b["exit"],
        target_exit=res_b.get("target_exit"),
        timed_out=res_b["timed_out"],
        stdout_text=stdout_b,
        stderr_text=stderr_b,
        cleanup_errors=res_b.get("cleanup_errors", []),
    )
    print(f"  [ARM B] exit={res_b['exit']}, target={res_b.get('target_exit')}, timed_out={res_b['timed_out']}, seconds={res_b['seconds']:.2f}s")
    print(f"  [ARM B] classification: {class_b['classification']}, is_success={class_b['is_success']}")
    print(f"  [ARM B] stdout: '{stdout_b}'")
    print(f"  [ARM B] phase_markers ({class_b['phase_marker_count']}):")
    for m in class_b["phase_markers"][:10]:
        print("    ", m)

    # 5. Save Structured Comparison Summary
    summary = {
        "hashes": {
            "elfuse_socket_derived": actual_elfuse,
            "target_pe": EXPECTED_PE,
            "libbadalloc_phase_so": actual_tracer,
        },
        "arm_a_baseline": {
            "run_dir": res_a["run_dir"],
            "exit": res_a["exit"],
            "target_exit": res_a.get("target_exit"),
            "timed_out": res_a["timed_out"],
            "seconds": res_a["seconds"],
            "stdout": stdout_a,
            "classification": class_a["classification"],
            "is_success": class_a["is_success"],
        },
        "arm_b_instrumented": {
            "run_dir": res_b["run_dir"],
            "exit": res_b["exit"],
            "target_exit": res_b.get("target_exit"),
            "timed_out": res_b["timed_out"],
            "seconds": res_b["seconds"],
            "stdout": stdout_b,
            "classification": class_b["classification"],
            "is_success": class_b["is_success"],
            "phase_marker_count": class_b["phase_marker_count"],
            "phase_markers": class_b["phase_markers"],
        },
        "env_delta_file": str(log_dir / "env_delta.json"),
    }
    summary_path = log_dir / "fex_phase_control_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\n================================================================")
    print(f"Dual-arm run summary saved to: {summary_path}")
    print("================================================================")

    return 0

if __name__ == "__main__":
    sys.exit(main())
