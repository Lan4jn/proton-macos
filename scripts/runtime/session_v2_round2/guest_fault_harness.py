"""Guest fault injection runner: inner timeout and worker crash."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

LAB = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
P0 = LAB / 'scripts/runtime/session_v2/run.py'
P0_SHA = '3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b'
LAUNCHER = HERE / 'fault_launcher.py'

RUNTIMES = {
    'original': {
        'path': LAB / 'sources/elfuse-once-panorama2-derived/build/elfuse',
        'sha256': '8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda',
    },
    'derived': {
        'path': LAB / 'sources/elfuse-inproc-present-derived/build/elfuse',
        'sha256': '3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926',
    },
}

PROBE_ELF = {
    'path': LAB / 'sources/p0-session-round2/session_probe',
    'sha256': 'f2446b87c79d66a283d808d3d68f90621ec9cb0601e97198988721d1ab15fa1b',
}

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def make_root_manifest(root):
    manifest = {}
    for p in root.rglob('*'):
        if p.is_file(): manifest[str(p.relative_to(root))] = sha256_file(p)
        elif p.is_dir(): manifest[str(p.relative_to(root))] = 'directory'
    return manifest

def run_fault_scenario(mode, role, run_id, inject_fault_failure=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError(f'Invalid run-id: {run_id}')
    if mode not in ('timeout', 'crash'):
        raise ValueError(f'Invalid fault mode: {mode}')
    if role not in ('fake', 'original', 'derived'):
        raise ValueError(f'Invalid role: {role}')

    if role != 'fake':
        lock_token = os.environ.get('GUEST_LOCK_TOKEN')
        if not lock_token:
            raise RuntimeError('guest execution locked; requires GUEST_LOCK_TOKEN')

    if sha256_file(P0) != P0_SHA:
        raise RuntimeError('P0 SHA mismatch')

    spec = importlib.util.spec_from_file_location('p0', P0)
    p0 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(p0)
    p0.LOGS = LAB / 'logs/session-v2-round2'

    observer = HERE / 'guest_observer.py'

    if role == 'fake':
        root = LAB / 'sources/p0-session-round2' / ('guest-fake-' + run_id)
        assert root.resolve().parent == (LAB / 'sources/p0-session-round2').resolve()
        (root / 'tmp').mkdir(parents=True, exist_ok=False)
        manifest = make_root_manifest(root)
        (root / 'root_manifest.json').write_text(json.dumps(manifest, indent=2))
        runtime_path = HERE / 'fake_runtime.py'
        target_cmd = [sys.executable, '-I', str(observer), '--root', str(root), '--runtime', str(runtime_path), '--fake']
    else:
        rt_info = RUNTIMES[role]
        if sha256_file(rt_info['path']) != rt_info['sha256']:
            raise RuntimeError(f'runtime {role} SHA mismatch')
        if sha256_file(PROBE_ELF['path']) != PROBE_ELF['sha256']:
            raise RuntimeError('probe ELF SHA mismatch')

        root = LAB / 'sources/p0-session-round2' / ('guest-fixture-' + run_id)
        assert root.resolve().parent == (LAB / 'sources/p0-session-round2').resolve()
        root.mkdir(parents=True, exist_ok=False)
        (root / 'bin').mkdir(parents=True, exist_ok=False)
        (root / 'tmp').mkdir(parents=True, exist_ok=False)
        installed_probe = root / 'bin/probe'
        shutil.copyfile(PROBE_ELF['path'], installed_probe)
        installed_probe.chmod(0o755)
        manifest = make_root_manifest(root)
        (root / 'root_manifest.json').write_text(json.dumps(manifest, indent=2))
        runtime_path = rt_info['path']
        target_cmd = [sys.executable, '-I', str(observer), '--root', str(root), '--runtime', str(runtime_path)]

    # Both modes stall at PRE: timeout waits for 2s timeout; crash waits for SIGKILL
    target_cmd.append('--stall')

    outer_budget = 6 if mode == 'timeout' else 15
    if mode == 'timeout':
        # Inner timeout = 2s, outer timeout = 6s
        p0_args = [
            '--run-id', run_id,
            '--timeout', '2',
            '--outer-timeout', str(outer_budget),
            '--fixture-short-outer',
            '--module', 'runtime=' + str(runtime_path),
            '--module', 'observer=' + str(observer),
            '--', *target_cmd,
        ]
    else:
        # Crash mode: inner timeout 10s, outer timeout 15s
        p0_args = [
            '--run-id', run_id,
            '--timeout', '10',
            '--outer-timeout', str(outer_budget),
            '--module', 'runtime=' + str(runtime_path),
            '--module', 'observer=' + str(observer),
            '--', *target_cmd,
        ]

    # Sentinel setup in isolated process group
    sentinel = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'], start_new_session=True)
    p0_proc = None

    session_root = p0.LOGS / run_id
    pre_file = session_root / 'work/guest-pre.json'
    owned_file = session_root / 'owned.json'

    fault_record = {
        'mode': mode,
        'role': role,
        'run_id': run_id,
        'pre_arrival_time': None,
        'signal_sent': None,
        'known_before_fault': [],
        'fault_error': None,
    }

    t0 = time.monotonic()
    runner_exit = None
    known_identities = []
    fault_exception = None

    try:
        p0_proc = subprocess.Popen(
            [sys.executable, '-I', str(LAUNCHER), *p0_args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if inject_fault_failure:
            raise RuntimeError('injected fault controller failure')

        # Wait for PRE barrier snapshot to be recorded (max 8s)
        deadline = time.monotonic() + 8.0
        while not pre_file.exists():
            if p0_proc.poll() is not None:
                break
            if time.monotonic() > deadline:
                raise TimeoutError('guest-pre.json not generated within 8s; PRE barrier unreached')
            time.sleep(0.02)

        if not pre_file.exists():
            stdout, stderr = p0_proc.communicate(timeout=2)
            raise RuntimeError(f'P0 worker ended before PRE reached: code={p0_proc.returncode}\nOUT:\n{stdout}\nERR:\n{stderr}')

        t_pre = time.monotonic()
        fault_record['pre_arrival_time'] = t_pre - t0

        pre_data = json.loads(pre_file.read_text())
        known_identities = [{'pid': r['pid'], 'identity': r['identity'], 'pgid': r['pgid']} for r in pre_data['snapshots'][0]]
        fault_record['known_before_fault'] = known_identities

        if mode == 'crash':
            # Verify worker identity strictly
            deadline_owner = time.monotonic() + 2.0
            while not owned_file.exists() and time.monotonic() < deadline_owner:
                time.sleep(0.01)
            owner = json.loads(owned_file.read_text())
            rows = p0.snapshot()
            current_worker = next((r for r in rows if r['pid'] == owner['pid']), None)
            if not current_worker or current_worker['identity'] != owner['identity'] or current_worker['pgid'] != owner['pgid']:
                raise RuntimeError('worker identity lost or invalid before fault')
            # Send single SIGKILL to verified worker
            os.kill(owner['pid'], signal.SIGKILL)
            fault_record['signal_sent'] = {'pid': owner['pid'], 'identity': owner['identity'], 'signal': 'SIGKILL', 'result': 'sent'}

        # Wait for P0 parent to finish normally through its own runner logic
        stdout, stderr = p0_proc.communicate(timeout=outer_budget + 4.0)
        runner_exit = p0_proc.returncode
    except Exception as exc:
        fault_exception = str(exc)
        fault_record['fault_error'] = fault_exception
        # If P0 parent is still running during an unexpected failure, DO NOT terminate it.
        # Wait for P0 parent to complete its own outer timeout + cleanup cleanly.
        if p0_proc and p0_proc.poll() is None:
            try:
                stdout, stderr = p0_proc.communicate(timeout=outer_budget + 4.0)
                runner_exit = p0_proc.returncode
            except subprocess.TimeoutExpired:
                # If even outer timeout exceeded by large margin, only then reap P0 parent process
                p0_proc.kill()
                p0_proc.wait(timeout=2)
                runner_exit = p0_proc.returncode
    finally:
        sentinel_alive = sentinel.poll() is None
        if sentinel_alive:
            sentinel.terminate()
        sentinel.wait(timeout=3)

    receipt_file = session_root / 'receipt.json'
    receipt = json.loads(receipt_file.read_text()) if receipt_file.exists() else None

    # Check that all pre-fault known identities are reaped/gone
    after_rows = p0.snapshot()
    leaked = [r for r in after_rows if any(r['pid'] == k['pid'] and r['identity'] == k['identity'] for k in known_identities) and not r['state'].startswith('Z')]

    status = 'PASS' if (not fault_exception and receipt and receipt.get('cleanup', {}).get('complete') and not leaked) else 'UNKNOWN'

    summary = {
        'status': status,
        'run_id': run_id,
        'mode': mode,
        'role': role,
        'runner_exit': runner_exit,
        'target_exit': receipt.get('target_exit') if receipt else None,
        'inner_timed_out': receipt.get('inner_timed_out') if receipt else None,
        'outer_timed_out': receipt.get('outer_timed_out') if receipt else None,
        'cleanup_complete': receipt['cleanup']['complete'] if (receipt and 'cleanup' in receipt) else False,
        'sentinel_alive': sentinel_alive,
        'sentinel_reaped': sentinel.poll() is not None,
        'known_before_fault': known_identities,
        'leaked_processes': leaked,
        'fault_record': fault_record,
        'error': fault_exception,
    }
    try:
        (session_root / 'fault-summary.json').write_text(json.dumps(summary, indent=2))
    except Exception:
        pass
    return summary

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['timeout', 'crash'], required=True)
    ap.add_argument('--role', choices=['fake', 'original', 'derived'], required=True)
    ap.add_argument('--run-id', required=True)
    args = ap.parse_args()
    summary = run_fault_scenario(args.mode, args.role, args.run_id)
    print(json.dumps(summary, indent=2))
    sys.exit(0 if summary['status'] == 'PASS' else 1)
