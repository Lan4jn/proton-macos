import hashlib
import json
import os
import re
import sys
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-once-count-derived/build/elfuse'
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
    str(lab / 'scripts/runtime/once_count/control.py')
]

extra_env = {
    'ELFUSE_ONCE_TRACE_OBSERVE': '1',
    'ELFUSE_ONCE_TRACE_UADDR': '0x203000440',
    'ELFUSE_ONCE_COUNT_UADDR': '0x203000440',
    'ELFUSE_THREAD_LIFETIME_OBSERVE': '1',
    'ELFUSE_FUTEX_OWNER_OBSERVE': '1'
}

log_root = lab / 'logs/once-count'
result = run_isolated(argv, log_root, timeout=12, extra_env=extra_env)

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
count_lines = [l for l in stderr_text.splitlines() if 'ONCE_ENTRY_COUNT' in l]

print(f"Captured {len(armed_lines)} armed lines, {len(count_lines)} entry count lines:")
for l in armed_lines:
    print("  ", l)
for l in count_lines:
    print("  ", l)

assert len(armed_lines) >= 1, "Expected at least 1 ONCE_COUNT_ARMED line"
assert len(count_lines) >= 1, "Expected at least 1 ONCE_ENTRY_COUNT line"

control_box = {
    'runtime_sha256': rt_sha,
    'result': result,
    'stdout': stdout_text,
    'armed_lines': armed_lines,
    'count_lines': count_lines
}

(log_root / 'control.json').write_text(json.dumps(control_box, indent=2) + '\n')
print(f"Saved control output to {log_root / 'control.json'}")
