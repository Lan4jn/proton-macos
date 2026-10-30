"""Wine initialization combined bootstrap launcher (Round 3 full closure: 18 sort-base + 3 FEX Unix libs + 6 PE DLLs):
Imports frozen wine_diagnostics_launcher_v2_sort.py (2e0319), binds CLOSURE_MANIFEST_R3_COMBINED.json,
materializes 18 sort files + 3 FEX Unix libraries in usr/lib + 6 PE DLLs in system32,
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

FROZEN_SORT_LAUNCHER = LAB / 'scripts/runtime/wine_init_round3/wine_diagnostics_launcher_v2_sort.py'
FROZEN_SORT_SHA = '2e03197ecb02c5fd7321b8b54685078d8268a4ac2707ac927ccca63c04ee7732'

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

if sha256_file(FROZEN_SORT_LAUNCHER) != FROZEN_SORT_SHA:
    raise SystemExit('Frozen wine_diagnostics_launcher_v2_sort.py SHA mismatch')

spec = importlib.util.spec_from_file_location('sort_base', FROZEN_SORT_LAUNCHER)
sort_base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sort_base)

CLOSURE_MANIFEST_PATH = LAB / 'sources/wine-init-round3/CLOSURE_MANIFEST_R3_COMBINED.json'
CLOSURE_R3_COMBINED = json.loads(CLOSURE_MANIFEST_PATH.read_text())

PE_6_NAMES = ["shell32.dll", "user32.dll", "gdi32.dll", "win32u.dll", "shcore.dll", "shlwapi.dll"]

def resolve_repo_path(p_str):
    p = Path(p_str)
    if not p.is_absolute():
        p = LAB / p
    return p.resolve()

def validate_closure_sources_combined():
    # 1. Validate sort base (18 files)
    sort_base.validate_closure_sources_sort()

    # 2. Validate 3 Unix libs
    for lib_name, info in CLOSURE_R3_COMBINED['unix_libs'].items():
        src_p = resolve_repo_path(info['source'])
        if not src_p.is_file():
            raise FileNotFoundError(f"Missing Unix lib source: {src_p}")
        h = sha256_file(src_p)
        if h != info['sha256']:
            raise ValueError(f"Unix lib SHA mismatch for {lib_name}: expected {info['sha256']}, got {h}")

    # 3. Validate 6 new PE DLLs
    for pe_name in PE_6_NAMES:
        info = CLOSURE_R3_COMBINED['dlls'][pe_name]
        src_p = resolve_repo_path(info['source'])
        if not src_p.is_file():
            raise FileNotFoundError(f"Missing PE DLL source: {src_p}")
        h = sha256_file(src_p)
        if h != info['sha256']:
            raise ValueError(f"PE DLL SHA mismatch for {pe_name}: expected {info['sha256']}, got {h}")

def setup_real_sysroot_combined(target_root):
    validate_closure_sources_combined()
    # 1. Call sort base setup to materialize 18 base files (including sortdefault in bundle and prefix)
    root_manifest = sort_base.setup_real_sysroot_sort(target_root)
    root_manifest['r3_combined_deployed'] = {
        'unix_libs': {},
        'pe_6_dlls': {}
    }

    # 2. Materialize 3 Unix libraries in usr/lib
    usr_lib_dst = target_root / 'usr/lib'
    usr_lib_dst.mkdir(parents=True, exist_ok=True)
    for lib_name, info in CLOSURE_R3_COMBINED['unix_libs'].items():
        src_p = resolve_repo_path(info['source'])
        dst_p = target_root / info['target']
        sort_base.diag_base.base_s3v2.base.clone_or_copy(src_p, dst_p)
        h = sha256_file(dst_p)
        if h != info['sha256']:
            raise ValueError(f"Deployed Unix lib SHA mismatch for {lib_name}")
        entry = {
            'target': info['target'],
            'sha256': h,
            'bytes': dst_p.stat().st_size,
            'inode': dst_p.stat().st_ino
        }
        if 'target_soname' in info:
            dst_soname = target_root / info['target_soname']
            sort_base.diag_base.base_s3v2.base.clone_or_copy(src_p, dst_soname)
            entry['target_soname'] = info['target_soname']
        root_manifest['r3_combined_deployed']['unix_libs'][lib_name] = entry

    # 3. Materialize 6 PE DLLs in bundle aarch64-windows and prefix system32
    bundle_win_dst = target_root / 'wine/lib/wine/aarch64-windows'
    bundle_win_dst.mkdir(parents=True, exist_ok=True)
    sys32_dst = target_root / 'prefix/drive_c/windows/system32'
    sys32_dst.mkdir(parents=True, exist_ok=True)

    for pe_name in PE_6_NAMES:
        info = CLOSURE_R3_COMBINED['dlls'][pe_name]
        src_p = resolve_repo_path(info['source'])
        dst_bundle = bundle_win_dst / pe_name
        sort_base.diag_base.base_s3v2.base.clone_or_copy(src_p, dst_bundle)

        dst_sys32 = sys32_dst / pe_name
        if dst_sys32.is_symlink() or dst_sys32.exists():
            dst_sys32.unlink()
        sort_base.diag_base.base_s3v2.base.clone_or_copy(src_p, dst_sys32)
        h = sha256_file(dst_sys32)
        if h != info['sha256']:
            raise ValueError(f"Deployed PE DLL SHA mismatch for {pe_name}")

        root_manifest['r3_combined_deployed']['pe_6_dlls'][pe_name] = {
            'target': f"prefix/drive_c/windows/system32/{pe_name}",
            'sha256': h,
            'bytes': dst_sys32.stat().st_size,
            'inode': dst_sys32.stat().st_ino
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
            'soft_threshold_bytes': sort_base.diag_base.STDERR_SOFT_THRESHOLD_BYTES,
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
        sort_base.diag_base.base_s3v2.base.verify_whitelist()
        validate_closure_sources_combined()

        if args.role == 'fake':
            if not prefix.exists():
                sort_base.diag_base.base_s3v2.base.copy_and_materialize_prefix(sort_base.diag_base.base_s3v2.base.TEMPLATE_PFX, prefix, work)

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

            result['commands']['wineserver'] = sort_base.diag_base.build_wineserver_command_r3(sort_base.diag_base.base_s3v2.base.WHITELIST['runtime_original']['path'], root)
            result['commands']['wine_pe'] = sort_base.diag_base.build_wine_pe_command_r3(sort_base.diag_base.base_s3v2.base.WHITELIST['runtime_original']['path'], root)

            deadline = time.monotonic() + 1.0 if args.fail_probe else time.monotonic() + 5.0
            probe_res = {'status': 'WAITING', 'error': 'not_started'}
            while time.monotonic() < deadline:
                probe_res = sort_base.diag_base.base_s3v2.base.probe_readiness(None, root, prefix, fake_mode=True)
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
            clf = sort_base.diag_base.classify_r3_wine_outcome(result['wine_exit'])
            result['r3_classification'] = clf
            result['status'] = clf['status']

        else:
            if not args.run_approved:
                raise RuntimeError('Real wine execution blocked: requires explicit --run-approved flag from Lead')

            runtime_bin = sort_base.diag_base.base_s3v2.verify_chosen_runtime(args.role)

            setup_real_sysroot_combined(root)

            server_cmd = sort_base.diag_base.build_wineserver_command_r3(runtime_bin, root)
            wine_cmd = sort_base.diag_base.build_wine_pe_command_r3(runtime_bin, root)
            result['commands']['wineserver'] = server_cmd
            result['commands']['wine_pe'] = wine_cmd

            server_proc = subprocess.Popen(server_cmd)

            deadline = time.monotonic() + 5.0
            probe_res = {'status': 'WAITING', 'error': 'not_started'}
            while time.monotonic() < deadline:
                if server_proc.poll() is not None:
                    break
                probe_res = sort_base.diag_base.base_s3v2.base.probe_readiness(runtime_bin, root, prefix, fake_mode=False)
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
            stderr_monitor = sort_base.diag_base.StderrCapMonitor(runner_stderr, soft_threshold_bytes=sort_base.diag_base.STDERR_SOFT_THRESHOLD_BYTES)
            stderr_monitor.start(wine_proc)

            result['wine_exit'] = wine_proc.wait(timeout=60.0)
            stderr_monitor.stop()

            result['stderr_cap']['observed_bytes'] = stderr_monitor.observed_bytes
            result['stderr_cap']['exceeded'] = stderr_monitor.exceeded

            if stderr_monitor.exceeded:
                result['error'] = f'STDERR_SOFT_THRESHOLD_EXCEEDED: size {stderr_monitor.observed_bytes} > {sort_base.diag_base.STDERR_SOFT_THRESHOLD_BYTES}'
                result['status'] = 'UNKNOWN'
                result['r3_classification'] = {'status': 'UNKNOWN', 'reason': 'stderr soft threshold exceeded'}
            else:
                clf = sort_base.diag_base.classify_r3_wine_outcome(result['wine_exit'])
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
                stderr_content = sort_base.diag_base.read_capped_stderr(runner_stderr, max_read_bytes=sort_base.diag_base.STDERR_SOFT_THRESHOLD_BYTES)
                result['diag_parsed_findings'] = sort_base.diag_base.parse_diagnostics_from_stderr(stderr_content)
                sz = runner_stderr.stat().st_size
                result['stderr_cap']['observed_bytes'] = sz
                result['stderr_cap']['exceeded'] = sz > sort_base.diag_base.STDERR_SOFT_THRESHOLD_BYTES
        except Exception: pass

        try:
            (work / 'wine-launcher-result.json').write_text(json.dumps(result, indent=2))
        except Exception: pass

    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__':
    sys.exit(main())
