import hashlib
import json
import os
import re
import sys
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-once-trace-derived/build/elfuse'
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
    str(lab / 'scripts/runtime/once_trace/control.py')
]

extra_env = {
    'ELFUSE_ONCE_TRACE_OBSERVE': '1',
    'ELFUSE_ONCE_TRACE_UADDR': '0x203000440',
    'ELFUSE_THREAD_LIFETIME_OBSERVE': '1',
    'ELFUSE_FUTEX_OWNER_OBSERVE': '1'
}

log_root = lab / 'logs/once-trace'
result = run_isolated(argv, log_root, timeout=12, extra_env=extra_env)

stdout_text = Path(result['stdout']).read_text(errors='replace')
stderr_text = Path(result['stderr']).read_text(errors='replace')

print("=== STDOUT ===")
print(stdout_text)
print("=== STDERR (first 40 lines) ===")
print("\n".join(stderr_text.splitlines()[:40]))

assert result['exit'] == 0, f"Control test exited with {result['exit']}"
assert not result['timed_out'], "Control test timed out"
assert 'ONCE_TRACE_CONTROLS_OK' in stdout_text, "ONCE_TRACE_CONTROLS_OK not found in stdout"

# Collect observer lines
transitions = [l for l in stderr_text.splitlines() if l.startswith('ONCE_TRANSITION')]
print(f"Captured {len(transitions)} ONCE_TRANSITION lines:")
for l in transitions:
    print("  ", l)

assert len(transitions) >= 2, f"Expected at least 2 transitions, got {len(transitions)}"

control_box = {
    'runtime_sha256': rt_sha,
    'result': result,
    'stdout': stdout_text,
    'transitions': transitions,
    'transition_count': len(transitions)
}

(log_root / 'control.json').write_text(json.dumps(control_box, indent=2) + '\n')
print(f"Saved control output to {log_root / 'control.json'}")
