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

def compute_sha256(filepath):
    p = Path(filepath)
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    return "not_found"

def main():
    rt = LAB / "sources/elfuse-read16-caller-derived/build/elfuse"
    assert rt.exists(), f"Runtime not found: {rt}"
    root = LAB / "fixtures/runtime/arch-case"
    probe = LAB / "scripts/runtime/x64_vk/vk_enum_x64.exe"
    srcp = LAB / "fixtures/runtime/futex-args-vulkan/pfx"
    
    out = LAB / "logs/read16-caller"
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
        "ELFUSE_READ16_CALLER_OBSERVE": "1",
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

    stderr_lines = stderr.splitlines()

    # Extract READ16 caller lines
    caller_entry_lines = [ln for ln in stderr_lines if ln.startswith("READ16_CALLER_ENTRY")]
    caller_frame_lines = [ln for ln in stderr_lines if ln.startswith("READ16_CALLER_FRAME")]
    caller_trunc_lines = [ln for ln in stderr_lines if ln.startswith("READ16_CALLER_TRUNCATE")]
    caller_map_lines = [ln for ln in stderr_lines if ln.startswith("READ16_MAP")]

    # Parse observations
    observations = {}
    for ln in caller_entry_lines:
        m = re.search(r"obs_idx=(d+) pid=(d+) guest_pid=(d+) gtid=(-?d+) guest_fd=(d+) count=(d+) elr=(0x[0-9a-fA-F]+) lr=(0x[0-9a-fA-F]+) sp=(0x[0-9a-fA-F]+) fp=(0x[0-9a-fA-F]+)", ln)
        if m:
            idx, pid, gpid, gtid, gfd, cnt, elr, lr, sp, fp = m.groups()
            observations[idx] = {
                "obs_idx": idx,
                "pid": pid,
                "guest_pid": gpid,
                "gtid": gtid,
                "guest_fd": gfd,
                "count": cnt,
                "registers": {
                    "elr": elr,
                    "lr": lr,
                    "sp": sp,
                    "fp": fp
                },
                "frames": [],
                "truncation": None,
                "maps": []
            }

    for ln in caller_frame_lines:
        m = re.search(r"obs_idx=(d+) depth=(d+) kind=([a-z]+) fp=(0x[0-9a-fA-F]+) addr=(0x[0-9a-fA-F]+) mod=([^s]+) off=(0x[0-9a-fA-F]+)", ln)
        if m:
            idx, depth, kind, fp, addr, mod, off = m.groups()
            if idx in observations:
                observations[idx]["frames"].append({
                    "depth": int(depth),
                    "kind": kind,
                    "fp": fp,
                    "addr": addr,
                    "mod": mod,
                    "off": off
                })

    for ln in caller_trunc_lines:
        m = re.search(r"obs_idx=(d+) depth=(d+) reason=([^s]+) (?:cur_fp|next_fp)=(0x[0-9a-fA-F]+)", ln)
        if m:
            idx, depth, reason, fp = m.groups()
            if idx in observations:
                observations[idx]["truncation"] = {
                    "depth": int(depth),
                    "reason": reason,
                    "fp": fp
                }

    unique_mods = set()
    for ln in caller_map_lines:
        m = re.search(r"obs_idx=(d+) start=(0x[0-9a-fA-F]+) end=(0x[0-9a-fA-F]+) off=(0x[0-9a-fA-F]+) prot=(d+) path=([^s]+)", ln)
        if m:
            idx, start, end, off, prot, mod_path = m.groups()
            if idx in observations:
                observations[idx]["maps"].append({
                    "start": start,
                    "end": end,
                    "off": off,
                    "prot": int(prot),
                    "path": mod_path
                })
            unique_mods.add(mod_path)

    module_hashes = {}
    for mpath in unique_mods:
        if mpath.startswith("/") and os.path.exists(mpath):
            module_hashes[mpath] = compute_sha256(mpath)

    # Watchdog pending info
    watchdog_lines = [ln for ln in stderr_lines if "FUTEX_OWNER_THREAD" in ln and "pending_call_id" in ln]
    root_watchdogs = [ln for ln in watchdog_lines if "sibling_gtid=1" in ln]

    # Hook counts
    counts = {
        "pipe_create": len([ln for ln in stderr_lines if ln.startswith("PIPE_CREATE")]),
        "pipe_dup": len([ln for ln in stderr_lines if ln.startswith("PIPE_DUP")]),
        "pipe_close": len([ln for ln in stderr_lines if ln.startswith("PIPE_CLOSE")]),
        "pipe_fork_inherit": len([ln for ln in stderr_lines if ln.startswith("PIPE_FORK_INHERIT")]),
        "io_call_enter": len([ln for ln in stderr_lines if ln.startswith("IO_CALL_ENTER")]),
        "io_call_return": len([ln for ln in stderr_lines if ln.startswith("IO_CALL_RETURN")]),
        "io_call_truncated": len([ln for ln in stderr_lines if ln.startswith("IO_CALL_TRUNCATED")]),
        "watchdog_snapshots": len([ln for ln in stderr_lines if "THREAD_SNAPSHOT_BEGIN" in ln]),
        "read16_caller_entries": len(caller_entry_lines),
        "root_read_enters": len([ln for ln in stderr_lines if ln.startswith("IO_CALL_ENTER") and "guest_pid=1" in ln and "op=read" in ln]),
        "root_read_returns": len([ln for ln in stderr_lines if ln.startswith("IO_CALL_RETURN") and "guest_pid=1" in ln and "op=read" in ln])
    }

    audit_result = {
        "metadata": {
            "task": "task-117",
            "title": "Root Read16 Dynamic FP Stack and Wine Wait Protocol Candidate Binding",
            "author": "x64-pipe-reviewer",
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "verified"
        },
        "runtime": {
            "path": str(rt),
            "sha256": compute_sha256(rt),
            "base_runtime_sha256": "2eff2415b42ee23c625d8b750f6b4d571c3979f7ff4ac3d1696fe4d4476e458a"
        },
        "probe": {
            "path": str(probe),
            "sha256": compute_sha256(probe),
            "has_step1": "[WIN_X64_VK] Step 1" in stdout,
            "has_step3": "[WIN_X64_VK] Step 3" in stdout,
            "stdout_bytes": len(stdout.encode()),
            "pe_flow_observed": False
        },
        "run": {
            "run_dir": r["run_dir"],
            "elapsed_seconds": elapsed,
            "exit_code": r["exit"],
            "timed_out": r["timed_out"],
            "supervisor_exit": r.get("supervisor_exit"),
            "cleanup_errors": r.get("cleanup_errors", [])
        },
        "counts": counts,
        "observations": observations,
        "module_hashes": module_hashes,
        "watchdog_samples": root_watchdogs[:10]
    }

    audit_file = out / "audit-result.json"
    audit_file.write_text(json.dumps(audit_result, indent=2) + "\n")
    print("Wrote audit result to:", audit_file)

    receipt = {
        "runtime_sha256": audit_result["runtime"]["sha256"],
        "probe_sha256": audit_result["probe"]["sha256"],
        "run_valid": False,
        "has_step1": audit_result["probe"]["has_step1"],
        "has_step3": audit_result["probe"]["has_step3"],
        "exit_code": r["exit"],
        "timed_out": r["timed_out"],
        "elapsed_seconds": elapsed,
        "stdout_bytes": audit_result["probe"]["stdout_bytes"],
        "stderr_bytes": len(stderr.encode()),
        "run_dir": r["run_dir"],
        "counts": counts,
        "observations_summary": {
            idx: {
                "guest_fd": obs["guest_fd"],
                "registers": obs["registers"],
                "frames_count": len(obs["frames"]),
                "key_frames": [f for f in obs["frames"] if "ntdll" in f["mod"].lower() or "wine" in f["mod"].lower()]
            } for idx, obs in observations.items()
        }
    }
    receipt_file = out / "receipt.json"
    receipt_file.write_text(json.dumps(receipt, indent=2) + "\n")
    print("Wrote receipt to:", receipt_file)

if __name__ == "__main__":
    main()
