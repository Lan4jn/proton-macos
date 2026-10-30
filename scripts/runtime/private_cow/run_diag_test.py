import hashlib
import json
import os
import sys
import time
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-once-count-derived/build/elfuse'
assert rt.exists(), f"elfuse binary not found at {rt}"
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()
print(f"elfuse SHA256: {rt_sha}")

test_bin = lab / 'scripts/runtime/private_cow/test_diag_gate'
assert test_bin.exists(), f"test binary not found at {test_bin}"
bin_sha = hashlib.sha256(test_bin.read_bytes()).hexdigest()
print(f"test_diag_gate SHA256: {bin_sha}")

sysroot = lab / 'fixtures/runtime/arch-case'
log_root = lab / 'logs/private-cow/diag'
log_root.mkdir(parents=True, exist_ok=True)

runs = [
    ("without_diag_gate", {}),
    ("with_diag_gate", {"ELFUSE_DIAG_SESSION_SHARED": "1"})
]

results = {}

for label, extra_env in runs:
    print(f"\n=======================================================")
    print(f"Running diag gate test: {label}")
    print(f"extra_env: {extra_env}")

    argv = [
        str(rt),
        '--sysroot', str(sysroot),
        '--timeout', '5',
        str(test_bin)
    ]

    t0 = time.monotonic()
    res = run_isolated(argv, log_root / label, timeout=8, extra_env=extra_env)
    elapsed = time.monotonic() - t0

    stdout_txt = Path(res['stdout']).read_text(errors='replace')
    stderr_txt = Path(res['stderr']).read_text(errors='replace')

    print(f"Completed in {elapsed:.3f}s, exit: {res['exit']}, timed_out: {res['timed_out']}")
    print("--- STDOUT ---")
    print(stdout_txt.strip())
    if stderr_txt.strip():
        print("--- STDERR ---")
        print(stderr_txt.strip())

    results[label] = {
        'label': label,
        'extra_env': extra_env,
        'exit_code': res['exit'],
        'timed_out': res['timed_out'],
        'seconds': elapsed,
        'stdout': stdout_txt,
        'stderr': stderr_txt,
        'run_dir': res['run_dir']
    }

summary = {
    'runtime_sha256': rt_sha,
    'binary_sha256': bin_sha,
    'timestamp': time.time(),
    'runs': results
}

summary_path = log_root / 'diag_comparison_summary.json'
summary_path.write_text(json.dumps(summary, indent=2) + '\n')
print(f"\nSaved diag comparison summary to {summary_path}")
