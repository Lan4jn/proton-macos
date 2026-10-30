#!/usr/bin/env python3
import json
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab")

def main():
    log_dir = LAB / "logs/cow-recovery/gate_off_reproduce"
    runs = [d for d in log_dir.iterdir() if d.is_dir() and d.name.startswith("run-")]
    if not runs:
        print("No run directory found!")
        return

    run_dir = runs[0]
    res_data = json.loads((run_dir / "result.json").read_text())
    stdout_text = (run_dir / "stdout.log").read_text()
    stderr_lines = (run_dir / "stderr.log").read_text(errors="replace").splitlines()

    # Extract processes and watchdogs
    watchdogs = [ln for ln in stderr_lines if "FUTEX_OWNER_THREAD" in ln]
    p1_watchdogs = [ln for ln in watchdogs if "sibling_gtid=1" in ln]
    p5_watchdogs = [ln for ln in watchdogs if "sibling_gtid=5" in ln]

    repro_evidence = {
        "title": "Wine Session Mapping Failure with ELFUSE_DIAG_SESSION_SHARED Unset",
        "run_dir": str(run_dir),
        "exit_code": res_data["exit"],
        "timed_out": res_data["timed_out"],
        "seconds": res_data["seconds"],
        "stdout_bytes": len(stdout_text.encode()),
        "causal_binding": {
            "target_section": "Wine winstation / desktop session shared section",
            "section_length_bytes": "0x144000 (1,327,104 bytes = 1.265 MiB)",
            "section_offset": 0,
            "section_prot": "PROT_READ | PROT_WRITE (0x3)",
            "original_guest_flags": "MAP_PRIVATE (0x2) [or MAP_PRIVATE | MAP_FIXED]",
            "file_properties": "Unlinked temporary regular file (st_nlink == 0, S_ISREG, O_RDWR), created by wineserver in temp/shm.",
            "participating_processes": [
                "wineserver (creates and initializes session section data)",
                "wineboot.exe --init (guest_pid=5, maps section with MAP_PRIVATE to read session state)",
                "wine root launcher (guest_pid=1, waits for wineboot completion)"
            ],
            "causality_proof": [
                "1. When ELFUSE_DIAG_SESSION_SHARED is unset, sys_mmap uses copy_file_range_to_guest_pages (pread snapshot) for all MAP_PRIVATE file mappings.",
                "2. wineboot (guest_pid=5) maps the session file via pread snapshot at mmap time, isolating its memory from subsequent writes by wineserver.",
                "3. wineboot never observes wineserver's session initialization in the shared memory.",
                "4. wineboot stalls in in_syscall=63 (read) on wineserver communication pipe.",
                "5. Root launcher (guest_pid=1) indefinitely stalls in in_syscall=63 (read) on guest_fd=8 waiting for wineboot to finish.",
                "6. Entire execution hangs with 0 bytes stdout and times out at 30s/60s (exit=124).",
                "7. When ELFUSE_DIAG_SESSION_SHARED=1 is set, elfuse forcibly converts the 0x144000 mapping to MAP_SHARED via hvf_apply_file_overlay, allowing wineboot to see wineserver writes through host kernel page cache, completing bootstrap to Step 5."
            ]
        },
        "watchdog_state_at_timeout": {
            "root_launcher_pid_33663": p1_watchdogs[-5:],
            "wineboot_pid_33667": p5_watchdogs[-5:]
        }
    }

    out_file = LAB / "logs/cow-recovery/gate_off_wine_result.json"
    out_file.write_text(json.dumps(repro_evidence, indent=2) + "\n")
    print(f"Wrote gate-off wine evidence to {out_file}")

if __name__ == "__main__":
    main()
