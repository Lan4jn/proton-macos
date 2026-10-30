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
    vulkan_path = os.path.join(repo_root, "sources/wine-init-guard-v2/work/dlls/win32u/vulkan.c")
    d3dkmt_path = os.path.join(repo_root, "sources/wine-init-guard-v2/work/dlls/win32u/d3dkmt.c")
    patch_path = os.path.join(repo_root, "sources/wine-init-guard-v2/wine_vulkan_reentrancy_guard_v2.patch")

    vulkan_hash = sha256_file(vulkan_path)
    d3dkmt_hash = sha256_file(d3dkmt_path)
    patch_hash = sha256_file(patch_path)

    print(f"Patched vulkan.c SHA256: {vulkan_hash}")
    print(f"Patched d3dkmt.c SHA256: {d3dkmt_hash}")
    print(f"Patch v2 SHA256: {patch_hash}")

    # Extract vulkan guard code
    vulkan_guard, v_s, v_e = extract_block(
        vulkan_path,
        "static pthread_key_t vulkan_init_key;",
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

    # Extract d3dkmt guard code
    d3dkmt_guard, d_s, d_e = extract_block(
        d3dkmt_path,
        "static pthread_key_t d3dkmt_init_key;",
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

    # Extract d3dkmt callback and once control flow
    d3dkmt_cb, cb_s, cb_e = extract_block(
        d3dkmt_path,
        "static void d3dkmt_init_vulkan(void)",
        "static struct vulkan_instance *get_d3dkmt_vulkan_instance(void)"
    )
    for idx in range(cb_e - 1, len(d_lines)):
        if d_lines[idx].strip() == "}":
            cb_e = idx + 1
            break
    d3dkmt_cb = "".join(d_lines[cb_s - 1:cb_e])
    print(f"Extracted d3dkmt callback control flow from lines {cb_s}-{cb_e} ({len(d3dkmt_cb.splitlines())} lines)")

    out_file = os.path.join(repo_root, "sources/wine-init-guard-v2/extracted_guard.c")
    with open(out_file, "w") as f:
        f.write("/* Automatically extracted guard code from patched real sources */\n")
        f.write(f"/* Source 1: vulkan.c (SHA256: {vulkan_hash}) lines {v_s}-{v_e} */\n")
        f.write("/* --- BEGIN VULKAN GUARD --- */\n")
        f.write(vulkan_guard)
        f.write("\n/* --- END VULKAN GUARD --- */\n\n")
        f.write(f"/* Source 2: d3dkmt.c (SHA256: {d3dkmt_hash}) lines {d_s}-{d_e} */\n")
        f.write("/* --- BEGIN D3DKMT GUARD --- */\n")
        f.write(d3dkmt_guard)
        f.write("\n/* --- END D3DKMT GUARD --- */\n\n")
        f.write(f"/* Source 3: d3dkmt.c callback control flow lines {cb_s}-{cb_e} */\n")
        f.write("/* --- BEGIN D3DKMT CALLBACK FLOW --- */\n")
        f.write("static struct vulkan_instance *d3dkmt_vulkan_instance;\n\n")
        f.write(d3dkmt_cb)
        f.write("\n/* --- END D3DKMT CALLBACK FLOW --- */\n")

    extracted_hash = sha256_file(out_file)
    print(f"Emitted {out_file} (SHA256: {extracted_hash})")

    meta_file = os.path.join(repo_root, "logs/wine-guard-v2/extraction_meta.json")
    meta = {
        "patch_v2_sha256": patch_hash,
        "vulkan_source": {
            "path": vulkan_path,
            "sha256": vulkan_hash,
            "start_line": v_s,
            "end_line": v_e,
        },
        "d3dkmt_source": {
            "path": d3dkmt_path,
            "sha256": d3dkmt_hash,
            "start_line": d_s,
            "end_line": d_e,
        },
        "d3dkmt_callback_flow": {
            "path": d3dkmt_path,
            "start_line": cb_s,
            "end_line": cb_e,
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
