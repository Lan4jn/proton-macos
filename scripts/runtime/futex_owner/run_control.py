import hashlib
import json
import os
import re
import sys
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-futex-owner-derived/build/elfuse'
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
    str(lab / 'scripts/runtime/futex_owner/control.py')
]

extra_env = {
    'ELFUSE_FUTEX_OWNER_OBSERVE': '1',
    'ELFUSE_FUTEX_TARGET_UADDR': '0',
}

log_root = lab / 'logs/futex-owner'
result = run_isolated(argv, log_root, timeout=12, extra_env=extra_env)

stdout_text = Path(result['stdout']).read_text(errors='replace')
stderr_text = Path(result['stderr']).read_text(errors='replace')

print("=== STDOUT ===")
print(stdout_text)
print("=== STDERR (first 40 lines) ===")
print("\n".join(stderr_text.splitlines()[:40]))

# Verify control passed
assert result['exit'] == 0, f"Control test exited with {result['exit']}"
assert not result['timed_out'], "Control test timed out"
assert 'FUTEX_OWNER_CONTROLS_OK' in stdout_text, "FUTEX_OWNER_CONTROLS_OK not found in stdout"

# Collect observer lines
owner_enters = [l for l in stderr_text.splitlines() if l.startswith('FUTEX_OWNER_ENTER')]
owner_maps = [l for l in stderr_text.splitlines() if l.startswith('FUTEX_OWNER_MAP')]
owner_threads = [l for l in stderr_text.splitlines() if l.startswith('FUTEX_OWNER_THREAD')]
owner_returns = [l for l in stderr_text.splitlines() if l.startswith('FUTEX_OWNER_RETURN')]

print(f"Captured: {len(owner_enters)} enters, {len(owner_maps)} maps, {len(owner_threads)} thread records, {len(owner_returns)} returns")
assert len(owner_enters) > 0, "No FUTEX_OWNER_ENTER lines captured"
assert len(owner_maps) > 0, "No FUTEX_OWNER_MAP lines captured"
assert len(owner_threads) > 0, "No FUTEX_OWNER_THREAD lines captured"
assert len(owner_returns) > 0, "No FUTEX_OWNER_RETURN lines captured"

control_box = {
    'runtime_sha256': rt_sha,
    'result': result,
    'stdout': stdout_text,
    'counts': {
        'enters': len(owner_enters),
        'maps': len(owner_maps),
        'threads': len(owner_threads),
        'returns': len(owner_returns)
    },
    'sample_enters': owner_enters[:5],
    'sample_maps': owner_maps[:9],
    'sample_threads': owner_threads[:6],
    'sample_returns': owner_returns[:5]
}

(log_root / 'control.json').write_text(json.dumps(control_box, indent=2) + '\n')
print(f"Saved control output to {log_root / 'control.json'}")
