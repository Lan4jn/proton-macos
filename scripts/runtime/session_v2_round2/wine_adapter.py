"""Wine foreground adapter: prefix copier, mock server, and foreground launcher."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import time

CORE_DLLS = [
    'kernel32.dll',
    'kernelbase.dll',
    'libarm64ecfex.dll',
    'ntdll.dll',
]

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def compute_server_socket_path(base_tmp, prefix_dir):
    st = prefix_dir.stat()
    uid = os.getuid()
    server_dir = f"server-{st.st_dev:x}-{st.st_ino:x}"
    return base_tmp / f".wine-{uid}" / server_dir / "socket"

def copy_and_materialize_prefix(template_dir, target_prefix, work_dir, core_source_root=None):
    if target_prefix.exists():
        raise FileExistsError(f"target prefix already exists: {target_prefix}")
    target_prefix.mkdir(parents=True)

    manifest = {
        'files': {},
        'symlinks': {},
        'dir_symlinks': {},
        'materialized_dlls': {},
    }

    # Use os.scandir / walk without following symlinks
    for root, dirs, files in os.walk(template_dir, followlinks=False):
        rel_root = Path(root).relative_to(template_dir)
        dest_dir = target_prefix / rel_root
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Handle directory symlinks if any in dirs
        for d in list(dirs):
            d_path = Path(root) / d
            if d_path.is_symlink():
                dirs.remove(d)  # do not recurse into dir symlink
                dest_link = dest_dir / d
                target = os.readlink(d_path)
                os.symlink(target, dest_link)
                manifest['dir_symlinks'][str(dest_link.relative_to(target_prefix))] = target

        # Handle files
        for f in files:
            src_file = Path(root) / f
            dest_file = dest_dir / f

            if src_file.is_symlink():
                target = os.readlink(src_file)
                if dest_dir.name == 'system32' and f.lower() in CORE_DLLS:
                    # If core_source_root specified, copy STRICTLY and ONLY from that local directory
                    if core_source_root:
                        real_src = Path(core_source_root) / f
                        if not real_src.is_file():
                            raise FileNotFoundError(f"Core DLL missing from specified local source root {core_source_root}: {f}")
                        shutil.copyfile(real_src, dest_file)
                    else:
                        # Strict fail-closed fallback
                        resolved = src_file.resolve(strict=True)
                        shutil.copyfile(resolved, dest_file)
                    manifest['materialized_dlls'][str(dest_file.relative_to(target_prefix))] = sha256_file(dest_file)
                else:
                    # Retain broken or normal symlink
                    os.symlink(target, dest_file)
                    manifest['symlinks'][str(dest_file.relative_to(target_prefix))] = target
            else:
                shutil.copyfile(src_file, dest_file)
                manifest['files'][str(dest_file.relative_to(target_prefix))] = sha256_file(dest_file)

    # 3. Handle dosdevices c: and z:
    dosdevices = target_prefix / 'dosdevices'
    dosdevices.mkdir(parents=True, exist_ok=True)
    c_link = dosdevices / 'c:'
    if c_link.is_symlink() or c_link.exists():
        c_link.unlink()
    c_target = '../drive_c'
    os.symlink(c_target, c_link)
    manifest['symlinks'][str(c_link.relative_to(target_prefix))] = c_target

    z_link = dosdevices / 'z:'
    if z_link.is_symlink() or z_link.exists():
        z_link.unlink()
    z_target = '/work'
    os.symlink(z_target, z_link)
    manifest['symlinks'][str(z_link.relative_to(target_prefix))] = z_target

    (target_prefix / 'prefix_manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest

def probe_server_socket_ready(sock_path, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sock_path.is_socket():
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.5)
            try:
                s.connect(str(sock_path))
                s.close()
                return True
            except (ConnectionRefusedError, socket.timeout, OSError):
                s.close()
        time.sleep(0.05)
    return False

def run_foreground_wine_session(root_dir, prefix_dir, work_dir, fake_mode=True):
    base_tmp = root_dir / 'tmp'
    sock_path = compute_server_socket_path(base_tmp, prefix_dir)

    server_proc = None
    wine_proc = None
    result = {
        'server_ready': False,
        'server_exit': None,
        'wine_exit': None,
        'error': None,
    }

    try:
        if fake_mode:
            server_cmd = [
                sys.executable, '-I', '-c', f'''
import os, socket, sys, time
p = "{str(sock_path)}"
os.makedirs(os.path.dirname(p), exist_ok=True)
if os.path.exists(p): os.unlink(p)
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
        else:
            raise NotImplementedError("Real wine execution requires explicit Lead lock")

        server_proc = subprocess.Popen(server_cmd)
        ready = probe_server_socket_ready(sock_path, timeout=5.0)
        result['server_ready'] = ready

        if not ready:
            result['error'] = 'SERVER_NOT_READY'
            return result

        if fake_mode:
            wine_cmd = [sys.executable, '-I', '-c', 'import sys; sys.exit(0)']
            wine_proc = subprocess.Popen(wine_cmd)
            result['wine_exit'] = wine_proc.wait(timeout=5.0)
        else:
            pass

    except Exception as exc:
        result['error'] = str(exc)
    finally:
        if wine_proc and wine_proc.poll() is None:
            wine_proc.terminate()
            wine_proc.wait(timeout=2.0)
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=2.0)
            result['server_exit'] = server_proc.returncode

    return result
