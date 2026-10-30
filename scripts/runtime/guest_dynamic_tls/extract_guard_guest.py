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

    vulkan_hash = sha256_file(vulkan_path)
    d3dkmt_hash = sha256_file(d3dkmt_path)

    # Extract vulkan guard
    v_lines, v_s, v_e = extract_block(
        vulkan_path,
        "static __thread int vulkan_init_depth;",
        "void vulkan_init_guard_cleanup(void *arg)"
    )
    with open(vulkan_path, 'r') as f:
        all_v = f.readlines()
    for idx in range(v_e - 1, len(all_v)):
        if all_v[idx].strip() == "}":
            v_e = idx + 1
            break
    v_guard = "".join(all_v[v_s - 1:v_e])

    # Extract d3dkmt guard
    d_lines, d_s, d_e = extract_block(
        d3dkmt_path,
        "static __thread int d3dkmt_init_depth;",
        "static void d3dkmt_init_guard_cleanup(void *arg)"
    )
    with open(d3dkmt_path, 'r') as f:
        all_d = f.readlines()
    for idx in range(d_e - 1, len(all_d)):
        if all_d[idx].strip() == "}":
            d_e = idx + 1
            break
    d_guard = "".join(all_d[d_s - 1:d_e])

    out_file = os.path.join(repo_root, "sources/guest-dynamic-tls/libv3_guard.c")
    with open(out_file, "w") as f:
        f.write("/* Automatically extracted v3 guard code for guest Linux dynamic TLS shared library */\n")
        f.write("#define _GNU_SOURCE\n")
        f.write("#include <stdint.h>\n")
        f.write("#include <pthread.h>\n\n")
        f.write("typedef int BOOL;\n#define TRUE 1\n#define FALSE 0\n\n")
        f.write(f"/* Source: vulkan.c (SHA256: {vulkan_hash}) lines {v_s}-{v_e} */\n")
        f.write(v_guard)
        f.write("\n\n")
        f.write(f"/* Source: d3dkmt.c (SHA256: {d3dkmt_hash}) lines {d_s}-{d_e} */\n")
        f.write(d_guard)
        f.write("\n\n")
        f.write("/* Direct TLS inspector & d3dkmt exports for guest runner verification */\n")
        f.write("BOOL d3dkmt_is_in_progress(void) { return is_d3dkmt_init_in_progress(); }\n")
        f.write("BOOL d3dkmt_guard_enter(void) { return d3dkmt_init_guard_enter(); }\n")
        f.write("void d3dkmt_guard_exit(void) { d3dkmt_init_guard_exit(); }\n")
        f.write("void *get_vulkan_init_depth_addr(void) { return (void *)&vulkan_init_depth; }\n")
        f.write("int get_vulkan_init_depth_val(void) { return vulkan_init_depth; }\n")
        f.write("void *get_d3dkmt_init_depth_addr(void) { return (void *)&d3dkmt_init_depth; }\n")
        f.write("int get_d3dkmt_init_depth_val(void) { return d3dkmt_init_depth; }\n\n")
        f.write("/* Real callback push/pop wrapper directly testing callback semantics */\n")
        f.write("static pthread_mutex_t g_cb_test_mutex = PTHREAD_MUTEX_INITIALIZER;\n")
        f.write("static pthread_cond_t g_cb_test_cond = PTHREAD_COND_INITIALIZER;\n")
        f.write("static int g_cb_block_in_action = 0;\n")
        f.write("static int g_cb_worker_in_action = 0;\n\n")
        f.write("void set_cb_blocking(int enable) { g_cb_block_in_action = enable; g_cb_worker_in_action = 0; }\n")
        f.write("int wait_cb_worker_in_action(void) {\n")
        f.write("    pthread_mutex_lock(&g_cb_test_mutex);\n")
        f.write("    while (!g_cb_worker_in_action) pthread_cond_wait(&g_cb_test_cond, &g_cb_test_mutex);\n")
        f.write("    pthread_mutex_unlock(&g_cb_test_mutex);\n")
        f.write("    return 1;\n")
        f.write("}\n\n")
        f.write("int test_real_callback_flow(int simulate_cancel) {\n")
        f.write("    vulkan_init_guard_enter();\n")
        f.write("    pthread_cleanup_push(vulkan_init_guard_cleanup, NULL);\n")
        f.write("    if (g_cb_block_in_action) {\n")
        f.write("        pthread_mutex_lock(&g_cb_test_mutex);\n")
        f.write("        g_cb_worker_in_action = 1;\n")
        f.write("        pthread_cond_broadcast(&g_cb_test_cond);\n")
        f.write("        while (1) {\n")
        f.write("            pthread_cond_wait(&g_cb_test_cond, &g_cb_test_mutex);\n")
        f.write("        }\n")
        f.write("        pthread_mutex_unlock(&g_cb_test_mutex);\n")
        f.write("    }\n")
        f.write("    pthread_cleanup_pop(1);\n")
        f.write("    return 0;\n")
        f.write("}\n")

    out_hash = sha256_file(out_file)
    print(f"Extracted to {out_file} (SHA256: {out_hash})")

if __name__ == '__main__':
    main()
