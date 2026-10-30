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

rt = lab / 'sources/elfuse-once-backtrace-derived/build/elfuse'
assert rt.exists(), f"elfuse binary not found at {rt}"
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()
print(f"elfuse SHA256: {rt_sha}")

logs_base = lab / 'logs/x64-vk'
if logs_base.exists():
    shutil.rmtree(logs_base)
logs_base.mkdir(parents=True, exist_ok=True)

src_pfx = lab / 'fixtures/runtime/futex-args-vulkan/pfx'
assert src_pfx.exists(), f"Source prefix not found: {src_pfx}"

pfx_dir = logs_base / 'pfx'
shutil.copytree(src_pfx, pfx_dir, symlinks=True)
print(f"Copied independent clean prefix to {pfx_dir}")

# Copy compiled x64 probe to drive_c
probe_src = lab / 'scripts/runtime/x64_vk/vk_enum_x64.exe'
assert probe_src.exists(), f"x64 probe binary not found: {probe_src}"
probe_dst = pfx_dir / 'drive_c' / 'vk_enum_x64.exe'
shutil.copyfile(probe_src, probe_dst)
probe_sha = hashlib.sha256(probe_src.read_bytes()).hexdigest()
print(f"Installed vk_enum_x64.exe (SHA256: {probe_sha}) to {probe_dst}")

old_result = json.loads((lab / 'logs/vulkan-null-driver/result.json').read_text())
argv = old_result['result']['argv'][:]
argv[0] = str(rt)
argv = [('WINEPREFIX=' + str(pfx_dir)) if s.startswith('WINEPREFIX=') else s for s in argv]

# Target vk_enum_x64.exe instead of vk_enum_arm64.exe
for i in range(len(argv)):
    if 'vk_enum_arm64.exe' in argv[i]:
        argv[i] = argv[i].replace('vk_enum_arm64.exe', 'vk_enum_x64.exe')

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

print("Starting Windows x64 Vulkan probe under once-backtrace instrumentation (budget 62s)...")
t0 = time.monotonic()
res = run_isolated(argv, logs_base, timeout=62, extra_env=extra_env)
elapsed = time.monotonic() - t0

stdout_txt = Path(res['stdout']).read_text(errors='replace')
stderr_txt = Path(res['stderr']).read_text(errors='replace')

print(f"Completed in {elapsed:.3f}s, exit: {res['exit']}, timed_out: {res['timed_out']}")

once_entries = [l for l in stderr_txt.splitlines() if 'ONCE_ENTRY_COUNT' in l]
once_armed = [l for l in stderr_txt.splitlines() if 'ONCE_COUNT_ARMED' in l]
target_enters = [l for l in stderr_txt.splitlines() if 'FUTEX_OWNER_ENTER' in l and '0x20102d440' in l]
target_calls = [l for l in once_entries if '0x20102d440' in l]

bt_frames = [l for l in stderr_txt.splitlines() if 'ONCE_BACKTRACE_FRAME' in l]
bt_summaries = [l for l in stderr_txt.splitlines() if 'ONCE_BACKTRACE_SUMMARY' in l]

print(f"Captured once entries: {len(once_entries)}")
print(f"Target 0x20102d440 calls: {len(target_calls)}")
print(f"Target 0x20102d440 futex enters: {len(target_enters)}")
print(f"Captured backtrace frames: {len(bt_frames)}")

print("STDOUT tail:")
for l in stdout_txt.splitlines()[-15:]:
    print("  [stdout]", l)

# Check hard validity gates: Step 3 + target ENTER
has_step3 = "[WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)..." in stdout_txt
has_target_enter = (len(target_enters) > 0)
has_target_once = (len(target_calls) > 0)

run_valid = has_step3 and (has_target_enter or has_target_once)
validity_status = "VALID" if run_valid else "run_valid=false / FAILED"

print(f"Windows x64 Vulkan Run Validity: {validity_status} (has_step3={has_step3}, target_enters={len(target_enters)}, target_once={len(target_calls)})")

receipt = {
    'path_type': 'Windows_x64_Vulkan_Wine_FEX',
    'probe_binary': 'vk_enum_x64.exe',
    'probe_sha256': probe_sha,
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
    'target_once_calls': target_calls,
    'once_armed': once_armed,
    'once_entries': once_entries,
    'backtrace_summaries': bt_summaries,
    'backtrace_frames': bt_frames
}

receipt_path = logs_base / 'receipt.json'
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(f"Saved Windows x64 receipt to {receipt_path}")
