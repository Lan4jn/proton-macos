import hashlib
import json
import os
import sys
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-once-bypass-derived/build/elfuse'
assert rt.exists(), f"elfuse binary not found at {rt}"
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()

log_root = lab / 'logs/once-bypass'
log_root.mkdir(parents=True, exist_ok=True)

control_script = lab / 'scripts/runtime/once_bypass/control.py'
python_guest = '/usr/bin/python3.14'

argv = [
    str(rt),
    '--sysroot', str(lab / 'fixtures/runtime/arch-case'),
    '--timeout', '4',
    python_guest,
    str(control_script)
]

extra_env = {
    'ELFUSE_DIAG_ONCE_BYPASS': '1',
    'ELFUSE_FUTEX_TARGET_UADDR': '0' # match all uaddr in control
}

print("Running control test via run_isolated with ELFUSE_DIAG_ONCE_BYPASS=1...")
result = run_isolated(argv, extra_env=extra_env, log_root=log_root)

stdout_text = Path(result['stdout']).read_text()
stderr_text = Path(result['stderr']).read_text()

print(f"Exit code: {result['exit']}, seconds: {result['seconds']:.3f}")
print("Stdout:", stdout_text.strip())
print("Stderr:", stderr_text.strip())

assert result['exit'] == 0, f"Control run failed with exit {result['exit']}"
assert "ONCE_BYPASS_CONTROLS_OK MUTATED_TO_2" in stdout_text, "Verification string missing in stdout"
assert "[DIAGNOSTIC] ONCE_DEADLOCK_BYPASSED" in stderr_text, "Bypass marker missing in stderr"

control_box = {
    'runtime_sha256': rt_sha,
    'result': result,
    'stdout': stdout_text,
    'stderr': stderr_text,
    'status': 'PASS'
}

(log_root / 'control.json').write_text(json.dumps(control_box, indent=2) + '\n')
print(f"Saved control output to {log_root / 'control.json'}")
