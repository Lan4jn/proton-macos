#!/usr/bin/env python3
"""
scripts/runtime/fex_init/run_probe_harness.py

Executes freestanding mmap_probe under elfuse and elfuse-fex-derived
using backend supervisor to capture stdout and exact reject logs.
"""

import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[3]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.process import run_isolated

log_root = LAB / "logs" / "fex-init"
probe_bin = LAB / "fixtures" / "runtime" / "fex-init" / "mmap_probe"

for name, elfuse_bin in [
    ("original_elfuse", LAB / "sources" / "elfuse" / "build" / "elfuse"),
    ("derived_elfuse", LAB / "sources" / "elfuse-fex-derived" / "build" / "elfuse"),
]:
    print(f"=== Running probe under {name} ===")
    argv = [str(elfuse_bin), "--timeout", "20", str(probe_bin)]
    res = run_isolated(argv, log_root, timeout=25)
    print("Run dir:", res["run_dir"])
    print("Exit code:", res["exit"])
    print("Target exit:", res.get("target_exit"))
    print("Timed out:", res["timed_out"])
    stdout_txt = Path(res["stdout"]).read_text()
    stderr_txt = Path(res["stderr"]).read_text()
    print("STDOUT:")
    print(stdout_txt)
    print("STDERR:")
    print(stderr_txt)
