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

rt = lab / 'sources/elfuse-thread-lifetime-derived/build/elfuse'
assert rt.exists(), f"elfuse binary not found at {rt}"
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()
print(f"Elfuse binary SHA256: {rt_sha}")

# Set up log destination in logs/thread-lifetime/vulkan
log_vulkan = lab / 'logs/thread-lifetime/vulkan'
if log_vulkan.exists():
    shutil.rmtree(log_vulkan)
log_vulkan.mkdir(parents=True, exist_ok=True)

# Use R33 settled working prefix (read-only reuse as explicitly approved by Lead)
pfx = lab / 'fixtures/runtime/futex-args-vulkan/pfx'
assert pfx.exists(), f"Prefix not found: {pfx}"
print(f"Using working prefix: {pfx}")

# Base argv from logs/vulkan-null-driver/result.json
old_result = json.loads((lab / 'logs/vulkan-null-driver/result.json').read_text())
argv = old_result['result']['argv'][:]
argv[0] = str(rt)
argv = [('WINEPREFIX=' + str(pfx)) if s.startswith('WINEPREFIX=') else s for s in argv]

extra_env = {
    'ELFUSE_DIAG_SESSION_SHARED': '1',
    'ELFUSE_IO_TRANSACTION_OBSERVE': '1',
    'ELFUSE_FIXTURE_IDENTITY': '1',
    'ELFUSE_FUTEX_OWNER_OBSERVE': '1',
    'ELFUSE_FUTEX_TARGET_UADDR': '0x20102d440',
    'ELFUSE_THREAD_LIFETIME_OBSERVE': '1'
}

print("Starting Wine thread lifetime measurement run...")
start_time = time.monotonic()
result = run_isolated(argv, log_vulkan, timeout=62, extra_env=extra_env)
elapsed = time.monotonic() - start_time
print(f"Wine run completed in {elapsed:.2f}s, exit: {result['exit']}, timed_out: {result['timed_out']}")

stdout_text = Path(result['stdout']).read_text(errors='replace')
stderr_text = Path(result['stderr']).read_text(errors='replace')

owner_enters = [l for l in stderr_text.splitlines() if l.startswith('FUTEX_OWNER_ENTER')]
owner_maps = [l for l in stderr_text.splitlines() if l.startswith('FUTEX_OWNER_MAP')]
owner_threads = [l for l in stderr_text.splitlines() if l.startswith('FUTEX_OWNER_THREAD')]
owner_returns = [l for l in stderr_text.splitlines() if l.startswith('FUTEX_OWNER_RETURN')]
futex_args = [l for l in stderr_text.splitlines() if l.startswith('FUTEX_ARGS')]

lt_enters = [l for l in stderr_text.splitlines() if l.startswith('THREAD_LIFETIME_ENTER')]
lt_returns = [l for l in stderr_text.splitlines() if l.startswith('THREAD_LIFETIME_RETURN')]
lt_events = [l for l in stderr_text.splitlines() if l.startswith('THREAD_LIFETIME_EVENT')]
snapshots_begin = [l for l in stderr_text.splitlines() if l.startswith('THREAD_SNAPSHOT_BEGIN')]

# Hard validity gates per Lead instructions:
# (a) stdout contains "[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)..."
# (b) stderr contains at least one FUTEX_OWNER_ENTER for uaddr=0x20102d440
has_step3 = "[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)..." in stdout_text
target_enters = [l for l in owner_enters if "uaddr=0x20102d440" in l]
run_valid = has_step3 and (len(target_enters) > 0)
validity_status = "VALID" if run_valid else "run_valid=false / NOT_REPRODUCED"

print(f"Validity check: {validity_status} (has_step3={has_step3}, target_enters={len(target_enters)})")
print(f"Captured lines:")
print(f"  FUTEX_OWNER_ENTER:      {len(owner_enters)} (target 0x20102d440: {len(target_enters)})")
print(f"  FUTEX_OWNER_MAP:        {len(owner_maps)}")
print(f"  FUTEX_OWNER_THREAD:     {len(owner_threads)}")
print(f"  FUTEX_OWNER_RETURN:     {len(owner_returns)}")
print(f"  FUTEX_ARGS:             {len(futex_args)}")
print(f"  THREAD_LIFETIME_ENTER:  {len(lt_enters)}")
print(f"  THREAD_LIFETIME_RETURN: {len(lt_returns)}")
print(f"  THREAD_LIFETIME_EVENT:  {len(lt_events)}")
print(f"  THREAD_SNAPSHOT_BEGIN:  {len(snapshots_begin)}")

# Filter events relating to tid49 (or gtid!=1)
tid49_lines = [l for l in stderr_text.splitlines() if "gtid=49" in l or "tid=49" in l or "result=49" in l]
print(f"Found {len(tid49_lines)} lines mentioning tid49:")
for l in tid49_lines:
    print("  ", l)

receipt = {
    'runtime_sha256': rt_sha,
    'run_valid': run_valid,
    'validity_status': validity_status,
    'result': result,
    'stdout': stdout_text,
    'futex_owner_enters': owner_enters,
    'target_futex_enters': target_enters,
    'futex_owner_maps': owner_maps,
    'futex_owner_threads': owner_threads,
    'futex_owner_returns': owner_returns,
    'futex_args': futex_args,
    'thread_lifetime_enters': lt_enters,
    'thread_lifetime_returns': lt_returns,
    'thread_lifetime_events': lt_events,
    'thread_snapshots': snapshots_begin,
    'tid49_records': tid49_lines,
    'stderr_bytes': len(stderr_text.encode('utf-8', errors='replace')),
    'stdout_bytes': len(stdout_text.encode('utf-8', errors='replace')),
    'mismatch_count': stderr_text.count("Session object id doesn't match")
}

receipt_path = log_vulkan / 'receipt.json'
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(f"Saved receipt to {receipt_path}")
