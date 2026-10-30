#!/usr/bin/env python3
"""
scripts/runtime/vulkan_queue/run_queue_fill_probe.py

Controlled supervisor runner for Lavapipe Vulkan queue fill and readback probe.
Executes probe_queue_fill.py under elfuse-lifecycle-derived with isolated logging.
"""

import hashlib
import json
import os
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

def main():
    elfuse_bin = LAB_ROOT / "sources" / "elfuse-lifecycle-derived" / "build" / "elfuse"
    sysroot = LAB_ROOT / "fixtures" / "runtime" / "arch-case"
    linux_python = sysroot / "usr" / "bin" / "python3.14"
    probe_script = LAB_ROOT / "scripts" / "runtime" / "vulkan_queue" / "probe_queue_fill.py"
    icd_json = LAB_ROOT / "fixtures" / "runtime" / "lavapipe-derived" / "usr" / "share" / "vulkan" / "icd.d" / "lvp_icd.json"
    log_dir = LAB_ROOT / "logs" / "vulkan-queue"
    log_dir.mkdir(parents=True, exist_ok=True)

    hashes = {
        "elfuse_lifecycle_derived": sha256_file(elfuse_bin),
        "linux_python": sha256_file(linux_python),
        "probe_script": sha256_file(probe_script),
        "lvp_icd_json": sha256_file(icd_json),
    }

    env = {
        "VK_ICD_FILENAMES": str(icd_json),
    }

    argv = [
        str(elfuse_bin),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--sysroot", str(sysroot),
        "--timeout", "25",
        str(linux_python),
        str(probe_script),
    ]

    print("=================================================================")
    print("Task-34: Vulkan Queue Fill & Host Memory Readback Controlled Run")
    print(f"  elfuse SHA-256: {hashes['elfuse_lifecycle_derived']}")
    print(f"  ICD:            {icd_json}")
    print("=================================================================")

    res = run_isolated(argv, log_dir, timeout=30, extra_env=env)

    print("Execution Finished:")
    print(f"  Exit code:   {res['exit']}")
    print(f"  Target exit: {res.get('target_exit')}")
    print(f"  Timed out:   {res['timed_out']}")
    print(f"  Seconds:     {res['seconds']:.3f}")
    print(f"  Run dir:     {res['run_dir']}")

    stdout_path = Path(res["stdout"])
    stderr_path = Path(res["stderr"])
    stdout_txt = stdout_path.read_text().strip()
    stderr_txt = stderr_path.read_text().strip()

    report_parsed = None
    try:
        report_parsed = json.loads(stdout_txt)
    except Exception as e:
        print(f"Failed to parse JSON stdout: {e}")
        print("Raw stdout:")
        print(stdout_txt)

    if stderr_txt:
        print("Stderr output:")
        print(stderr_txt)

    run_summary = {
        "hashes": hashes,
        "runner_result": res,
        "probe_report": report_parsed,
    }

    summary_file = log_dir / "latest_run_summary.json"
    summary_file.write_text(json.dumps(run_summary, indent=2) + "\n")
    print(f"Summary written to: {summary_file}")

    if report_parsed and report_parsed.get("status") == "SUCCESS":
        print("\n>>> VERDICT: LAVAPIPE_QUEUE_FILL_READBACK_SUCCESS <<<")
        return 0
    else:
        print(f"\n>>> VERDICT: FAILED ({report_parsed.get('error') if report_parsed else 'no report'}) <<<")
        return 1

if __name__ == "__main__":
    sys.exit(main())
