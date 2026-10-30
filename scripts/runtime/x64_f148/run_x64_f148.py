import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / 'sources/elfuse-crashdump-derived/build/elfuse'
probe = lab / 'scripts/runtime/x64_vk/vk_enum_x64.exe'
sysroot = lab / 'fixtures/runtime/arch-case'
source_prefix = lab / 'fixtures/runtime/futex-args-vulkan/pfx'
logs_root = lab / 'logs/x64-f148-trace'
run_root = logs_root / 'rerun'

assert rt.exists(), f"Derived runtime not found: {rt}"
assert probe.exists(), f"Existing x64 probe not found: {probe}"
assert source_prefix.exists(), f"Existing source prefix not found: {source_prefix}"

runtime_sha = hashlib.sha256(rt.read_bytes()).hexdigest()
probe_sha = hashlib.sha256(probe.read_bytes()).hexdigest()

if run_root.exists():
    raise RuntimeError(f"Refusing to reuse existing rerun path: {run_root}")
run_root.mkdir(parents=True)
prefix = run_root / 'pfx'
shutil.copytree(source_prefix, prefix, symlinks=True)
shutil.copyfile(probe, prefix / 'drive_c' / 'vk_enum_x64.exe')

# Preserve the prior x64 runner's argv, sysroot, prefix semantics, and diagnostic environment.
old_result = json.loads((lab / 'logs/vulkan-null-driver/result.json').read_text())
argv = old_result['result']['argv'][:]
argv[0] = str(rt)
argv = [('WINEPREFIX=' + str(prefix)) if s.startswith('WINEPREFIX=') else s for s in argv]
for i, value in enumerate(argv):
    if 'vk_enum_arm64.exe' in value:
        argv[i] = value.replace('vk_enum_arm64.exe', 'vk_enum_x64.exe')

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

print(f"runtime_sha256={runtime_sha}")
print(f"probe_sha256={probe_sha}")
print(f"prefix={prefix}")
print("Running identical x64 Vulkan probe/argv with derived read-only crash observation...")
start = time.monotonic()
result = run_isolated(argv, run_root, timeout=62, extra_env=extra_env)
elapsed = time.monotonic() - start
stdout_path = Path(result['stdout'])
stderr_path = Path(result['stderr'])
stdout = stdout_path.read_text(errors='replace')
stderr = stderr_path.read_text(errors='replace')

keys = (
    'unexpected exception', 'X64_F148_READONLY_TRACE', 'X64_F148_LR_INSN',
    'X64_F148_STACK64', '## Registers', 'X2  =', 'X30  =', 'SP0',
    'FUTEX_OWNER_ENTER', 'ONCE_COUNT_ARMED', 'Step 3:', 'Step 4:'
)
interesting = [line for line in stderr.splitlines() if any(key in line for key in keys)]
stdout_interesting = [line for line in stdout.splitlines() if '[WIN_ARM64_VK]' in line]
receipt = {
    'purpose': 'Task-107 read-only crash observation rerun',
    'runtime_sha256': runtime_sha,
    'probe_sha256': probe_sha,
    'probe': str(probe),
    'source_prefix': str(source_prefix),
    'run_prefix': str(prefix),
    'argv': argv,
    'extra_env': extra_env,
    'exit_code': result['exit'],
    'timed_out': result['timed_out'],
    'elapsed_sec': elapsed,
    'stdout_bytes': len(stdout.encode('utf-8', errors='replace')),
    'stderr_bytes': len(stderr.encode('utf-8', errors='replace')),
    'stdout_path': str(stdout_path),
    'stderr_path': str(stderr_path),
    'stdout_probe_lines': stdout_interesting,
    'stderr_observation_lines': interesting,
    'run_dir': result.get('run_dir', str(run_root))
}
receipt_path = logs_root / 'receipt.json'
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(f"exit={result['exit']} timed_out={result['timed_out']} elapsed={elapsed:.3f}s stdout_bytes={receipt['stdout_bytes']} stderr_bytes={receipt['stderr_bytes']}")
print("=== STDOUT PROBE LINES ===")
for line in stdout_interesting:
    print(line)
print("=== STDERR OBSERVATION LINES ===")
for line in interesting:
    print(line)
print(f"receipt={receipt_path}")
