"""Wine initialization v6 combined bootstrap launcher (33 sources: 31 v5-base + 2 Wininet delay-load PE DLLs):
Minimal wrapper importing frozen wine_diagnostics_launcher_v5_ole.py (77eedc),
only diffing the 2 Wininet PE DLLs (wininet.dll, mpr.dll), binds CLOSURE_MANIFEST_R3_V6.json,
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

FROZEN_V5_LAUNCHER = LAB / 'scripts/runtime/wine_init_round3/wine_diagnostics_launcher_v5_ole.py'
FROZEN_V5_SHA = '77eedc70ec67e2993be2170a32874f55431dc4ce06bceecadef849933f8361ba'

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

if sha256_file(FROZEN_V5_LAUNCHER) != FROZEN_V5_SHA:
    raise SystemExit('Frozen wine_diagnostics_launcher_v5_ole.py SHA mismatch')

spec = importlib.util.spec_from_file_location('v5_base', FROZEN_V5_LAUNCHER)
v5_base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v5_base)

CLOSURE_MANIFEST_PATH = LAB / 'sources/wine-init-round3/CLOSURE_MANIFEST_R3_V6.json'
CLOSURE_R3_V6 = json.loads(CLOSURE_MANIFEST_PATH.read_text())

WININET_2_NAMES = ["wininet.dll", "mpr.dll"]

def resolve_repo_path(p_str):
    p = Path(p_str)
    if not p.is_absolute():
        p = LAB / p
    return p.resolve()

# Preserve references to original v5 functions before hooking
orig_validate_v5 = v5_base.validate_closure_sources_v5
orig_setup_v5 = v5_base.setup_real_sysroot_v5

def validate_closure_sources_v6():
    # 1. Fail closed on the 2 additional Wininet sources BEFORE calling v5 validation
    for wininet_name in WININET_2_NAMES:
        info = CLOSURE_R3_V6['dlls'][wininet_name]
        src_p = resolve_repo_path(info['source'])
        if not src_p.is_file():
            raise FileNotFoundError(f"Missing Wininet DLL source: {src_p}")
        h = sha256_file(src_p)
        if h != info['sha256']:
            raise ValueError(f"Wininet DLL SHA mismatch for {wininet_name}: expected {info['sha256']}, got {h}")

    # 2. Call preserved v5 validation
    orig_validate_v5()

def setup_real_sysroot_v6(target_root):
    validate_closure_sources_v6()
    # 1. Call preserved original v5 setup to materialize 31 base files
    root_manifest = orig_setup_v5(target_root)
    root_manifest['r3_v6_wininet_dlls_deployed'] = {}

    bundle_win_dst = target_root / 'wine/lib/wine/aarch64-windows'
    bundle_win_dst.mkdir(parents=True, exist_ok=True)
    sys32_dst = target_root / 'prefix/drive_c/windows/system32'
    sys32_dst.mkdir(parents=True, exist_ok=True)

    # 2. Deploy only the 2 Wininet DLLs to bundle and prefix system32
    for wininet_name in WININET_2_NAMES:
        info = CLOSURE_R3_V6['dlls'][wininet_name]
        src_p = resolve_repo_path(info['source'])
        dst_bundle = bundle_win_dst / wininet_name
        v5_base.v4_base.sort_base.diag_base.base_s3v2.base.clone_or_copy(src_p, dst_bundle)

        dst_sys32 = sys32_dst / wininet_name
        if dst_sys32.is_symlink() or dst_sys32.exists():
            dst_sys32.unlink()
        v5_base.v4_base.sort_base.diag_base.base_s3v2.base.clone_or_copy(src_p, dst_sys32)
        h = sha256_file(dst_sys32)
        if h != info['sha256']:
            raise ValueError(f"Deployed Wininet DLL SHA mismatch for {wininet_name}")

        root_manifest['r3_v6_wininet_dlls_deployed'][wininet_name] = {
            'target': f"prefix/drive_c/windows/system32/{wininet_name}",
            'sha256': h,
            'bytes': dst_sys32.stat().st_size,
            'inode': dst_sys32.stat().st_ino
        }

    (target_root / 'root_manifest.json').write_text(json.dumps(root_manifest, indent=2))
    return root_manifest

# Hook setup into v5_base module namespace
v5_base.setup_real_sysroot_v5 = setup_real_sysroot_v6
v5_base.validate_closure_sources_v5 = validate_closure_sources_v6

# Also hook into the underlying v4_base where v4_base.main() looks for setup_real_sysroot_combined
v5_base.v4_base.setup_real_sysroot_combined = setup_real_sysroot_v6
v5_base.v4_base.validate_closure_sources_combined = validate_closure_sources_v6

def main():
    return v5_base.main()

if __name__ == '__main__':
    sys.exit(main())
