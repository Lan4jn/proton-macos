#!/usr/bin/env python3
import os
import shutil
import hashlib
from pathlib import Path

REPO_ROOT = Path("/Users/mewcapoo/Projects/proton-macos-lab")
PROVEN_TEMPLATE = REPO_ROOT / "sources/wine-win32u-experimental/patched-full/files"
DEPLOY_ROOT = REPO_ROOT / "sources/wine-v3-vulkan-build/deploy"

ORIG_SO = REPO_ROOT / "fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/win32u.so"
PRIST_SO = REPO_ROOT / "sources/wine-v3-vulkan-build/target_pristine_build/dlls/win32u/win32u.so"
PATCH_SO = REPO_ROOT / "sources/wine-v3-vulkan-build/target_patched_build/dlls/win32u/win32u.so"

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def setup_tree(target_dir, win32u_so_source):
    print(f"Setting up tree at {target_dir}...")
    files_dir = target_dir / "files"
    if files_dir.exists():
        shutil.rmtree(files_dir)
    
    shutil.copytree(PROVEN_TEMPLATE, files_dir, symlinks=True)

    dest_so = files_dir / "lib/wine/aarch64-unix/win32u.so"
    if dest_so.exists():
        dest_so.unlink()
    shutil.copyfile(win32u_so_source, dest_so)
    dest_so.chmod(0o755)

    sha = sha256_file(dest_so)
    print(f"  win32u.so deployed: {dest_so} (SHA256: {sha})")
    return sha

def main():
    DEPLOY_ROOT.mkdir(parents=True, exist_ok=True)

    sha_orig = setup_tree(DEPLOY_ROOT / "original", ORIG_SO)
    sha_prist = setup_tree(DEPLOY_ROOT / "pristine", PRIST_SO)
    sha_patch = setup_tree(DEPLOY_ROOT / "patched", PATCH_SO)

    print("=== Deployed SHA256 summary ===")
    print(f"Original: {sha_orig}")
    print(f"Pristine: {sha_prist}")
    print(f"Patched:  {sha_patch}")

    assert sha_orig == "4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5"
    assert sha_prist == "341ddb623e8d924e03e74dd6bfb7cc5cce6f18f1cb25341127b2c68a3aaae23c"
    assert sha_patch == "60f7b3235aa5cb867b1a3286f987a57ea5707df7e1c1c00005a795dfcb06e24b"
    print("All trees deployed and verified successfully!")

if __name__ == '__main__':
    main()
