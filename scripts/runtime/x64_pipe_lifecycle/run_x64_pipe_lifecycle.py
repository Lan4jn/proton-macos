import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab")
sys.path.insert(0, str(LAB))
from scripts.backend.process import run_isolated

def main():
    rt = LAB / "sources/elfuse-pipe-lifecycle-derived/build/elfuse"
    assert rt.exists(), f"Runtime not found: {rt}"
    root = LAB / "fixtures/runtime/arch-case"
    bundle = LAB / "fixtures/runtime/proton-derived"
    probe = LAB / "scripts/runtime/x64_vk/vk_enum_x64.exe"
    srcp = LAB / "fixtures/runtime/futex-args-vulkan/pfx"
    
    out = LAB / "logs/x64-pipe-lifecycle"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    
    pfx = out / "pfx"
    shutil.copytree(srcp, pfx, symlinks=True)
    shutil.copyfile(probe, pfx / "drive_c/vk_enum_x64.exe")

    # Load baseline argv template from run-aizg68sd
    aizg_res = json.loads((LAB / "logs/x64-block/sampled-peer-trace/run-aizg68sd/result.json").read_text())
    argv = aizg_res["argv"][:]
    argv[0] = str(rt)
    argv = [(f"WINEPREFIX={pfx}") if x.startswith("WINEPREFIX=") else x for x in argv]

    env = {
        "ELFUSE_PIPE_LIFECYCLE": "1",
        "ELFUSE_THREAD_LIFETIME_OBSERVE": "1",
        "ELFUSE_DIAG_DISABLE_VDSO_AUXV": "1",
        "ELFUSE_DIAG_SESSION_SHARED": "1",
        "ELFUSE_FIXTURE_IDENTITY": "1",
        "ELFUSE_FUTEX_OWNER_OBSERVE": "1",
        "ELFUSE_FUTEX_TARGET_UADDR": "0x20102d440",
        "ELFUSE_ONCE_PANORAMA_OBSERVE": "1",
        "ELFUSE_ONCE_COUNT_OBSERVE": "1",
        "ELFUSE_ONCE_TRACE_OBSERVE": "1",
        "ELFUSE_ONCE_COUNT_UADDR": "0x20102d440",
        "ELFUSE_ONCE_TRACE_UADDR": "0x20102d440",
        "WINEDEBUG": "+timestamp,+process,+winstation,+vulkan,+explorer,+driver,+seh,+loaddll"
    }

    print(f"Starting single bounded 25s x64 startup run with runtime={rt}...")
    start_time = time.monotonic()
    # 25-second bounded supervisor timeout
    r = run_isolated(argv, out, timeout=25, extra_env=env)
    elapsed = time.monotonic() - start_time
    print(f"Run finished in {elapsed:.3f}s, exit={r['exit']}, timed_out={r['timed_out']}")

    stdout = Path(r["stdout"]).read_text(errors="replace")
    stderr = Path(r["stderr"]).read_text(errors="replace")

    # Parse stderr lines
    stderr_lines = stderr.splitlines()
    pipe_create_lines = [ln for ln in stderr_lines if ln.startswith("PIPE_CREATE")]
    pipe_dup_lines = [ln for ln in stderr_lines if ln.startswith("PIPE_DUP")]
    pipe_close_lines = [ln for ln in stderr_lines if ln.startswith("PIPE_CLOSE")]
    pipe_fork_lines = [ln for ln in stderr_lines if ln.startswith("PIPE_FORK_INHERIT")]
    io_enter_lines = [ln for ln in stderr_lines if ln.startswith("IO_CALL_ENTER")]
    io_return_lines = [ln for ln in stderr_lines if ln.startswith("IO_CALL_RETURN")]
    io_trunc_lines = [ln for ln in stderr_lines if ln.startswith("IO_CALL_TRUNCATED")]
    watchdog_lines = [ln for ln in stderr_lines if "FUTEX_OWNER_THREAD" in ln]
    proc_lines = [ln for ln in stderr_lines if re.search(r"trace:process|NtCreateUserProcess", ln)]
    pe_lines = [ln for ln in stderr_lines if "vk_enum_x64.exe" in ln.lower()]

    step1 = "[WIN_X64_VK] Step 1" in stdout
    step3 = "[WIN_X64_VK] Step 3" in stdout

    # Root read analysis (guest_pid=1, op=read)
    root_enter = [ln for ln in io_enter_lines if "guest_pid=1" in ln and "op=read" in ln]
    root_return = [ln for ln in io_return_lines if "guest_pid=1" in ln and "op=read" in ln]

    # Map call_ids
    return_call_ids = set()
    for ln in io_return_lines:
        m = re.search(r"call_id=(d+)", ln)
        if m: return_call_ids.add(m.group(1))

    # Check watchdog pending calls
    watchdog_root = [ln for ln in watchdog_lines if "pid=" in ln and "sibling_gtid=1" in ln]
    pending_in_watchdog = []
    for ln in watchdog_root:
        m = re.search(r"in_syscall=(d+).*pending_call_id=(d+).*pending_fd=(-?d+)", ln)
        if m:
            sc, cid, pfd = m.groups()
            pending_in_watchdog.append({
                "in_syscall": int(sc),
                "pending_call_id": cid,
                "pending_fd": int(pfd),
                "line": ln
            })

    receipt = {
        "runtime_sha256": hashlib.sha256(rt.read_bytes()).hexdigest(),
        "probe_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
        "run_valid": False,
        "has_step1": step1,
        "has_step3": step3,
        "exit_code": r["exit"],
        "timed_out": r["timed_out"],
        "elapsed_seconds": elapsed,
        "supervisor_exit": r.get("supervisor_exit"),
        "cleanup_errors": r.get("cleanup_errors", []),
        "stdout_bytes": len(stdout.encode()),
        "stderr_bytes": len(stderr.encode()),
        "run_dir": r["run_dir"],
        "counts": {
            "pipe_create": len(pipe_create_lines),
            "pipe_dup": len(pipe_dup_lines),
            "pipe_close": len(pipe_close_lines),
            "pipe_fork_inherit": len(pipe_fork_lines),
            "io_call_enter": len(io_enter_lines),
            "io_call_return": len(io_return_lines),
            "io_call_truncated": len(io_trunc_lines),
            "watchdog_snapshots": len([ln for ln in stderr_lines if "THREAD_SNAPSHOT_BEGIN" in ln]),
            "root_read_enters": len(root_enter),
            "root_read_returns": len(root_return)
        },
        "root_pending_watchdog": pending_in_watchdog,
        "pipe_create_samples": pipe_create_lines[:50],
        "wine_process_trace_lines": proc_lines[:200],
        "x64_probe_mentions": pe_lines[:50]
    }

    receipt_file = out / "receipt.json"
    receipt_file.write_text(json.dumps(receipt, indent=2) + "\n")
    print("Wrote receipt to:", receipt_file)
    print("Counts:", json.dumps(receipt["counts"], indent=2))
    print("Root pending in watchdog samples (first 5 and last 5):")
    for s in pending_in_watchdog[:5]:
        print(" ", s)
    if len(pending_in_watchdog) > 5:
        print("  ...")
        for s in pending_in_watchdog[-5:]:
            print(" ", s)

if __name__ == "__main__":
    main()
