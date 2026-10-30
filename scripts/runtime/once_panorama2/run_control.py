import hashlib
import json
import os
import re
import sys
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-once-panorama2-derived/build/elfuse'
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
    str(lab / 'scripts/runtime/once_panorama2/control.py')
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

log_root = lab / 'logs/once-panorama2'
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

armed_lines = [l for l in stderr_text.splitlines() if 'ONCE_COUNT_ARMED' in l]
assert len(armed_lines) >= 1, f"Expected ONCE_COUNT_ARMED line, got {len(armed_lines)}"
print(f"Found ONCE_COUNT_ARMED: {armed_lines[0]}")

target_lines = [l for l in stderr_text.splitlines() if 'ONCE_ENTRY_COUNT' in l and 'is_target=1' in l]
print(f"Target count lines: {len(target_lines)}")
for l in target_lines:
    print("  ", l)

assert len(target_lines) >= 2, f"CONTROL FAILED: expected target_count >= 2, got {len(target_lines)}"

# Extract target counts and words
c1_word = re.search(r'word=(\d+)', target_lines[0]).group(1)
c2_word = re.search(r'word=(\d+)', target_lines[1]).group(1)
c1_count = re.search(r'target_count=(\d+)', target_lines[0]).group(1)
c2_count = re.search(r'target_count=(\d+)', target_lines[1]).group(1)

print(f"Call 1: target_count={c1_count}, word={c1_word}")
print(f"Call 2: target_count={c2_count}, word={c2_word}")

assert int(c1_count) == 1 and int(c1_word) == 0, f"Call 1 mismatch: count={c1_count}, word={c1_word}"
assert int(c2_count) == 2 and int(c2_word) == 2, f"Call 2 mismatch: count={c2_count}, word={c2_word}"

receipt = {
    'test': 'once_panorama2_control',
    'status': 'PASS',
    'runtime_sha256': rt_sha,
    'exit_code': result['exit'],
    'timed_out': result['timed_out'],
    'target_uaddr': '0x203000440',
    'target_hits_count': len(target_lines),
    'armed_line': armed_lines[0],
    'target_entries': target_lines,
    'stdout': stdout_text,
    'run_dir': result['run_dir']
}

receipt_path = log_root / 'control.json'
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(f"\nSaved control receipt to {receipt_path}")
print("CONTROL_VERIFICATION_PASS: The measuring stick successfully recorded count >= 2 on known repeated target!")
