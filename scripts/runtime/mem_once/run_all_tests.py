import hashlib
import json
import os
import sys
import time
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-futex-owner-derived/build/elfuse'
assert rt.exists(), f"elfuse binary not found at {rt}"
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()
print(f"elfuse runtime: {rt} (SHA: {rt_sha})")

sysroot = lab / 'fixtures/runtime/arch-case'
bin_dir = lab / 'scripts/runtime/mem_once'
log_root = lab / 'logs/mem-once'
log_root.mkdir(parents=True, exist_ok=True)

tests = [
    ('test_once', bin_dir / 'test_once', "1) 单线程 pthread_once 调用测试"),
    ('test_mmap_zero', bin_dir / 'test_mmap_zero', "2) mmap(MAP_PRIVATE|MAP_ANONYMOUS) 全新匿名页零填充检查"),
    ('test_fork_cow', bin_dir / 'test_fork_cow', "3) fork 内存隔离与 CoW 写入泄漏检查"),
    ('test_clone_variants', bin_dir / 'test_clone_variants', "4) clone(0x1200011) 精确标志子进程私有内存隔离检查")
]

results = {}

for name, binary, desc in tests:
    assert binary.exists(), f"Binary {binary} not found"
    bin_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    print(f"\n==================================================")
    print(f"Running: {name} - {desc}")
    print(f"Binary SHA: {bin_sha}")

    argv = [
        str(rt),
        '--sysroot', str(sysroot),
        '--timeout', '5',
        str(binary)
    ]

    t0 = time.monotonic()
    run_res = run_isolated(argv, log_root / name, timeout=8)
    elapsed = time.monotonic() - t0

    stdout_txt = Path(run_res['stdout']).read_text(errors='replace')
    stderr_txt = Path(run_res['stderr']).read_text(errors='replace')

    print(f"Completed in {elapsed:.3f}s, exit: {run_res['exit']}, timed_out: {run_res['timed_out']}")
    print(f"STDOUT:\n{stdout_txt.strip()}")
    if stderr_txt.strip():
        print(f"STDERR:\n{stderr_txt.strip()}")

    results[name] = {
        'description': desc,
        'binary_path': str(binary),
        'binary_sha256': bin_sha,
        'exit_code': run_res['exit'],
        'target_exit': run_res.get('target_exit'),
        'timed_out': run_res['timed_out'],
        'seconds': elapsed,
        'stdout': stdout_txt,
        'stderr': stderr_txt,
        'run_dir': run_res['run_dir']
    }

summary = {
    'runtime_path': str(rt),
    'runtime_sha256': rt_sha,
    'timestamp': time.time(),
    'tests': results
}

summary_path = log_root / 'summary.json'
summary_path.write_text(json.dumps(summary, indent=2) + '\n')
print(f"\nSaved complete test summary to {summary_path}")
