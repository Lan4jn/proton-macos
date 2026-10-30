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

rt = lab / 'sources/elfuse-once-bypass-derived/build/elfuse'
assert rt.exists(), f"elfuse binary not found at {rt}"
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()
print(f"Elfuse binary SHA256: {rt_sha}")

logs_base = lab / 'logs/once-bypass'
logs_base.mkdir(parents=True, exist_ok=True)

src_pfx = lab / 'fixtures/runtime/futex-args-vulkan/pfx'
assert src_pfx.exists(), f"Source prefix not found: {src_pfx}"

old_result = json.loads((lab / 'logs/vulkan-null-driver/result.json').read_text())

def run_single_experiment(mode: str, enable_bypass: bool, timeout_sec: int = 62):
    print(f"\n=======================================================")
    print(f"Starting {mode.upper()} run (enable_bypass={enable_bypass}, timeout={timeout_sec}s)...")
    print(f"=======================================================")
    
    mode_dir = logs_base / mode
    if mode_dir.exists():
        shutil.rmtree(mode_dir)
    mode_dir.mkdir(parents=True, exist_ok=True)
    
    # Independent prefix copy
    pfx_dir = mode_dir / 'pfx'
    shutil.copytree(src_pfx, pfx_dir, symlinks=True)
    print(f"Copied independent prefix to {pfx_dir}")

    argv = old_result['result']['argv'][:]
    argv[0] = str(rt)
    argv = [('WINEPREFIX=' + str(pfx_dir)) if s.startswith('WINEPREFIX=') else s for s in argv]

    extra_env = {
        'ELFUSE_DIAG_SESSION_SHARED': '1',
        'ELFUSE_IO_TRANSACTION_OBSERVE': '1',
        'ELFUSE_FIXTURE_IDENTITY': '1',
        'ELFUSE_FUTEX_OWNER_OBSERVE': '1',
        'ELFUSE_FUTEX_TARGET_UADDR': '0x20102d440',
        'ELFUSE_THREAD_LIFETIME_OBSERVE': '1'
    }
    if enable_bypass:
        extra_env['ELFUSE_DIAG_ONCE_BYPASS'] = '1'

    t0 = time.monotonic()
    result = run_isolated(argv, mode_dir, timeout=timeout_sec, extra_env=extra_env)
    elapsed = time.monotonic() - t0
    
    print(f"Run completed in {elapsed:.2f}s, exit: {result['exit']}, timed_out: {result['timed_out']}")
    
    stdout_text = Path(result['stdout']).read_text(errors='replace')
    stderr_text = Path(result['stderr']).read_text(errors='replace')
    
    owner_enters = [l for l in stderr_text.splitlines() if l.startswith('FUTEX_OWNER_ENTER')]
    target_enters = [l for l in owner_enters if 'uaddr=0x20102d440' in l]
    bypass_events = [l for l in stderr_text.splitlines() if '[DIAGNOSTIC] ONCE_DEADLOCK_BYPASSED' in l]
    
    has_step3 = "[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)..." in stdout_text
    
    if enable_bypass:
        # In bypass mode, valid if Step 3 reached and bypass occurred
        run_valid = has_step3 and (len(bypass_events) > 0 or len(target_enters) > 0)
    else:
        # In baseline mode, valid if Step 3 reached and target futex enter captured (hangs as expected)
        run_valid = has_step3 and (len(target_enters) > 0)
        
    validity_status = "VALID" if run_valid else "run_valid=false / NOT_REPRODUCED"
    
    print(f"Validity: {validity_status} (has_step3={has_step3}, target_enters={len(target_enters)}, bypass_events={len(bypass_events)})")
    print(f"Stdout bytes: {len(stdout_text.encode('utf-8'))}, Stderr bytes: {len(stderr_text.encode('utf-8'))}")
    if stdout_text.strip():
        print("Stdout preview:\n", stdout_text.strip())
        
    receipt = {
        'mode': mode,
        'enable_bypass': enable_bypass,
        'is_diagnostic_borrowed': True,
        'runtime_sha256': rt_sha,
        'run_valid': run_valid,
        'validity_status': validity_status,
        'result': result,
        'stdout': stdout_text,
        'target_futex_enters': target_enters,
        'futex_owner_enters_count': len(owner_enters),
        'bypass_events': bypass_events,
        'has_step3': has_step3,
        'stderr_bytes': len(stderr_text.encode('utf-8', errors='replace')),
        'stdout_bytes': len(stdout_text.encode('utf-8', errors='replace')),
        'diagnostic_disclaimer': 'BORROWED/DIAGNOSTIC ONLY. NOT A FIX. DOES NOT PROVE VULKAN EXECUTION SUCCEEDED OR ABI CORRECTNESS.'
    }
    
    receipt_file = mode_dir / 'receipt.json'
    receipt_file.write_text(json.dumps(receipt, indent=2) + '\n')
    print(f"Saved receipt to {receipt_file}")
    return receipt

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if target in ('baseline', 'all'):
        run_single_experiment('baseline', enable_bypass=False, timeout_sec=62)
    if target in ('bypass', 'all'):
        run_single_experiment('bypass', enable_bypass=True, timeout_sec=62)
