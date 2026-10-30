import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-once-panorama-derived/build/elfuse'
assert rt.exists(), f"elfuse binary not found at {rt}"
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()
print(f"elfuse SHA256: {rt_sha}")

logs_base = lab / 'logs/once-panorama/windows'
if logs_base.exists():
    shutil.rmtree(logs_base)
logs_base.mkdir(parents=True, exist_ok=True)

src_pfx = lab / 'fixtures/runtime/futex-args-vulkan/pfx'
assert src_pfx.exists(), f"Source prefix not found: {src_pfx}"

pfx_dir = logs_base / 'pfx'
shutil.copytree(src_pfx, pfx_dir, symlinks=True)
print(f"Copied independent clean prefix to {pfx_dir}")

old_result = json.loads((lab / 'logs/vulkan-null-driver/result.json').read_text())
argv = old_result['result']['argv'][:]
argv[0] = str(rt)
argv = [('WINEPREFIX=' + str(pfx_dir)) if s.startswith('WINEPREFIX=') else s for s in argv]

extra_env = {
    'ELFUSE_DIAG_SESSION_SHARED': '1',
    'ELFUSE_IO_TRANSACTION_OBSERVE': '1',
    'ELFUSE_FIXTURE_IDENTITY': '1',
    'ELFUSE_FUTEX_OWNER_OBSERVE': '1',
    'ELFUSE_FUTEX_TARGET_UADDR': '0x20102d440',
    'ELFUSE_THREAD_LIFETIME_OBSERVE': '1',
    'ELFUSE_ONCE_PANORAMA_ALL': '1',
    'ELFUSE_ONCE_PANORAMA_OBSERVE': '1',
    'ELFUSE_ONCE_COUNT_OBSERVE': '1',
    'ELFUSE_ONCE_TRACE_OBSERVE': '1',
    'ELFUSE_ONCE_COUNT_UADDR': '0x20102d440'
}

print("Starting Windows ARM64 Vulkan probe under once-panorama instrumentation (budget 62s)...")
t0 = time.monotonic()
res = run_isolated(argv, logs_base, timeout=62, extra_env=extra_env)
elapsed = time.monotonic() - t0

stdout_txt = Path(res['stdout']).read_text(errors='replace')
stderr_txt = Path(res['stderr']).read_text(errors='replace')

print(f"Completed in {elapsed:.3f}s, exit: {res['exit']}, timed_out: {res['timed_out']}")

once_entries = [l for l in stderr_txt.splitlines() if 'ONCE_ENTRY_COUNT' in l]
once_armed = [l for l in stderr_txt.splitlines() if 'ONCE_COUNT_ARMED' in l]
target_enters = [l for l in stderr_txt.splitlines() if 'FUTEX_OWNER_ENTER' in l and '0x20102d440' in l]

print(f"Captured once entries count: {len(once_entries)}")
print(f"ONCE_COUNT_ARMED lines: {len(once_armed)}")
print(f"Target 0x20102d440 futex enters: {len(target_enters)}")

for e in once_entries[:10]:
    print("  ", e)
if len(once_entries) > 10:
    print(f"  ... ({len(once_entries) - 10} more)")

# Check hard validity gates: Step 3 + target ENTER
has_step3 = "[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)..." in stdout_txt
run_valid = has_step3 and (len(target_enters) > 0)
validity_status = "VALID" if run_valid else "run_valid=false / FAILED"

print(f"Windows Vulkan Run Validity: {validity_status} (has_step3={has_step3}, target_enters={len(target_enters)})")

receipt = {
    'path_type': 'Windows_ARM64_Vulkan_Wine',
    'runtime_sha256': rt_sha,
    'run_valid': run_valid,
    'validity_status': validity_status,
    'exit_code': res['exit'],
    'timed_out': res['timed_out'],
    'seconds': elapsed,
    'stdout_bytes': len(stdout_txt.encode('utf-8', errors='replace')),
    'stderr_bytes': len(stderr_txt.encode('utf-8', errors='replace')),
    'run_dir': res['run_dir'],
    'stdout': stdout_txt,
    'has_step3': has_step3,
    'target_futex_enters': target_enters,
    'once_armed': once_armed,
    'once_entries': once_entries
}

receipt_path = logs_base / 'receipt.json'
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(f"Saved Windows receipt to {receipt_path}")
