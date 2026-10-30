"""Wine launcher: strict whitelist, prefix isolation, readiness probe, and foreground two-stage execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[2]

sys.path.insert(0, str(HERE))
from wine_adapter import copy_and_materialize_prefix

WHITELIST = {
    'runtime_original': {
        'path': LAB / 'sources/elfuse-once-panorama2-derived/build/elfuse',
        'sha256': '8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda',
    },
    'runtime_derived': {
        'path': LAB / 'sources/elfuse-inproc-present-derived/build/elfuse',
        'sha256': '3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926',
    },
    'wine': {
        'path': LAB / 'sources/proton-v3-deploy/original/files/bin-arm64/wine',
        'sha256': '0eb603be3624255de6d13740b73c4c5bbb9ee5c1f5f9120abdb3ebc408dab91b',
    },
    'wineserver': {
        'path': LAB / 'sources/proton-v3-deploy/original/files/bin-arm64/wineserver',
        'sha256': 'dc6b16a7428df4beca04620839fc13e231a529270bd40b43c3ae3dd2d990995c',
    },
    'ntdll_unix': {
        'path': LAB / 'sources/proton-v3-deploy/original/files/lib/wine/aarch64-unix/ntdll.so',
        'sha256': 'd2d734b53183750f27bd0c7a4093b6665fc94947a38d1bc444411fe6c85fc296',
    },
    'wineserver_shim': {
        'path': LAB / 'sources/p0-session-round2/wineserver_shim',
        'sha256': 'ebc8d4d91dbf3249e91d581d4a3b3086c28ea1e8968b75c73f4f043cbfef8d21',
    },
    'wine_readiness_probe': {
        'path': LAB / 'sources/p0-session-round2/wine_readiness_probe',
        'sha256': '1fc0cf08dc85eacd1289d1a0ebfb6f7c2449b6d019ddb9def875a606bdb5e051',
    },
    'minimal_x64': {
        'path': LAB / 'fixtures/runtime/pe-worker/pfx/drive_c/minimal-x64.exe',
        'sha256': '87406032e5b7c6546afe5fa0f03847a5e398cb4981c969604417a828ab266bc8',
    },
}

CORE_DLLS = [
    'kernel32.dll',
    'kernelbase.dll',
    'libarm64ecfex.dll',
    'ntdll.dll',
]

TEMPLATE_PFX = LAB / 'fixtures/runtime/pe-worker/pfx'
ARCH_ROOT = LAB / 'fixtures/runtime/arch-root'
PROTON_BUNDLE = LAB / 'sources/proton-v3-deploy/original/files'
PROTON_DERIVED = LAB / 'fixtures/runtime/proton-derived/files'

REQUIRED_ARCH_LIBS = [
    'usr/lib/ld-linux-aarch64.so.1',
    'usr/lib/libc.so.6',
]

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def verify_whitelist():
    for name, item in WHITELIST.items():
        p = Path(item['path'])
        if not p.is_file():
            raise FileNotFoundError(f"Whitelist item missing: {name} at {p}")
        h = sha256_file(p)
        if h != item['sha256']:
            raise ValueError(f"Whitelist SHA mismatch for {name}: expected {item['sha256']}, got {h}")

def parse_elf_deps(path):
    data = Path(path).read_bytes()
    if data[:4] != b"\x7fELF": return None
    is_64 = data[4] == 2
    e_phoff = struct.unpack_from("<Q" if is_64 else "<I", data, 32 if is_64 else 28)[0]
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 54 if is_64 else 44)
    pt_interp = None
    dynamic_offset = None
    dynamic_filesz = None
    load_segments = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        if is_64:
            p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from("<IIQQQQQQ", data, off)
        else:
            p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from("<IIIIIIII", data, off)
        if p_type == 1: load_segments.append((p_vaddr, p_filesz, p_offset))
        elif p_type == 2: dynamic_offset, dynamic_filesz = p_offset, p_filesz
        elif p_type == 3: pt_interp = data[p_offset:p_offset+p_filesz].rstrip(b"\x00").decode("ascii")

    def vaddr_to_offset(vaddr):
        for lv, sz, off in load_segments:
            if lv <= vaddr < lv + sz: return off + (vaddr - lv)
        return vaddr

    needed = []
    if dynamic_offset:
        ent_sz = 16 if is_64 else 8
        count = dynamic_filesz // ent_sz
        tags = []
        strtab_vaddr = None
        for i in range(count):
            if is_64: tag, val = struct.unpack_from("<Qq", data, dynamic_offset + i * ent_sz)
            else: tag, val = struct.unpack_from("<Ii", data, dynamic_offset + i * ent_sz)
            tags.append((tag, val))
            if tag == 5: strtab_vaddr = val
        if strtab_vaddr:
            strtab_off = vaddr_to_offset(strtab_vaddr)
            for tag, val in tags:
                if tag == 1:
                    needed.append(data[strtab_off + val:].split(b"\x00", 1)[0].decode("ascii"))
    return {"pt_interp": pt_interp, "dt_needed": needed}

def clone_or_copy(src_path, dst_path):
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    method = 'ditto_clone'
    ret = subprocess.run(['ditto', '--clone', str(src_path), str(dst_path)], capture_output=True)
    if ret.returncode != 0:
        method = 'shutil_copy'
        if src_path.is_dir():
            shutil.copytree(src_path, dst_path, symlinks=True)
        else:
            shutil.copyfile(src_path, dst_path)
    return method

def build_wineserver_command(runtime_path, sysroot_dir):
    cmd = [
        str(runtime_path),
        '--sysroot', str(sysroot_dir),
        '--timeout', '20',
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
    return cmd

def build_wine_pe_command(runtime_path, sysroot_dir):
    cmd = [
        str(runtime_path),
        '--sysroot', str(sysroot_dir),
        '--timeout', '20',
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
    return cmd

def probe_readiness(runtime_path, sysroot_dir, prefix_dir, fake_mode=False):
    if fake_mode:
        st = prefix_dir.stat()
        uid = os.getuid()
        sock_path = prefix_dir.parent / 'tmp' / f".wine-{uid}" / f"server-{st.st_dev:x}-{st.st_ino:x}" / "socket"
        if not sock_path.is_socket():
            return {'status': 'WAITING', 'error': 'socket_absent', 'socket_path': str(sock_path)}
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(str(sock_path))
            s.close()
            return {'status': 'READY', 'uid': uid, 'dev': f"{st.st_dev:x}", 'ino': f"{st.st_ino:x}", 'socket_path': str(sock_path)}
        except Exception as exc:
            s.close()
            return {'status': 'WAITING', 'error': 'connect_failed', 'errno': str(exc)}
    else:
        probe_cmd = [
            str(runtime_path),
            '--sysroot', str(sysroot_dir),
            '--timeout', '5',
            '--workdir', '/tmp',
            '--clear-env',
            '/bin/wine_readiness_probe',
            '/prefix',
        ]
        p = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=8)
        for line in p.stdout.splitlines():
            try:
                res = json.loads(line)
                if isinstance(res, dict) and 'status' in res:
                    return res
            except ValueError:
                continue
        return {'status': 'FAIL', 'error': 'probe_output_invalid', 'raw': p.stdout + p.stderr}

def setup_real_sysroot(target_root):
    (target_root / 'tmp').mkdir(parents=True, exist_ok=True)
    (target_root / 'work').mkdir(parents=True, exist_ok=True)
    (target_root / 'home').mkdir(parents=True, exist_ok=True)
    (target_root / 'bin').mkdir(parents=True, exist_ok=True)
    (target_root / 'usr/lib').mkdir(parents=True, exist_ok=True)

    root_manifest = {
        'items': {},
        'external_links_audit': {},
        'core_dlls_materialized': {},
        'pe_installed': {},
        'all_symlinks_audit': {},
        'elf_dependencies_verified': {},
    }

    # Verify actual ELF dependencies on host files before setup
    for name in ('wine', 'wineserver', 'ntdll_unix'):
        elf_p = WHITELIST[name]['path']
        root_manifest['elf_dependencies_verified'][name] = parse_elf_deps(elf_p)

    # 1. Install probe and shim
    m1 = clone_or_copy(WHITELIST['wine_readiness_probe']['path'], target_root / 'bin/wine_readiness_probe')
    (target_root / 'bin/wine_readiness_probe').chmod(0o755)
    root_manifest['items']['bin/wine_readiness_probe'] = {
        'method': m1,
        'sha256': sha256_file(target_root / 'bin/wine_readiness_probe'),
        'inode': (target_root / 'bin/wine_readiness_probe').stat().st_ino,
    }

    m2 = clone_or_copy(WHITELIST['wineserver_shim']['path'], target_root / 'bin/wineserver_shim')
    (target_root / 'bin/wineserver_shim').chmod(0o755)
    root_manifest['items']['bin/wineserver_shim'] = {
        'method': m2,
        'sha256': sha256_file(target_root / 'bin/wineserver_shim'),
        'inode': (target_root / 'bin/wineserver_shim').stat().st_ino,
    }

    # 2. Strict copy of required dynamic libraries
    for rel_path in REQUIRED_ARCH_LIBS:
        src_f = ARCH_ROOT / rel_path
        dst_f = target_root / rel_path
        meth = clone_or_copy(src_f, dst_f)
        root_manifest['items'][rel_path] = {
            'method': meth,
            'sha256': sha256_file(dst_f),
            'inode': dst_f.stat().st_ino,
        }

    # /lib -> usr/lib relative symlink within target_root itself
    lib_link = target_root / 'lib'
    if not lib_link.exists():
        os.symlink('usr/lib', lib_link)

    # 3. Clone Proton wine bundle and audit/handle the 11 external symlinks inside it
    wine_mount = target_root / 'wine'
    if not wine_mount.exists():
        m_bundle = clone_or_copy(PROTON_BUNDLE, wine_mount)
        root_manifest['items']['wine'] = {'method': m_bundle}

    # Audit and process external symlinks inside target_root/wine
    for root_dir, dirs, files in os.walk(wine_mount):
        for name in list(dirs) + list(files):
            p = Path(root_dir) / name
            if p.is_symlink():
                target = os.readlink(p)
                if 'proton-derived' in target or target.startswith('/'):
                    rel_to_bundle = str(p.relative_to(wine_mount))
                    resolved_src = p.resolve(strict=True)
                    p.unlink()
                    if rel_to_bundle == 'lib/wine/aarch64-windows':
                        # Materialize ONLY the required 4 core DLLs into local directory
                        p.mkdir(parents=True, exist_ok=True)
                        for dll_name in CORE_DLLS:
                            src_dll = resolved_src / dll_name
                            dst_dll = p / dll_name
                            clone_or_copy(src_dll, dst_dll)
                        root_manifest['external_links_audit'][rel_to_bundle] = {
                            'literal_target': target,
                            'treatment': 'materialized_subset',
                            'omitted_others': 'only_4_core_dlls_materialized',
                            'source_dir': str(resolved_src),
                        }
                    elif rel_to_bundle == 'bin':
                        # Copy bin-arm64 contents directly to bin
                        p.mkdir(parents=True, exist_ok=True)
                        for b in (wine_mount / 'bin-arm64').iterdir():
                            clone_or_copy(b, p / b.name)
                        root_manifest['external_links_audit'][rel_to_bundle] = {
                            'literal_target': target,
                            'treatment': 'materialized_from_local_bin_arm64',
                            'source_dir': str(wine_mount / 'bin-arm64'),
                        }
                    else:
                        # Non-essential external dirs omitted as isolated empty directory
                        if resolved_src.is_dir():
                            p.mkdir(parents=True, exist_ok=True)
                        else:
                            p.write_bytes(b'')
                        root_manifest['external_links_audit'][rel_to_bundle] = {
                            'literal_target': target,
                            'treatment': 'omitted_empty',
                            'source_dir': str(resolved_src),
                        }

    # 4. Copy prefix and explicitly extract 4 core DLLs strictly from local target_root/wine
    prefix_dir = target_root / 'prefix'
    local_core_source = target_root / 'wine/lib/wine/aarch64-windows'
    if not prefix_dir.exists():
        # Pass core_source_root directly so copier never touches outside repository
        copy_and_materialize_prefix(TEMPLATE_PFX, prefix_dir, target_root / 'work', core_source_root=local_core_source)
        for dll_name in CORE_DLLS:
            dst_dll = prefix_dir / 'drive_c/windows/system32' / dll_name
            root_manifest['core_dlls_materialized'][dll_name] = {
                'source': f"wine/lib/wine/aarch64-windows/{dll_name}",
                'sha256': sha256_file(dst_dll),
                'inode': dst_dll.stat().st_ino,
            }

    # 5. Explicitly install minimal-x64.exe and verify SHA256
    installed_pe = prefix_dir / 'drive_c/minimal-x64.exe'
    if installed_pe.exists() or installed_pe.is_symlink():
        installed_pe.unlink()
    clone_or_copy(WHITELIST['minimal_x64']['path'], installed_pe)
    pe_sha = sha256_file(installed_pe)
    if pe_sha != WHITELIST['minimal_x64']['sha256']:
        raise ValueError(f"Installed PE SHA mismatch: expected {WHITELIST['minimal_x64']['sha256']}, got {pe_sha}")
    root_manifest['pe_installed'] = {
        'path': 'prefix/drive_c/minimal-x64.exe',
        'sha256': pe_sha,
        'inode': installed_pe.stat().st_ino,
    }

    # 6. Audit ALL symlinks inside target_root with strict multi-dimensional perspective
    host_prefix_patterns = ('/Users/', '/Volumes/', '/private/')
    for root_dir, dirs, files in os.walk(target_root):
        for name in list(dirs) + list(files):
            p = Path(root_dir) / name
            if p.is_symlink():
                target_str = os.readlink(p)
                rel_path = str(p.relative_to(target_root))

                # Hard rejection of any lingering host-absolute paths that escape target_root
                if any(target_str.startswith(pat) for pat in host_prefix_patterns):
                    raise RuntimeError(f"Unsafe host escape symlink detected at {rel_path}: {target_str}")

                if target_str.startswith('/'):
                    context = 'guest_sysroot'
                    guest_target = target_root / target_str.lstrip('/')
                    exists = guest_target.exists()
                    actual_resolved = str(guest_target)
                    classification = 'guest_internal_link' if exists else 'broken_retained'
                else:
                    context = 'relative'
                    rel_target = (p.parent / target_str)
                    exists = rel_target.exists()
                    actual_resolved = str(rel_target)
                    classification = 'valid_relative' if exists else 'broken_retained'

                root_manifest['all_symlinks_audit'][rel_path] = {
                    'literal_target': target_str,
                    'resolution_context': context,
                    'actual_resolved': actual_resolved,
                    'exists': exists,
                    'classification': classification,
                }

    (target_root / 'root_manifest.json').write_text(json.dumps(root_manifest, indent=2))
    return root_manifest

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--role', choices=['fake', 'original'], default='fake')
    ap.add_argument('--run-approved', action='store_true', help='Explicit Lead approval flag for real wine run')
    ap.add_argument('--fail-probe', action='store_true', help='Force readiness failure for negative testing')
    args = ap.parse_args()

    root = Path(args.root)

    # Enforce P0 samegroup identity check in real mode BEFORE any directory creation
    if args.role != 'fake':
        # 1. 严格复用 A 组逻辑强校验必须运行于 P0 监督进程组中
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

        # 2. 校验 root 必须位于 run_parent 专属子目录内部，杜绝覆盖 run_parent 本身
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
        'commands': {},
        'error': None,
    }

    server_proc = None
    wine_proc = None

    try:
        verify_whitelist()

        if args.role == 'fake':
            if not prefix.exists():
                copy_and_materialize_prefix(TEMPLATE_PFX, prefix, work)

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

            result['commands']['wineserver'] = build_wineserver_command(WHITELIST['runtime_original']['path'], root)
            result['commands']['wine_pe'] = build_wine_pe_command(WHITELIST['runtime_original']['path'], root)

            # Probe readiness
            deadline = time.monotonic() + 1.0 if args.fail_probe else time.monotonic() + 5.0
            probe_res = {'status': 'WAITING', 'error': 'not_started'}
            while time.monotonic() < deadline:
                probe_res = probe_readiness(None, root, prefix, fake_mode=True)
                if probe_res.get('status') == 'READY':
                    result['server_ready'] = True
                    result['readiness_evidence'] = probe_res
                    break
                time.sleep(0.05)

            result['readiness_evidence'] = probe_res
            if not result['server_ready']:
                result['error'] = 'SERVER_NOT_READY'
                raise RuntimeError('SERVER_NOT_READY: probe connection unestablished')

            # Stage 2: Wine PE (simulated)
            wine_cmd = [sys.executable, '-I', '-c', 'import sys; sys.exit(0)']
            wine_proc = subprocess.Popen(wine_cmd)
            result['wine_exit'] = wine_proc.wait(timeout=5.0)
            result['status'] = 'PASS'

        else:
            # Explicit Lead approval gate via flag
            if not args.run_approved:
                raise RuntimeError('Real wine execution blocked: requires explicit --run-approved flag from Lead')

            setup_real_sysroot(root)

            runtime_bin = WHITELIST['runtime_original']['path']
            server_cmd = build_wineserver_command(runtime_bin, root)
            wine_cmd = build_wine_pe_command(runtime_bin, root)
            result['commands']['wineserver'] = server_cmd
            result['commands']['wine_pe'] = wine_cmd

            server_proc = subprocess.Popen(server_cmd)

            deadline = time.monotonic() + 5.0
            probe_res = {'status': 'WAITING', 'error': 'not_started'}
            while time.monotonic() < deadline:
                if server_proc.poll() is not None:
                    break
                probe_res = probe_readiness(runtime_bin, root, prefix, fake_mode=False)
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
            result['wine_exit'] = wine_proc.wait(timeout=20.0)
            result['status'] = 'PASS' if result['wine_exit'] == 0 else 'FAIL'

    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        if wine_proc and wine_proc.poll() is None:
            wine_proc.terminate()
            wine_proc.wait(timeout=2.0)
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=2.0)
            result['wineserver_exit'] = server_proc.returncode
        (work / 'wine-launcher-result.json').write_text(json.dumps(result, indent=2))

    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__':
    sys.exit(main())
