"""Wine initialization diagnostics launcher (Round 3):
Minimal adapter importing frozen Stage 3 v2 (508685), injecting WINEDEBUG=+timestamp,+pid,+module,+seh,+loaddll,
enforcing 32MiB soft_threshold on stderr with bounded termination, and keeping single PGID governance.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[2]

FROZEN_STAGE3_V2_LAUNCHER = LAB / 'scripts/runtime/session_v2_round2/stage3/wine_launcher_stage3_v2.py'
FROZEN_STAGE3_V2_SHA = '5086855c30dbef45dce60b3d243896b1efbb6f76d96038a7ec754a8dc5332b57'

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

if sha256_file(FROZEN_STAGE3_V2_LAUNCHER) != FROZEN_STAGE3_V2_SHA:
    raise SystemExit('Frozen wine_launcher_stage3_v2.py SHA mismatch')

spec = importlib.util.spec_from_file_location('stage3_v2_base', FROZEN_STAGE3_V2_LAUNCHER)
base_s3v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base_s3v2)

WINEDEBUG_VALUE = '+timestamp,+pid,+module,+seh,+loaddll'
STDERR_SOFT_THRESHOLD_BYTES = 32 * 1024 * 1024  # 32 MiB soft threshold (polled every 200ms)

def build_wineserver_command_r3(runtime_path, sysroot_dir):
    return base_s3v2.build_wineserver_command_stage3(runtime_path, sysroot_dir)

def build_wine_pe_command_r3(runtime_path, sysroot_dir):
    cmd = list(base_s3v2.build_wine_pe_command_stage3(runtime_path, sysroot_dir))
    cmd.insert(-2, '--env')
    cmd.insert(-2, f'WINEDEBUG={WINEDEBUG_VALUE}')
    return cmd

class StderrCapMonitor:
    def __init__(self, log_path, soft_threshold_bytes=STDERR_SOFT_THRESHOLD_BYTES, check_interval=0.2):
        self.log_path = Path(log_path)
        self.soft_threshold_bytes = soft_threshold_bytes
        self.check_interval = check_interval
        self.stop_event = threading.Event()
        self.exceeded = False
        self.observed_bytes = 0
        self.thread = None

    def _run(self, proc):
        while not self.stop_event.is_set():
            if self.log_path.exists():
                try:
                    sz = self.log_path.stat().st_size
                    self.observed_bytes = sz
                    if sz > self.soft_threshold_bytes:
                        self.exceeded = True
                        if proc and proc.poll() is None:
                            proc.terminate()
                        break
                except OSError:
                    pass
            self.stop_event.wait(self.check_interval)

    def start(self, proc):
        self.thread = threading.Thread(target=self._run, args=(proc,), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.log_path.exists():
            try:
                self.observed_bytes = self.log_path.stat().st_size
            except OSError:
                pass

def read_capped_stderr(log_path, max_read_bytes=STDERR_SOFT_THRESHOLD_BYTES):
    p = Path(log_path)
    if not p.exists():
        return ""
    try:
        with open(p, 'rb') as f:
            data = f.read(max_read_bytes)
        return data.decode('utf-8', errors='replace')
    except Exception:
        return ""

def parse_diagnostics_from_stderr(stderr_text):
    findings = {
        'trace_calls': [],
        'last_call_module_candidate': None,
        'image_load_failure_log': None,
        'exception_address_candidate': None,
        'exception_code_candidate': None,
        'trace_lines_count': 0,
        'limitations': 'Fields are raw candidate traces from logs; Initializing system dll for wineboot reflects image path parameter, not proven fault DLL; last CALL is not guaranteed fault DLL without entry point confirmation.'
    }
    for line in stderr_text.splitlines():
        if " - CALL" in line:
            findings['trace_calls'].append(line)
            findings['last_call_module_candidate'] = line
            findings['trace_lines_count'] += 1
        elif ("Initialization of " in line and " failed" in line) or ("Initializing system dll for " in line and " failed" in line):
            findings['image_load_failure_log'] = line
        elif "Unhandled exception code" in line:
            findings['exception_code_candidate'] = line
        elif "exception in PE entry point" in line:
            findings['exception_address_candidate'] = line
    return findings

def classify_r3_wine_outcome(wine_exit):
    if wine_exit == 43:
        return {'status': 'PASS', 'semantic_marker': 'REACHED_PE_ENTRY_NT_TERMINATE_43'}
    elif wine_exit == 29:
        return {'status': 'UNKNOWN', 'semantic_marker': 'LOADER_FAILURE_EXIT_29', 'reason': 'PE entry execution unverified; Wine exit 29'}
    else:
        return {'status': 'UNKNOWN', 'semantic_marker': f'UNEXPECTED_EXIT_{wine_exit}', 'reason': 'Unverified exit code'}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--role', choices=['fake', 'original', 'derived'], default='fake')
    ap.add_argument('--run-approved', action='store_true')
    ap.add_argument('--fail-probe', action='store_true')
    ap.add_argument('--test-mock-wine-exit', type=int, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    root = Path(args.root)

    # 1. P0 samegroup identity check in real mode BEFORE any directory creation
    if args.role != 'fake':
        run_parent = Path.cwd().parent
        owned_file = run_parent / 'owned.json'
        try:
            owner = json.loads(owned_file.read_text())
            if owner['pgid'] != os.getpgrp():
                sys.stderr.write(f"P0 samegroup mismatch: current {os.getpgrp()} != owned {owner['pgid']}\n")
                return 1
        except (OSError, ValueError, KeyError) as e:
            sys.stderr.write(f"P0 supervised session required (owned.json invalid or missing): {e}\n")
            return 1

        resolved_root = root.resolve()
        if not (run_parent in resolved_root.parents):
            sys.stderr.write(f"Root path escape rejected: {resolved_root} not within P0 run directory {run_parent}\n")
            return 1

    work = root / 'work'
    prefix = root / 'prefix'
    tmp = root / 'tmp'
    work.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)

    result = {
        'status': 'UNKNOWN',
        'role': args.role,
        'server_ready': False,
        'readiness_evidence': None,
        'wineserver_exit': None,
        'wine_exit': None,
        'r3_classification': None,
        'commands': {},
        'stderr_cap': {
            'soft_threshold_bytes': STDERR_SOFT_THRESHOLD_BYTES,
            'observed_bytes': 0,
            'exceeded': False,
            'check_mechanism': '200ms_polling_soft_threshold'
        },
        'diag_parsed_findings': None,
        'error': None,
    }

    server_proc = None
    wine_proc = None
    stderr_monitor = None

    runner_stderr = Path.cwd().parent / 'stderr.log'

    try:
        base_s3v2.base.verify_whitelist()
        base_s3v2.validate_closure_sources()

        if args.role == 'fake':
            if not prefix.exists():
                base_s3v2.base.copy_and_materialize_prefix(base_s3v2.base.TEMPLATE_PFX, prefix, work)

            st = prefix.stat()
            uid = os.getuid()
            sock_dir = root / 'tmp' / f".wine-{uid}" / f"server-{st.st_dev:x}-{st.st_ino:x}"
            sock_dir.mkdir(parents=True, exist_ok=True)
            sock_path = sock_dir / "socket"
            if sock_path.exists(): sock_path.unlink()

            if not args.fail_probe:
                server_cmd = [
                    sys.executable, '-I', '-c', f'''
import os, socket, sys, time
p = "{str(sock_path)}"
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.bind(p)
s.listen(5)
s.settimeout(0.5)
deadline = time.monotonic() + 10.0
while time.monotonic() < deadline:
    try:
        c, _ = s.accept()
        c.close()
    except socket.timeout:
        pass
'''
                ]
                server_proc = subprocess.Popen(server_cmd)

            result['commands']['wineserver'] = build_wineserver_command_r3(base_s3v2.base.WHITELIST['runtime_original']['path'], root)
            result['commands']['wine_pe'] = build_wine_pe_command_r3(base_s3v2.base.WHITELIST['runtime_original']['path'], root)

            deadline = time.monotonic() + 1.0 if args.fail_probe else time.monotonic() + 5.0
            probe_res = {'status': 'WAITING', 'error': 'not_started'}
            while time.monotonic() < deadline:
                probe_res = base_s3v2.base.probe_readiness(None, root, prefix, fake_mode=True)
                if probe_res.get('status') == 'READY':
                    result['server_ready'] = True
                    result['readiness_evidence'] = probe_res
                    break
                time.sleep(0.05)

            result['readiness_evidence'] = probe_res
            if not result['server_ready']:
                result['error'] = 'SERVER_NOT_READY'
                raise RuntimeError('SERVER_NOT_READY: probe connection unestablished')

            target_exit = args.test_mock_wine_exit if args.test_mock_wine_exit is not None else 43
            wine_cmd = [sys.executable, '-I', '-c', f'import sys; sys.exit({target_exit})']
            wine_proc = subprocess.Popen(wine_cmd)
            result['wine_exit'] = wine_proc.wait(timeout=60.0)
            clf = classify_r3_wine_outcome(result['wine_exit'])
            result['r3_classification'] = clf
            result['status'] = clf['status']

        else:
            if not args.run_approved:
                raise RuntimeError('Real wine execution blocked: requires explicit --run-approved flag from Lead')

            runtime_bin = base_s3v2.verify_chosen_runtime(args.role)

            base_s3v2.setup_real_sysroot_stage3_v2(root)

            server_cmd = build_wineserver_command_r3(runtime_bin, root)
            wine_cmd = build_wine_pe_command_r3(runtime_bin, root)
            result['commands']['wineserver'] = server_cmd
            result['commands']['wine_pe'] = wine_cmd

            server_proc = subprocess.Popen(server_cmd)

            deadline = time.monotonic() + 5.0
            probe_res = {'status': 'WAITING', 'error': 'not_started'}
            while time.monotonic() < deadline:
                if server_proc.poll() is not None:
                    break
                probe_res = base_s3v2.base.probe_readiness(runtime_bin, root, prefix, fake_mode=False)
                if probe_res.get('status') == 'READY':
                    result['server_ready'] = True
                    result['readiness_evidence'] = probe_res
                    break
                time.sleep(0.1)

            result['readiness_evidence'] = probe_res
            if not result['server_ready']:
                result['error'] = 'SERVER_NOT_READY'
                raise RuntimeError('SERVER_NOT_READY: real wineserver probe failed')

            wine_proc = subprocess.Popen(wine_cmd)
            stderr_monitor = StderrCapMonitor(runner_stderr, soft_threshold_bytes=STDERR_SOFT_THRESHOLD_BYTES)
            stderr_monitor.start(wine_proc)

            result['wine_exit'] = wine_proc.wait(timeout=60.0)
            stderr_monitor.stop()

            result['stderr_cap']['observed_bytes'] = stderr_monitor.observed_bytes
            result['stderr_cap']['exceeded'] = stderr_monitor.exceeded

            if stderr_monitor.exceeded:
                result['error'] = f'STDERR_SOFT_THRESHOLD_EXCEEDED: size {stderr_monitor.observed_bytes} > {STDERR_SOFT_THRESHOLD_BYTES}'
                result['status'] = 'UNKNOWN'
                result['r3_classification'] = {'status': 'UNKNOWN', 'reason': 'stderr soft threshold exceeded'}
            else:
                clf = classify_r3_wine_outcome(result['wine_exit'])
                result['r3_classification'] = clf
                result['status'] = clf['status']

    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        # Structured inner try-finally for cleanup to guarantee result writeout even on wait/terminate failure
        try:
            if stderr_monitor:
                stderr_monitor.stop()
        except Exception:
            pass

        try:
            if wine_proc and wine_proc.poll() is None:
                wine_proc.terminate()
                wine_proc.wait(timeout=3.0)
        except Exception:
            pass

        try:
            if server_proc and server_proc.poll() is None:
                server_proc.terminate()
                server_proc.wait(timeout=3.0)
                result['wineserver_exit'] = server_proc.returncode
        except Exception:
            pass

        try:
            if runner_stderr.exists():
                stderr_content = read_capped_stderr(runner_stderr, max_read_bytes=STDERR_SOFT_THRESHOLD_BYTES)
                result['diag_parsed_findings'] = parse_diagnostics_from_stderr(stderr_content)
                sz = runner_stderr.stat().st_size
                result['stderr_cap']['observed_bytes'] = sz
                result['stderr_cap']['exceeded'] = sz > STDERR_SOFT_THRESHOLD_BYTES
        except Exception:
            pass

        try:
            (work / 'wine-launcher-result.json').write_text(json.dumps(result, indent=2))
        except Exception:
            pass

    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__':
    sys.exit(main())
