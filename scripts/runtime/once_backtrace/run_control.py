import hashlib
import json
import os
import re
import sys
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-once-backtrace-derived/build/elfuse'
assert rt.exists(), f"elfuse binary not found at {rt}"
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()
print(f"elfuse SHA256: {rt_sha}")

argv = [
    str(rt),
    '--sysroot',
    str(lab / 'fixtures/runtime/arch-case'),
    '--timeout',
    '8',
    str(lab / 'fixtures/runtime/arch-case/usr/bin/python3.14'),
    str(lab / 'scripts/runtime/once_backtrace/control.py')
]

extra_env = {
    'ELFUSE_ONCE_TRACE_OBSERVE': '1',
    'ELFUSE_ONCE_COUNT_OBSERVE': '1',
    'ELFUSE_ONCE_PANORAMA_OBSERVE': '1',
    'ELFUSE_ONCE_TRACE_UADDR': '0x203000440',
    'ELFUSE_ONCE_COUNT_UADDR': '0x203000440',
    'ELFUSE_THREAD_LIFETIME_OBSERVE': '1',
    'ELFUSE_FUTEX_OWNER_OBSERVE': '1'
}

log_root = lab / 'logs/once-backtrace'
log_root.mkdir(parents=True, exist_ok=True)
result = run_isolated(argv, log_root / 'control_run', timeout=12, extra_env=extra_env)

stdout_text = Path(result['stdout']).read_text(errors='replace')
stderr_text = Path(result['stderr']).read_text(errors='replace')

print("=== STDOUT ===")
print(stdout_text)
print("=== STDERR ===")
print(stderr_text)

assert result['exit'] == 0, f"Control test exited with {result['exit']}"
assert not result['timed_out'], "Control test timed out"
assert 'ONCE_COUNT_CONTROLS_OK' in stdout_text, "ONCE_COUNT_CONTROLS_OK not found in stdout"

bt_frames = [l for l in stderr_text.splitlines() if 'ONCE_BACKTRACE_FRAME' in l]
bt_summaries = [l for l in stderr_text.splitlines() if 'ONCE_BACKTRACE_SUMMARY' in l]

print(f"Captured {len(bt_frames)} backtrace frame lines:")
for f in bt_frames:
    print("  ", f)

print(f"Captured {len(bt_summaries)} backtrace summary lines:")
for s in bt_summaries:
    print("  ", s)

assert len(bt_frames) >= 2, f"Expected at least 2 backtrace frames, got {len(bt_frames)}"
assert len(bt_summaries) >= 2, f"Expected 2 backtrace summaries, got {len(bt_summaries)}"

receipt = {
    'test': 'once_backtrace_control',
    'status': 'PASS',
    'runtime_sha256': rt_sha,
    'exit_code': result['exit'],
    'timed_out': result['timed_out'],
    'target_uaddr': '0x203000440',
    'backtrace_frames_count': len(bt_frames),
    'backtrace_summaries': bt_summaries,
    'backtrace_frames': bt_frames,
    'stdout': stdout_text,
    'run_dir': result['run_dir']
}

receipt_path = log_root / 'control.json'
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(f"\nSaved control receipt to {receipt_path}")
print("CONTROL_BACKTRACE_PASS: Stack frame walking and module resolution verified!")
