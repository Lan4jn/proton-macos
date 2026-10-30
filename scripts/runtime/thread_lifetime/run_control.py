import hashlib
import json
import os
import re
import sys
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-thread-lifetime-derived/build/elfuse'
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
    str(lab / 'scripts/runtime/thread_lifetime/control.py')
]

extra_env = {
    'ELFUSE_THREAD_LIFETIME_OBSERVE': '1',
    'ELFUSE_FUTEX_OWNER_OBSERVE': '1',
    'ELFUSE_FUTEX_TARGET_UADDR': '0',
}

log_root = lab / 'logs/thread-lifetime'
result = run_isolated(argv, log_root, timeout=12, extra_env=extra_env)

stdout_text = Path(result['stdout']).read_text(errors='replace')
stderr_text = Path(result['stderr']).read_text(errors='replace')

print("=== STDOUT ===")
print(stdout_text)
print("=== STDERR (first 50 lines) ===")
print("\n".join(stderr_text.splitlines()[:50]))

assert result['exit'] == 0, f"Control test exited with {result['exit']}"
assert not result['timed_out'], "Control test timed out"
assert 'THREAD_LIFETIME_CONTROLS_OK' in stdout_text, "THREAD_LIFETIME_CONTROLS_OK not found in stdout"

# Collect observer lines
lt_enters = [l for l in stderr_text.splitlines() if l.startswith('THREAD_LIFETIME_ENTER')]
lt_returns = [l for l in stderr_text.splitlines() if l.startswith('THREAD_LIFETIME_RETURN')]
lt_events = [l for l in stderr_text.splitlines() if l.startswith('THREAD_LIFETIME_EVENT')]
snapshots_begin = [l for l in stderr_text.splitlines() if l.startswith('THREAD_SNAPSHOT_BEGIN')]

print(f"Captured lines:")
print(f"  THREAD_LIFETIME_ENTER:  {len(lt_enters)}")
print(f"  THREAD_LIFETIME_RETURN: {len(lt_returns)}")
print(f"  THREAD_LIFETIME_EVENT:  {len(lt_events)}")
print(f"  THREAD_SNAPSHOT_BEGIN:  {len(snapshots_begin)}")

assert len(lt_enters) > 0, "No THREAD_LIFETIME_ENTER captured"
assert len(lt_returns) > 0, "No THREAD_LIFETIME_RETURN captured"
assert len(lt_events) > 0, "No THREAD_LIFETIME_EVENT captured"
assert len(snapshots_begin) > 0, "No THREAD_SNAPSHOT_BEGIN captured"

control_box = {
    'runtime_sha256': rt_sha,
    'result': result,
    'stdout': stdout_text,
    'counts': {
        'enters': len(lt_enters),
        'returns': len(lt_returns),
        'events': len(lt_events),
        'snapshots': len(snapshots_begin)
    },
    'sample_enters': lt_enters[:6],
    'sample_returns': lt_returns[:6],
    'sample_events': lt_events[:6],
    'sample_snapshots': snapshots_begin[:6]
}

(log_root / 'control.json').write_text(json.dumps(control_box, indent=2) + '\n')
print(f"Saved control output to {log_root / 'control.json'}")
