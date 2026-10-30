#!/usr/bin/env python3
"""
scripts/runtime/wine_badalloc/run_wine_badalloc.py

Host supervisor runner for Task-42:
Executes controller.py under elfuse-socket-derived with ELFUSE_ABSOCK_BASE=lab/.s.
Performs single controlled run (120-140s outer budget).
Extracts captured [BADALLOC_TRACE] native PC, module offsets, and SEH context.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.backend.process import run_isolated

def sha256_file(p: Path) -> str:
    if not p.is_file():
        return "NOT_FOUND"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def symbolize_offset(module_path: Path, offset: int) -> dict:
    symbolizer = Path("/opt/homebrew/opt/llvm@22/bin/llvm-symbolizer")
    if not symbolizer.is_file():
        symbolizer = Path("/opt/homebrew/opt/llvm@21/bin/llvm-symbolizer")
    if not symbolizer.is_file() or not module_path.is_file():
        return {"status": "UNAVAILABLE", "output": None}

    try:
        res = subprocess.run(
            [str(symbolizer), f"--obj={module_path}", hex(offset)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = res.stdout.strip()
        if res.returncode != 0 or "??" in out:
            return {"status": "UNKNOWN_NO_SYMBOLS", "output": out}
        return {"status": "RESOLVED", "output": out}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}

def main():
    elfuse_bin = LAB_ROOT / "sources" / "elfuse-socket-derived" / "build" / "elfuse"
    sysroot = LAB_ROOT / "fixtures" / "runtime" / "arch-case"
    linux_python = sysroot / "usr" / "bin" / "python3.14"
    controller_script = LAB_ROOT / "scripts" / "runtime" / "wine_badalloc" / "controller.py"
    target_pe = LAB_ROOT / "fixtures" / "runtime" / "wine-badalloc" / "pfx" / "drive_c" / "vk_enum_x64.exe"
    tracer_so = LAB_ROOT / "fixtures" / "runtime" / "badalloc-trace" / "libbadalloc_trace.so"
    lab_s = LAB_ROOT / ".s"
    log_dir = LAB_ROOT / "logs" / "wine-badalloc"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Strictly validate .s directory without blindly modifying existing external nodes
    if os.path.islink(lab_s):
        raise RuntimeError(f"Security error: {lab_s} is a symlink!")
    if not lab_s.is_dir():
        lab_s.mkdir(mode=0o700, exist_ok=True)
    st = os.lstat(lab_s)
    if st.st_uid != os.getuid():
        raise RuntimeError(f"Security error: {lab_s} UID {st.st_uid} != current UID {os.getuid()}!")
    if (st.st_mode & 0o777) != 0o700:
        os.chmod(str(lab_s), 0o700)
        st = os.lstat(lab_s)
        if (st.st_mode & 0o777) != 0o700:
            raise RuntimeError(f"Security error: {lab_s} mode {oct(st.st_mode & 0o777)} is not 0700!")

    hashes = {
        "elfuse_socket_derived": sha256_file(elfuse_bin),
        "linux_python": sha256_file(linux_python),
        "controller_script": sha256_file(controller_script),
        "target_pe": sha256_file(target_pe),
        "libbadalloc_trace_so": sha256_file(tracer_so),
    }

    EXPECTED_ELFUSE = "06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d"
    EXPECTED_PE = "f77f9b8fa427120cc1488625f46f4cc05b0f1d2d2b22032f137cb81462cec412"
    EXPECTED_TRACER = "6f034d0aaf3ff6796817d0eb947ace3e1aaa9d4fedeab139e6e6dc5efa0348d5"

    assert hashes["elfuse_socket_derived"] == EXPECTED_ELFUSE, f"ELFUSE hash mismatch: {hashes['elfuse_socket_derived']}"
    assert hashes["target_pe"] == EXPECTED_PE, f"Target PE hash mismatch: {hashes['target_pe']}"
    assert hashes["libbadalloc_trace_so"] == EXPECTED_TRACER, f"Tracer hash mismatch: {hashes['libbadalloc_trace_so']}"

    print("=================================================================")
    print("Task-42: Controlled Wine Vulkan bad_alloc Native Callstack Runner")
    print(f"  elfuse SHA-256:     {hashes['elfuse_socket_derived']}")
    print(f"  target PE SHA-256:  {hashes['target_pe']}")
    print(f"  tracer SHA-256:     {hashes['libbadalloc_trace_so']}")
    print(f"  relay dir:          {lab_s} (mode 0700)")
    print("=================================================================")

    env = {
        "ELFUSE_ABSOCK_BASE": str(lab_s),
    }

    argv = [
        str(elfuse_bin),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(sysroot),
        "--timeout", "125",
        "--env", f"LAB_ROOT={LAB_ROOT}",
        str(linux_python),
        str(controller_script),
    ]

    print("[RUNNER] Launching controlled single-run via supervisor...")
    # Pass RUN_DIR to guest controller via argv/run_isolated
    res = run_isolated(argv, log_dir, timeout=135, extra_env=env)

    print(f"\n[RUNNER] Single run finished:")
    print(f"  Supervisor exit: {res['exit']}")
    print(f"  Target exit:     {res.get('target_exit')}")
    print(f"  Timed out:       {res['timed_out']}")
    print(f"  Elapsed seconds: {res['seconds']:.2f}s")
    print(f"  Run directory:   {res['run_dir']}")

    run_path = Path(res["run_dir"])
    stdout_txt = Path(res["stdout"]).read_text(encoding="utf-8", errors="replace").strip()
    stderr_txt = Path(res["stderr"]).read_text(encoding="utf-8", errors="replace").strip()

    wine_out_file = run_path / "wine_stdout.log"
    wine_err_file = run_path / "wine_stderr.log"
    xvfb_out_file = run_path / "xvfb_stdout.log"
    xvfb_err_file = run_path / "xvfb_stderr.log"

    wine_out_txt = wine_out_file.read_text(encoding="utf-8", errors="replace") if wine_out_file.is_file() else ""
    wine_err_txt = wine_err_file.read_text(encoding="utf-8", errors="replace") if wine_err_file.is_file() else ""

    print(f"  Controller stdout length: {len(stdout_txt)} bytes")
    print(f"  Wine stderr length:       {len(wine_err_txt)} bytes")

    # Extract [BADALLOC_TRACE]
    trace_lines = [l for l in wine_err_txt.splitlines() if "[BADALLOC_TRACE]" in l]
    bad_alloc_lines = [l for l in wine_err_txt.splitlines() if "bad_alloc" in l]
    seh_lines = [l for l in wine_err_txt.splitlines() if "seh" in l.lower() or "exception" in l.lower()]

    print(f"\n[RUNNER] Analysis Findings:")
    print(f"  [BADALLOC_TRACE] lines captured: {len(trace_lines)}")
    for l in trace_lines:
        print("   ", l)

    print(f"  std::bad_alloc occurrences: {len(bad_alloc_lines)}")
    for l in bad_alloc_lines:
        print("   ", l)

    print(f"  SEH exception occurrences: {len(seh_lines)}")
    for l in seh_lines[:5]:
        print("   ", l)

    summary = {
        "hashes": hashes,
        "runner_result": res,
        "controller_stdout": stdout_txt,
        "badalloc_trace_captured": bool(trace_lines),
        "trace_lines": trace_lines,
        "bad_alloc_lines": bad_alloc_lines,
        "seh_lines": seh_lines[:10],
    }

    summary_file = log_dir / "latest_run_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\n[RUNNER] Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
