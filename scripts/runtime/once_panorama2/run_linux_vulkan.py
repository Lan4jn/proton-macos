import hashlib
import json
import os
import sys
import time
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-once-panorama2-derived/build/elfuse'
assert rt.exists(), f"elfuse binary not found at {rt}"
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()
print(f"elfuse SHA256: {rt_sha}")

python_guest = lab / 'fixtures/runtime/arch-case/usr/bin/python3.14'
probe_script = lab / 'scripts/runtime/vulkan_queue/probe_queue_fill.py'
sysroot = lab / 'fixtures/runtime/arch-case'
lavapipe_icd = lab / 'fixtures/runtime/lavapipe-derived/usr/share/vulkan/icd.d/lvp_icd.json'

log_root = lab / 'logs/once-panorama2/linux'
log_root.mkdir(parents=True, exist_ok=True)

argv = [
    str(rt),
    '--user', '501:20',
    '--sysroot', str(sysroot),
    '--timeout', '25',
    str(python_guest),
    str(probe_script)
]

extra_env = {
    'VK_ICD_FILENAMES': str(lavapipe_icd),
    'ELFUSE_ONCE_PANORAMA_OBSERVE': '1',
    'ELFUSE_ONCE_COUNT_OBSERVE': '1',
    'ELFUSE_ONCE_TRACE_OBSERVE': '1'
}

print("Starting Linux ARM64 Vulkan probe under once-panorama2 instrumentation...")
t0 = time.monotonic()
res = run_isolated(argv, log_root, timeout=30, extra_env=extra_env)
elapsed = time.monotonic() - t0

stdout_txt = Path(res['stdout']).read_text(errors='replace')
stderr_txt = Path(res['stderr']).read_text(errors='replace')

print(f"Completed in {elapsed:.3f}s, exit: {res['exit']}, timed_out: {res['timed_out']}")

once_entries = [l for l in stderr_txt.splitlines() if 'ONCE_ENTRY_COUNT' in l]
once_armed = [l for l in stderr_txt.splitlines() if 'ONCE_COUNT_ARMED' in l]

print(f"Captured once entries count: {len(once_entries)}")
print(f"ONCE_COUNT_ARMED lines: {len(once_armed)}")
if once_armed:
    print("  ", once_armed[0])
for e in once_entries[:10]:
    print("  ", e)
if len(once_entries) > 10:
    print(f"  ... ({len(once_entries) - 10} more)")

# Check validity: Linux probe exits 0 and produces PATTERN_MATCH_OK
has_match_ok = "PATTERN_MATCH_OK" in stdout_txt
run_valid = (res['exit'] == 0) and has_match_ok
validity_status = "VALID" if run_valid else "run_valid=false / FAILED"

print(f"Linux Vulkan Run Validity: {validity_status} (exit={res['exit']}, has_match_ok={has_match_ok})")

receipt = {
    'path_type': 'Linux_ARM64_Vulkan_Lavapipe',
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
    'once_armed': once_armed,
    'once_entries': once_entries
}

receipt_path = log_root / 'receipt.json'
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(f"Saved Linux receipt to {receipt_path}")
