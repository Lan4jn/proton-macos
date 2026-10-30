"""Wine initialization v5 combined bootstrap launcher (31 sources: 27 v4-base + 4 OLE delay-load PE DLLs):
Minimal wrapper importing frozen wine_diagnostics_launcher_v4_combined.py (ee3562),
only diffing the 4 OLE PE DLLs (ole32, combase, rpcrt4, coml2), binds CLOSURE_MANIFEST_R3_V5.json,
keeps identical WINEDEBUG=+timestamp,+pid,+module,+seh,+loaddll, budget 60/75/85 and soft 32MiB cap.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[2]

FROZEN_V4_LAUNCHER = LAB / 'scripts/runtime/wine_init_round3/wine_diagnostics_launcher_v4_combined.py'
FROZEN_V4_SHA = 'ee356252b261c724491e46a24077bd8f8bc305290d2d082d8aac087b39b05411'

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

if sha256_file(FROZEN_V4_LAUNCHER) != FROZEN_V4_SHA:
    raise SystemExit('Frozen wine_diagnostics_launcher_v4_combined.py SHA mismatch')

spec = importlib.util.spec_from_file_location('v4_base', FROZEN_V4_LAUNCHER)
v4_base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v4_base)

CLOSURE_MANIFEST_PATH = LAB / 'sources/wine-init-round3/CLOSURE_MANIFEST_R3_V5.json'
CLOSURE_R3_V5 = json.loads(CLOSURE_MANIFEST_PATH.read_text())

OLE_4_NAMES = ["ole32.dll", "combase.dll", "rpcrt4.dll", "coml2.dll"]

def resolve_repo_path(p_str):
    p = Path(p_str)
    if not p.is_absolute():
        p = LAB / p
    return p.resolve()

# Preserve references to original functions before any hooking
orig_validate_combined = v4_base.validate_closure_sources_combined
orig_setup_combined = v4_base.setup_real_sysroot_combined

def validate_closure_sources_v5():
    # 1. Fail closed on the 4 additional OLE sources BEFORE calling original v4 validation
    for ole_name in OLE_4_NAMES:
        info = CLOSURE_R3_V5['dlls'][ole_name]
        src_p = resolve_repo_path(info['source'])
        if not src_p.is_file():
            raise FileNotFoundError(f"Missing OLE DLL source: {src_p}")
        h = sha256_file(src_p)
        if h != info['sha256']:
            raise ValueError(f"OLE DLL SHA mismatch for {ole_name}: expected {info['sha256']}, got {h}")

    # 2. Call preserved original v4 validation
    orig_validate_combined()

def setup_real_sysroot_v5(target_root):
    validate_closure_sources_v5()
    # 1. Call preserved original v4 setup to materialize 27 base files (18 sort-base + 3 Unix libs + 6 PE DLLs)
    root_manifest = orig_setup_combined(target_root)
    root_manifest['r3_v5_ole_dlls_deployed'] = {}

    bundle_win_dst = target_root / 'wine/lib/wine/aarch64-windows'
    bundle_win_dst.mkdir(parents=True, exist_ok=True)
    sys32_dst = target_root / 'prefix/drive_c/windows/system32'
    sys32_dst.mkdir(parents=True, exist_ok=True)

    # 2. Deploy only the 4 OLE DLLs to bundle and prefix system32
    for ole_name in OLE_4_NAMES:
        info = CLOSURE_R3_V5['dlls'][ole_name]
        src_p = resolve_repo_path(info['source'])
        dst_bundle = bundle_win_dst / ole_name
        v4_base.sort_base.diag_base.base_s3v2.base.clone_or_copy(src_p, dst_bundle)

        dst_sys32 = sys32_dst / ole_name
        if dst_sys32.is_symlink() or dst_sys32.exists():
            dst_sys32.unlink()
        v4_base.sort_base.diag_base.base_s3v2.base.clone_or_copy(src_p, dst_sys32)
        h = sha256_file(dst_sys32)
        if h != info['sha256']:
            raise ValueError(f"Deployed OLE DLL SHA mismatch for {ole_name}")

        root_manifest['r3_v5_ole_dlls_deployed'][ole_name] = {
            'target': f"prefix/drive_c/windows/system32/{ole_name}",
            'sha256': h,
            'bytes': dst_sys32.stat().st_size,
            'inode': dst_sys32.stat().st_ino
        }

    (target_root / 'root_manifest.json').write_text(json.dumps(root_manifest, indent=2))
    return root_manifest

# Hook setup into v4_base module namespace
v4_base.setup_real_sysroot_combined = setup_real_sysroot_v5
v4_base.validate_closure_sources_combined = validate_closure_sources_v5

def main():
    return v4_base.main()

if __name__ == '__main__':
    sys.exit(main())
