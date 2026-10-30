"""Wine initialization single-candidate launcher (Round 3 sortdefault.nls hypothesis):
Imports frozen wine_diagnostics_launcher.py (6d32ab), binds CLOSURE_MANIFEST_R3_SORT.json,
materializes sortdefault.nls in wine/share/wine/nls/ and prefix/drive_c/windows/globalization/sorting/,
keeps identical WINEDEBUG=+timestamp,+pid,+module,+seh,+loaddll, budget 60/75/85 and soft 32MiB cap.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[2]

FROZEN_DIAG_LAUNCHER = LAB / 'scripts/runtime/wine_init_round3/wine_diagnostics_launcher.py'
FROZEN_DIAG_SHA = '6d32ab2cf04ca849d9373d3cebb208a9e72238e7ca4f891b475bd02a752c6b82'

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

if sha256_file(FROZEN_DIAG_LAUNCHER) != FROZEN_DIAG_SHA:
    raise SystemExit('Frozen wine_diagnostics_launcher.py SHA mismatch')

spec = importlib.util.spec_from_file_location('diag_base', FROZEN_DIAG_LAUNCHER)
diag_base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag_base)

CLOSURE_MANIFEST_PATH = LAB / 'sources/wine-init-round3/CLOSURE_MANIFEST_R3_SORT.json'
CLOSURE_R3_SORT = json.loads(CLOSURE_MANIFEST_PATH.read_text())

def resolve_repo_path(p_str):
    p = Path(p_str)
    if not p.is_absolute():
        p = LAB / p
    return p.resolve()

def validate_closure_sources_sort():
    pe_p = resolve_repo_path(CLOSURE_R3_SORT['target_pe']['path'])
    if not pe_p.is_file() or sha256_file(pe_p) != CLOSURE_R3_SORT['target_pe']['sha256']:
        raise FileNotFoundError(f"Missing or invalid target PE source: {pe_p}")

    wb_p = resolve_repo_path(CLOSURE_R3_SORT['wineboot_exe']['path'])
    if not wb_p.is_file() or sha256_file(wb_p) != CLOSURE_R3_SORT['wineboot_exe']['sha256']:
        raise FileNotFoundError(f"Missing or invalid wineboot source: {wb_p}")

    for dll_name, info in CLOSURE_R3_SORT['dlls'].items():
        dll_p = resolve_repo_path(info['source'])
        if not dll_p.is_file() or sha256_file(dll_p) != info['sha256']:
            raise FileNotFoundError(f"Missing or invalid closure DLL source: {dll_p}")

    for nls_name, info in CLOSURE_R3_SORT['nls'].items():
        nls_p = resolve_repo_path(info['source'])
        if not nls_p.is_file() or sha256_file(nls_p) != info['sha256']:
            raise FileNotFoundError(f"Missing or invalid closure NLS source: {nls_p}")

def setup_real_sysroot_sort(target_root):
    validate_closure_sources_sort()
    # Call base_s3v2 setup to materialise base sysroot and the 12 DLLs + 3 NLS
    root_manifest = diag_base.base_s3v2.setup_real_sysroot_stage3_v2(target_root)
    root_manifest['r3_sort_deployed'] = {}

    bundle_nls_dst = target_root / 'wine/share/wine/nls'
    bundle_nls_dst.mkdir(parents=True, exist_ok=True)

    sort_info = CLOSURE_R3_SORT['nls']['sortdefault.nls']
    src_sort = resolve_repo_path(sort_info['source'])
    dst_sort = bundle_nls_dst / 'sortdefault.nls'
    diag_base.base_s3v2.base.clone_or_copy(src_sort, dst_sort)
    h_sort = sha256_file(dst_sort)
    if h_sort != sort_info['sha256']:
        raise ValueError('sortdefault.nls SHA mismatch in bundle deployment')

    # Also deploy to prefix windows globalization sorting directory if prefix exists
    pfx_sort_dir = target_root / 'prefix/drive_c/windows/globalization/sorting'
    pfx_sort_dir.mkdir(parents=True, exist_ok=True)
    dst_pfx_sort = pfx_sort_dir / 'sortdefault.nls'
    if dst_pfx_sort.exists() or dst_pfx_sort.is_symlink():
        dst_pfx_sort.unlink()
    diag_base.base_s3v2.base.clone_or_copy(src_sort, dst_pfx_sort)

    root_manifest['r3_sort_deployed']['sortdefault.nls'] = {
        'target': 'wine/share/wine/nls/sortdefault.nls',
        'prefix_target': 'prefix/drive_c/windows/globalization/sorting/sortdefault.nls',
        'sha256': h_sort,
        'inode': dst_sort.stat().st_ino,
    }

    (target_root / 'root_manifest.json').write_text(json.dumps(root_manifest, indent=2))
    return root_manifest

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--role', choices=['fake', 'original', 'derived'], default='fake')
    ap.add_argument('--run-approved', action='store_true')
    ap.add_argument('--fail-probe', action='store_true')
    ap.add_argument('--test-mock-wine-exit', type=int, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    root = Path(args.root)

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
            'soft_threshold_bytes': diag_base.STDERR_SOFT_THRESHOLD_BYTES,
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
        diag_base.base_s3v2.base.verify_whitelist()
        validate_closure_sources_sort()

        if args.role == 'fake':
            if not prefix.exists():
                diag_base.base_s3v2.base.copy_and_materialize_prefix(diag_base.base_s3v2.base.TEMPLATE_PFX, prefix, work)

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

            result['commands']['wineserver'] = diag_base.build_wineserver_command_r3(diag_base.base_s3v2.base.WHITELIST['runtime_original']['path'], root)
            result['commands']['wine_pe'] = diag_base.build_wine_pe_command_r3(diag_base.base_s3v2.base.WHITELIST['runtime_original']['path'], root)

            deadline = time.monotonic() + 1.0 if args.fail_probe else time.monotonic() + 5.0
            probe_res = {'status': 'WAITING', 'error': 'not_started'}
            while time.monotonic() < deadline:
                probe_res = diag_base.base_s3v2.base.probe_readiness(None, root, prefix, fake_mode=True)
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
            clf = diag_base.classify_r3_wine_outcome(result['wine_exit'])
            result['r3_classification'] = clf
            result['status'] = clf['status']

        else:
            if not args.run_approved:
                raise RuntimeError('Real wine execution blocked: requires explicit --run-approved flag from Lead')

            runtime_bin = diag_base.base_s3v2.verify_chosen_runtime(args.role)

            setup_real_sysroot_sort(root)

            server_cmd = diag_base.build_wineserver_command_r3(runtime_bin, root)
            wine_cmd = diag_base.build_wine_pe_command_r3(runtime_bin, root)
            result['commands']['wineserver'] = server_cmd
            result['commands']['wine_pe'] = wine_cmd

            server_proc = subprocess.Popen(server_cmd)

            deadline = time.monotonic() + 5.0
            probe_res = {'status': 'WAITING', 'error': 'not_started'}
            while time.monotonic() < deadline:
                if server_proc.poll() is not None:
                    break
                probe_res = diag_base.base_s3v2.base.probe_readiness(runtime_bin, root, prefix, fake_mode=False)
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
            stderr_monitor = diag_base.StderrCapMonitor(runner_stderr, soft_threshold_bytes=diag_base.STDERR_SOFT_THRESHOLD_BYTES)
            stderr_monitor.start(wine_proc)

            result['wine_exit'] = wine_proc.wait(timeout=60.0)
            stderr_monitor.stop()

            result['stderr_cap']['observed_bytes'] = stderr_monitor.observed_bytes
            result['stderr_cap']['exceeded'] = stderr_monitor.exceeded

            if stderr_monitor.exceeded:
                result['error'] = f'STDERR_SOFT_THRESHOLD_EXCEEDED: size {stderr_monitor.observed_bytes} > {diag_base.STDERR_SOFT_THRESHOLD_BYTES}'
                result['status'] = 'UNKNOWN'
                result['r3_classification'] = {'status': 'UNKNOWN', 'reason': 'stderr soft threshold exceeded'}
            else:
                clf = diag_base.classify_r3_wine_outcome(result['wine_exit'])
                result['r3_classification'] = clf
                result['status'] = clf['status']

    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        try:
            if stderr_monitor: stderr_monitor.stop()
        except Exception: pass

        try:
            if wine_proc and wine_proc.poll() is None:
                wine_proc.terminate()
                wine_proc.wait(timeout=3.0)
        except Exception: pass

        try:
            if server_proc and server_proc.poll() is None:
                server_proc.terminate()
                server_proc.wait(timeout=3.0)
                result['wineserver_exit'] = server_proc.returncode
        except Exception: pass

        try:
            if runner_stderr.exists():
                stderr_content = diag_base.read_capped_stderr(runner_stderr, max_read_bytes=diag_base.STDERR_SOFT_THRESHOLD_BYTES)
                result['diag_parsed_findings'] = diag_base.parse_diagnostics_from_stderr(stderr_content)
                sz = runner_stderr.stat().st_size
                result['stderr_cap']['observed_bytes'] = sz
                result['stderr_cap']['exceeded'] = sz > diag_base.STDERR_SOFT_THRESHOLD_BYTES
        except Exception: pass

        try:
            (work / 'wine-launcher-result.json').write_text(json.dumps(result, indent=2))
        except Exception: pass

    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__':
    sys.exit(main())
