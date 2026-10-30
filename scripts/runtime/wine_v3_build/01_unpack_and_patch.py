#!/usr/bin/env python3
import os
import sys
import tarfile
import hashlib
import json
import shutil
import subprocess

REPO_ROOT = "/Users/mewcapoo/Projects/proton-macos-lab"
ARCHIVE_PATH = os.path.join(REPO_ROOT, "sources/wine-v3-build/wine-dc26e61847081a1b5cb0733dc30feba6ee575482.tar.gz")
PRISTINE_DIR = os.path.join(REPO_ROOT, "sources/wine-v3-build/pristine")
PATCHED_DIR = os.path.join(REPO_ROOT, "sources/wine-v3-build/patched")
PATCH_FILE = os.path.join(REPO_ROOT, "sources/wine-init-guard-v3/wine_vulkan_reentrancy_guard_v3.patch")

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def main():
    if not os.path.exists(ARCHIVE_PATH):
        print(f"ERROR: Archive not found: {ARCHIVE_PATH}", file=sys.stderr)
        sys.exit(1)

    archive_sha = sha256_file(ARCHIVE_PATH)
    archive_size = os.path.getsize(ARCHIVE_PATH)
    print(f"Archive SHA256: {archive_sha} ({archive_size} bytes)")

    # 1. Unpack into pristine
    os.makedirs(PRISTINE_DIR, exist_ok=True)
    print(f"Unpacking archive into {PRISTINE_DIR}...")
    with tarfile.open(ARCHIVE_PATH, "r:gz") as tar:
        tar.extractall(path=PRISTINE_DIR)

    # Find the extracted root directory (usually wine-dc26e61847081a1b5cb0733dc30feba6ee575482)
    entries = os.listdir(PRISTINE_DIR)
    extracted_root = None
    for e in entries:
        full = os.path.join(PRISTINE_DIR, e)
        if os.path.isdir(full) and "wine" in e:
            extracted_root = full
            break

    if not extracted_root:
        print("ERROR: Could not find extracted root dir in pristine", file=sys.stderr)
        sys.exit(1)

    print(f"Extracted root: {extracted_root}")

    # 2. Copy to patched
    if os.path.exists(PATCHED_DIR):
        shutil.rmtree(PATCHED_DIR)
    print(f"Copying pristine tree to {PATCHED_DIR}...")
    shutil.copytree(PRISTINE_DIR, PATCHED_DIR)

    patched_root = os.path.join(PATCHED_DIR, os.path.basename(extracted_root))

    # 3. Compute manifest of pristine key files
    key_files = [
        "configure",
        "configure.ac",
        "dlls/win32u/vulkan.c",
        "dlls/win32u/d3dkmt.c",
        "dlls/win32u/win32u_private.h",
        "dlls/win32u/sysparams.c",
        "dlls/win32u/opengl.c",
        "include/config.h.in"
    ]
    manifest = {
        "official_url": "https://github.com/ValveSoftware/wine/archive/dc26e61847081a1b5cb0733dc30feba6ee575482.tar.gz",
        "commit": "dc26e61847081a1b5cb0733dc30feba6ee575482",
        "archive_sha256": archive_sha,
        "archive_size": archive_size,
        "pristine_root": extracted_root,
        "patched_root": patched_root,
        "key_files_sha256": {}
    }
    for kf in key_files:
        p = os.path.join(extracted_root, kf)
        if os.path.exists(p):
            manifest["key_files_sha256"][kf] = sha256_file(p)

    manifest_path = os.path.join(REPO_ROOT, "logs/wine-v3-build/unpack_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Saved manifest to {manifest_path}")

    # 4. Dry-run apply v3 patch
    print("Testing patch dry-run on patched tree...")
    cmd_dry = f"patch -p1 --dry-run -d {patched_root} < {PATCH_FILE}"
    p_dry = subprocess.run(cmd_dry, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print("Patch dry-run exit code:", p_dry.returncode)
    print("Patch dry-run stdout:", p_dry.stdout.strip())
    if p_dry.returncode != 0:
        print("Patch dry-run stderr:", p_dry.stderr.strip(), file=sys.stderr)
        sys.exit(2)

    # 5. Actually apply v3 patch
    print("Applying v3 patch to patched tree...")
    cmd_apply = f"patch -p1 -d {patched_root} < {PATCH_FILE}"
    p_apply = subprocess.run(cmd_apply, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print("Patch apply exit code:", p_apply.returncode)
    print("Patch apply stdout:", p_apply.stdout.strip())
    if p_apply.returncode != 0:
        print("Patch apply stderr:", p_apply.stderr.strip(), file=sys.stderr)
        sys.exit(3)

    print("Unpack and patch application completed successfully!")

if __name__ == '__main__':
    main()
