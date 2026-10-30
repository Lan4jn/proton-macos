"""Stage 3 Wine launcher: minimal adapter extending frozen 32ec with 21.6MB closure, dual RT support, and 60s budget."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[3]

FROZEN_BASE_LAUNCHER = LAB / 'scripts/runtime/session_v2_round2/wine_launcher.py'
FROZEN_BASE_SHA = '32ec7513c58b76ab4ae41d10403d3ca658ec4ed9c841ab82e3c4228079c41b18'

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

if sha256_file(FROZEN_BASE_LAUNCHER) != FROZEN_BASE_SHA:
    raise SystemExit('Frozen base wine_launcher.py SHA mismatch')

spec = importlib.util.spec_from_file_location('frozen_base', FROZEN_BASE_LAUNCHER)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

CLOSURE_MANIFEST_PATH = LAB / 'sources/p0-session-round2/stage3/CLOSURE_MANIFEST.json'
CLOSURE = json.loads(CLOSURE_MANIFEST_PATH.read_text())

def resolve_repo_path(p_str):
    p = Path(p_str)
    if not p.is_absolute():
        p = LAB / p
    return p.resolve()

def validate_closure_sources():
    # 1. Target PE
    pe_p = resolve_repo_path(CLOSURE['target_pe']['path'])
    if not pe_p.is_file() or sha256_file(pe_p) != CLOSURE['target_pe']['sha256']:
        raise FileNotFoundError(f"Missing or invalid target PE source: {pe_p}")

    # 2. Wineboot
    wb_p = resolve_repo_path(CLOSURE['wineboot_exe']['path'])
    if not wb_p.is_file() or sha256_file(wb_p) != CLOSURE['wineboot_exe']['sha256']:
        raise FileNotFoundError(f"Missing or invalid wineboot source: {wb_p}")

    # 3. DLLs
    for dll_name, info in CLOSURE['dlls'].items():
        dll_p = resolve_repo_path(info['source'])
        if not dll_p.is_file() or sha256_file(dll_p) != info['sha256']:
            raise FileNotFoundError(f"Missing or invalid closure DLL source: {dll_p}")

    # 4. NLS
    for nls_name, info in CLOSURE['nls'].items():
        nls_p = resolve_repo_path(info['source'])
        if not nls_p.is_file() or sha256_file(nls_p) != info['sha256']:
            raise FileNotFoundError(f"Missing or invalid closure NLS source: {nls_p}")

def verify_chosen_runtime(role):
    rt_key = 'runtime_original' if role == 'original' else 'runtime_derived'
    rt_info = base.WHITELIST[rt_key]
    rt_p = Path(rt_info['path'])
    if not rt_p.is_file():
        raise FileNotFoundError(f"Chosen runtime binary missing: {rt_p}")
    h = sha256_file(rt_p)
    if h != rt_info['sha256']:
        raise ValueError(f"Chosen runtime SHA mismatch for {role}: expected {rt_info['sha256']}, got {h}")
    return rt_p

def build_wineserver_command_stage3(runtime_path, sysroot_dir):
    user_spec = f"{os.getuid()}:{os.getgid()}"
    return [
        str(runtime_path),
        '--user', user_spec,
        '--sysroot', str(sysroot_dir),
        '--timeout', '60',  # Approved Stage 3 budget
        '--workdir', '/tmp',
        '--clear-env',
        '--env', 'WINEPREFIX=/prefix',
        '--env', 'HOME=/home',
        '--env', 'TMPDIR=/tmp',
        '--env', 'LD_LIBRARY_PATH=/lib:/usr/lib:/wine/lib/wine/aarch64-unix',
        '--env', 'WINESERVER=/bin/wineserver_shim',
        '--env', 'WINEESYNC=0',
        '--env', 'WINEFSYNC=0',
        '--env', 'PROTON_NO_ESYNC=1',
        '--env', 'PROTON_NO_FSYNC=1',
        '--env', 'PROTON_NO_NTSYNC=1',
        '/wine/bin-arm64/wineserver',
        '-f',
    ]

def build_wine_pe_command_stage3(runtime_path, sysroot_dir):
    user_spec = f"{os.getuid()}:{os.getgid()}"
    return [
        str(runtime_path),
        '--user', user_spec,
        '--sysroot', str(sysroot_dir),
        '--timeout', '60',  # Approved Stage 3 budget
        '--workdir', '/work',
        '--clear-env',
        '--env', 'WINEPREFIX=/prefix',
        '--env', 'HOME=/home',
        '--env', 'TMPDIR=/tmp',
        '--env', 'LD_LIBRARY_PATH=/lib:/usr/lib:/wine/lib/wine/aarch64-unix',
        '--env', 'WINEDLLPATH=/wine/lib/wine/aarch64-unix',
        '--env', 'WINESERVER=/bin/wineserver_shim',
        '--env', 'WINEESYNC=0',
        '--env', 'WINEFSYNC=0',
        '--env', 'PROTON_NO_ESYNC=1',
        '--env', 'PROTON_NO_FSYNC=1',
        '--env', 'PROTON_NO_NTSYNC=1',
        '/wine/bin-arm64/wine',
        '/prefix/drive_c/minimal-x64.exe',
    ]

def setup_real_sysroot_stage3(target_root):
    validate_closure_sources()
    root_manifest = base.setup_real_sysroot(target_root)
    root_manifest['stage3_closure_deployed'] = {}

    bundle_win_dst = target_root / 'wine/lib/wine/aarch64-windows'
    bundle_win_dst.mkdir(parents=True, exist_ok=True)
    bundle_nls_dst = target_root / 'wine/share/wine/nls'
    bundle_nls_dst.mkdir(parents=True, exist_ok=True)
    sys32_dst = target_root / 'prefix/drive_c/windows/system32'
    sys32_dst.mkdir(parents=True, exist_ok=True)

    # 1. Deploy Wineboot
    wb_src = resolve_repo_path(CLOSURE['wineboot_exe']['path'])
    base.clone_or_copy(wb_src, bundle_win_dst / 'wineboot.exe')
    dst_wb_sys32 = sys32_dst / 'wineboot.exe'
    if dst_wb_sys32.is_symlink() or dst_wb_sys32.exists(): dst_wb_sys32.unlink()
    base.clone_or_copy(wb_src, dst_wb_sys32)
    wb_sha = sha256_file(dst_wb_sys32)
    root_manifest['stage3_closure_deployed']['wineboot.exe'] = {
        'target': 'prefix/drive_c/windows/system32/wineboot.exe',
        'sha256': wb_sha,
        'inode': dst_wb_sys32.stat().st_ino,
    }

    # 2. Deploy 10 DLLs in closure
    for dll_name, info in CLOSURE['dlls'].items():
        src_p = resolve_repo_path(info['source'])
        base.clone_or_copy(src_p, bundle_win_dst / dll_name)
        dst_dll_sys32 = sys32_dst / dll_name
        if dst_dll_sys32.is_symlink() or dst_dll_sys32.exists(): dst_dll_sys32.unlink()
        base.clone_or_copy(src_p, dst_dll_sys32)
        d_sha = sha256_file(dst_dll_sys32)
        root_manifest['stage3_closure_deployed'][dll_name] = {
            'target': f"prefix/drive_c/windows/system32/{dll_name}",
            'sha256': d_sha,
            'inode': dst_dll_sys32.stat().st_ino,
        }

    # 3. Deploy NLS tables
    for nls_name, info in CLOSURE['nls'].items():
        src_p = resolve_repo_path(info['source'])
        dst_nls = bundle_nls_dst / nls_name
        base.clone_or_copy(src_p, dst_nls)
        n_sha = sha256_file(dst_nls)
        root_manifest['stage3_closure_deployed'][nls_name] = {
            'target': f"wine/share/wine/nls/{nls_name}",
            'sha256': n_sha,
            'inode': dst_nls.stat().st_ino,
        }

    (target_root / 'root_manifest.json').write_text(json.dumps(root_manifest, indent=2))
    return root_manifest

def classify_stage3_wine_outcome(wine_exit):
    if wine_exit == 43:
        return {'status': 'PASS', 'semantic_marker': 'REACHED_PE_ENTRY_NT_TERMINATE_43'}
    elif wine_exit == 29:
        return {'status': 'UNKNOWN', 'semantic_marker': 'LOADER_FAILURE_EXIT_29', 'reason': 'Wine loader failed; entry unreached'}
    else:
        return {'status': 'UNKNOWN', 'semantic_marker': f'UNEXPECTED_EXIT_{wine_exit}', 'reason': 'Unverified exit code'}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--role', choices=['fake', 'original', 'derived'], default='fake')
    ap.add_argument('--run-approved', action='store_true')
    ap.add_argument('--fail-probe', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)

    # Enforce P0 samegroup identity check in real mode BEFORE any directory creation
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
        'stage3_classification': None,
        'commands': {},
        'error': None,
    }

    server_proc = None
    wine_proc = None

    try:
        base.verify_whitelist()
        validate_closure_sources()

        if args.role == 'fake':
            if not prefix.exists():
                base.copy_and_materialize_prefix(base.TEMPLATE_PFX, prefix, work)

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

            result['commands']['wineserver'] = build_wineserver_command_stage3(base.WHITELIST['runtime_original']['path'], root)
            result['commands']['wine_pe'] = build_wine_pe_command_stage3(base.WHITELIST['runtime_original']['path'], root)

            deadline = time.monotonic() + 1.0 if args.fail_probe else time.monotonic() + 5.0
            probe_res = {'status': 'WAITING', 'error': 'not_started'}
            while time.monotonic() < deadline:
                probe_res = base.probe_readiness(None, root, prefix, fake_mode=True)
                if probe_res.get('status') == 'READY':
                    result['server_ready'] = True
                    result['readiness_evidence'] = probe_res
                    break
                time.sleep(0.05)

            result['readiness_evidence'] = probe_res
            if not result['server_ready']:
                result['error'] = 'SERVER_NOT_READY'
                raise RuntimeError('SERVER_NOT_READY: probe connection unestablished')

            wine_cmd = [sys.executable, '-I', '-c', 'import sys; sys.exit(43)']
            wine_proc = subprocess.Popen(wine_cmd)
            result['wine_exit'] = wine_proc.wait(timeout=60.0)
            clf = classify_stage3_wine_outcome(result['wine_exit'])
            result['stage3_classification'] = clf
            result['status'] = clf['status']

        else:
            if not args.run_approved:
                raise RuntimeError('Real wine execution blocked: requires explicit --run-approved flag from Lead')

            runtime_bin = verify_chosen_runtime(args.role)

            setup_real_sysroot_stage3(root)

            server_cmd = build_wineserver_command_stage3(runtime_bin, root)
            wine_cmd = build_wine_pe_command_stage3(runtime_bin, root)
            result['commands']['wineserver'] = server_cmd
            result['commands']['wine_pe'] = wine_cmd

            server_proc = subprocess.Popen(server_cmd)

            deadline = time.monotonic() + 5.0
            probe_res = {'status': 'WAITING', 'error': 'not_started'}
            while time.monotonic() < deadline:
                if server_proc.poll() is not None:
                    break
                probe_res = base.probe_readiness(runtime_bin, root, prefix, fake_mode=False)
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
            result['wine_exit'] = wine_proc.wait(timeout=60.0)  # Stage 3 Python wait 60s
            clf = classify_stage3_wine_outcome(result['wine_exit'])
            result['stage3_classification'] = clf
            result['status'] = clf['status']

    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        if wine_proc and wine_proc.poll() is None:
            wine_proc.terminate()
            wine_proc.wait(timeout=3.0)
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=3.0)
            result['wineserver_exit'] = server_proc.returncode
        (work / 'wine-launcher-result.json').write_text(json.dumps(result, indent=2))

    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__':
    sys.exit(main())
