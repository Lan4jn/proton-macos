import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-reentry-release-derived/build/elfuse'
assert rt.exists(), f"elfuse binary not found at {rt}"
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()
print(f"elfuse SHA256: {rt_sha}")

logs_base = lab / 'logs/reentry-release/baseline'
if logs_base.exists():
    shutil.rmtree(logs_base)
logs_base.mkdir(parents=True, exist_ok=True)

src_pfx = lab / 'fixtures/runtime/futex-args-vulkan/pfx'
pfx_dir = logs_base / 'pfx'
shutil.copytree(src_pfx, pfx_dir, symlinks=True)

old_result = json.loads((lab / 'logs/vulkan-null-driver/result.json').read_text())
argv = old_result['result']['argv'][:]
argv[0] = str(rt)
argv = [('WINEPREFIX=' + str(pfx_dir)) if s.startswith('WINEPREFIX=') else s for s in argv]

# Baseline: ELFUSE_DIAG_REENTRY_RELEASE is NOT set!
extra_env = {
    'ELFUSE_DIAG_SESSION_SHARED': '1',
    'ELFUSE_IO_TRANSACTION_OBSERVE': '1',
    'ELFUSE_FIXTURE_IDENTITY': '1',
    'ELFUSE_FUTEX_OWNER_OBSERVE': '1',
    'ELFUSE_FUTEX_TARGET_UADDR': '0x20102d440',
    'ELFUSE_THREAD_LIFETIME_OBSERVE': '1',
    'ELFUSE_ONCE_PANORAMA_OBSERVE': '1',
    'ELFUSE_ONCE_COUNT_OBSERVE': '1',
    'ELFUSE_ONCE_TRACE_OBSERVE': '1',
    'ELFUSE_ONCE_COUNT_UADDR': '0x20102d440',
    'ELFUSE_ONCE_TRACE_UADDR': '0x20102d440'
}

print("Starting Baseline run (reentry release switch OFF, budget 62s)...")
t0 = time.monotonic()
res = run_isolated(argv, logs_base, timeout=62, extra_env=extra_env)
elapsed = time.monotonic() - t0

stdout_txt = Path(res['stdout']).read_text(errors='replace')
stderr_txt = Path(res['stderr']).read_text(errors='replace')

print(f"Baseline completed in {elapsed:.3f}s, exit: {res['exit']}, timed_out: {res['timed_out']}")

target_enters = [l for l in stderr_txt.splitlines() if 'FUTEX_OWNER_ENTER' in l and '0x20102d440' in l]
bypass_lines = [l for l in stderr_txt.splitlines() if 'REENTRY_ONCE_BYPASS' in l]

print(f"Target 0x20102d440 futex enters: {len(target_enters)}")
print(f"Bypass lines (expect 0 in baseline): {len(bypass_lines)}")

has_step3 = "[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)..." in stdout_txt
run_valid = has_step3 and (len(target_enters) > 0)
print(f"Baseline Run Validity: {'VALID' if run_valid else 'FAILED'} (has_step3={has_step3}, target_enters={len(target_enters)})")

receipt = {
    'mode': 'BASELINE_DIAGNOSTIC_OFF',
    'runtime_sha256': rt_sha,
    'run_valid': run_valid,
    'exit_code': res['exit'],
    'timed_out': res['timed_out'],
    'seconds': elapsed,
    'stdout_bytes': len(stdout_txt.encode('utf-8', errors='replace')),
    'stderr_bytes': len(stderr_txt.encode('utf-8', errors='replace')),
    'run_dir': res['run_dir'],
    'stdout': stdout_txt,
    'has_step3': has_step3,
    'target_futex_enters': target_enters,
    'bypass_lines': bypass_lines
}

receipt_path = logs_base / 'receipt.json'
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(f"Saved baseline receipt to {receipt_path}")
