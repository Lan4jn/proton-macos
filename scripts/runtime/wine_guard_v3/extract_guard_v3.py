#!/usr/bin/env python3
import sys
import os
import hashlib
import json

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def extract_block(filepath, start_marker, end_marker):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if start_idx is None and start_marker in line:
            start_idx = i
        elif start_idx is not None and end_marker in line:
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise ValueError(f"Could not find markers [{start_marker}] .. [{end_marker}] in {filepath}")
    return "".join(lines[start_idx:end_idx+1]), start_idx + 1, end_idx + 1

def main():
    repo_root = "/Users/mewcapoo/Projects/proton-macos-lab"
    vulkan_path = os.path.join(repo_root, "sources/wine-init-guard-v3/work/dlls/win32u/vulkan.c")
    d3dkmt_path = os.path.join(repo_root, "sources/wine-init-guard-v3/work/dlls/win32u/d3dkmt.c")
    patch_path = os.path.join(repo_root, "sources/wine-init-guard-v3/wine_vulkan_reentrancy_guard_v3.patch")

    vulkan_hash = sha256_file(vulkan_path)
    d3dkmt_hash = sha256_file(d3dkmt_path)
    patch_hash = sha256_file(patch_path)

    print(f"Patched vulkan.c SHA256: {vulkan_hash}")
    print(f"Patched d3dkmt.c SHA256: {d3dkmt_hash}")
    print(f"Patch v3 SHA256: {patch_hash}")

    # Extract vulkan guard definitions
    vulkan_guard, v_s, v_e = extract_block(
        vulkan_path,
        "static __thread int vulkan_init_depth;",
        "void vulkan_init_guard_cleanup(void *arg)"
    )
    with open(vulkan_path, 'r') as f:
        v_lines = f.readlines()
    for idx in range(v_e - 1, len(v_lines)):
        if v_lines[idx].strip() == "}":
            v_e = idx + 1
            break
    vulkan_guard = "".join(v_lines[v_s - 1:v_e])
    print(f"Extracted vulkan guard from lines {v_s}-{v_e} ({len(vulkan_guard.splitlines())} lines)")

    # Extract vulkan_init_once callback control flow
    vulkan_cb, vcb_s, vcb_e = extract_block(
        vulkan_path,
        "static void vulkan_init_once(void)",
        "pthread_cleanup_pop( 1 );"
    )
    for idx in range(vcb_e - 1, len(v_lines)):
        if v_lines[idx].strip() == "}":
            vcb_e = idx + 1
            break
    vulkan_cb = "".join(v_lines[vcb_s - 1:vcb_e])
    print(f"Extracted vulkan_init_once callback flow from lines {vcb_s}-{vcb_e} ({len(vulkan_cb.splitlines())} lines)")

    # Extract d3dkmt guard definitions
    d3dkmt_guard, d_s, d_e = extract_block(
        d3dkmt_path,
        "static __thread int d3dkmt_init_depth;",
        "static void d3dkmt_init_guard_cleanup(void *arg)"
    )
    with open(d3dkmt_path, 'r') as f:
        d_lines = f.readlines()
    for idx in range(d_e - 1, len(d_lines)):
        if d_lines[idx].strip() == "}":
            d_e = idx + 1
            break
    d3dkmt_guard = "".join(d_lines[d_s - 1:d_e])
    print(f"Extracted d3dkmt guard from lines {d_s}-{d_e} ({len(d3dkmt_guard.splitlines())} lines)")

    # Extract d3dkmt callback control flow
    d3dkmt_cb, dcb_s, dcb_e = extract_block(
        d3dkmt_path,
        "static void d3dkmt_init_vulkan(void)",
        "static struct vulkan_instance *get_d3dkmt_vulkan_instance(void)"
    )
    for idx in range(dcb_e - 1, len(d_lines)):
        if d_lines[idx].strip() == "}":
            dcb_e = idx + 1
            break
    d3dkmt_cb = "".join(d_lines[dcb_s - 1:dcb_e])
    print(f"Extracted d3dkmt callback flow from lines {dcb_s}-{dcb_e} ({len(d3dkmt_cb.splitlines())} lines)")

    out_file = os.path.join(repo_root, "sources/wine-init-guard-v3/extracted_guard_v3.c")
    with open(out_file, "w") as f:
        f.write("/* Automatically extracted guard code from patched real sources (v3) */\n")
        f.write(f"/* Source 1: vulkan.c (SHA256: {vulkan_hash}) lines {v_s}-{v_e} */\n")
        f.write("/* --- BEGIN VULKAN GUARD --- */\n")
        f.write(vulkan_guard)
        f.write("\n/* --- END VULKAN GUARD --- */\n\n")

        f.write(f"/* Source 2: d3dkmt.c (SHA256: {d3dkmt_hash}) lines {d_s}-{d_e} */\n")
        f.write("/* --- BEGIN D3DKMT GUARD --- */\n")
        f.write(d3dkmt_guard)
        f.write("\n/* --- END D3DKMT GUARD --- */\n\n")

        f.write(f"/* Source 3: d3dkmt.c callback flow lines {dcb_s}-{dcb_e} */\n")
        f.write("/* --- BEGIN D3DKMT CALLBACK FLOW --- */\n")
        f.write("static struct vulkan_instance *d3dkmt_vulkan_instance;\n\n")
        f.write(d3dkmt_cb)
        f.write("\n/* --- END D3DKMT CALLBACK FLOW --- */\n\n")

        f.write(f"/* Source 4: vulkan.c callback flow lines {vcb_s}-{vcb_e} */\n")
        f.write("/* --- BEGIN VULKAN CALLBACK FLOW --- */\n")
        f.write(vulkan_cb)
        f.write("\n/* --- END VULKAN CALLBACK FLOW --- */\n")

    extracted_hash = sha256_file(out_file)
    print(f"Emitted {out_file} (SHA256: {extracted_hash})")

    meta_file = os.path.join(repo_root, "logs/wine-guard-v3/extraction_meta.json")
    meta = {
        "patch_v3_sha256": patch_hash,
        "vulkan_source": {
            "path": vulkan_path,
            "sha256": vulkan_hash,
            "guard_lines": [v_s, v_e],
            "callback_lines": [vcb_s, vcb_e]
        },
        "d3dkmt_source": {
            "path": d3dkmt_path,
            "sha256": d3dkmt_hash,
            "guard_lines": [d_s, d_e],
            "callback_lines": [dcb_s, dcb_e]
        },
        "extracted_file": {
            "path": out_file,
            "sha256": extracted_hash
        }
    }
    with open(meta_file, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Emitted extraction metadata to {meta_file}")

if __name__ == '__main__':
    main()
