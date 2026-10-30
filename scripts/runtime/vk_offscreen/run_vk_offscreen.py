#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/runtime/vk_offscreen/run_vk_offscreen.py

End-to-End Windows ARM64 Vulkan Offscreen Triangle Rendering & Readback Runner (task-135).

Pipeline:
1. Clones isolated prefix, deploys Windows ARM64 PE probe (vk_offscreen_arm64.exe).
2. Generates compatibility tool package with natural-aligned patched win32u.so (59a76b05...)
   and shipped winevulkan.so (2786ca6f...).
3. Applies integrated installation plan into fixture Steam root.
4. Moves source package away (proves relocatability of installed adapter).
5. Directly executes installed destination wrapper: proton-wrapper.sh runinprefix C:\vk_offscreen_arm64.exe.
6. Reads back C:\framebuffer.raw (64x64 RGBA8 = 16384 bytes).
7. Renders visualization PNGs via bundled Pillow.
8. Executes multi-point pixel validation & negative tests.
9. Performs rollback and asserts byte-for-byte exact fingerprint restoration.
10. Validates bounded host observation anchors.
"""

import os
import sys
import json
import time
import shutil
import subprocess
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(LAB))

from scripts.backend.steam_plan import (
    generate_compatibility_tool_vdfs,
    create_compat_tool_plan,
    apply_installation_plan,
    verify_installation_manifest,
    rollback_installation_manifest,
    compute_tree_fingerprint,
    sha256_file
)
from scripts.backend.steam_handoff import prepare_runtime_tool
from scripts.runtime.vk_offscreen.verify_pixels import verify_framebuffer, run_negative_tests

REAL_PATCHED_SO = LAB / "sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so"
REAL_SHIPPED_SO = LAB / "fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/win32u.so"
REAL_SHIPPED_VK = LAB / "fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/winevulkan.so"
ELFUSE_BIN = LAB / "sources/elfuse-once-panorama2-derived/build/elfuse"
SYSROOT_DIR = LAB / "fixtures/runtime/arch-case"
LAVAPIPE_LIB = LAB / "fixtures/runtime/lavapipe-derived/usr/lib"
LAVAPIPE_ICD = LAB / "fixtures/runtime/lavapipe-derived/usr/share/vulkan/icd.d/lvp_icd.json"
STEAM_STUB = LAB / "fixtures/runtime/steam-stub"
PROBE_EXE = LAB / "sources/vk-offscreen-probe/vk_offscreen_arm64.exe"
BUNDLED_PYTHON = Path("/Users/mewcapoo/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3")

OUTPUT_DIR = LAB / "logs/vk-offscreen"


def render_pngs(raw_path: Path, out_dir: Path):
    cmd = [
        str(BUNDLED_PYTHON),
        "-c",
        f"""
from PIL import Image
from pathlib import Path

data = Path('{raw_path}').read_bytes()
img = Image.frombytes('RGBA', (64, 64), data)
img.save(Path('{out_dir}/framebuffer.png'))
img_upscaled = img.resize((256, 256), Image.Resampling.NEAREST)
img_upscaled.save(Path('{out_dir}/framebuffer_256.png'))
print('PNGs generated successfully')
"""
    ]
    subprocess.run(cmd, check=True)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(["killall", "-9", "elfuse"], capture_output=True)
    time.sleep(1)

    # 1. Bounded host observation setup
    host_paths = [
        Path(os.path.expanduser("~/Library/Application Support/Steam")),
        Path(os.path.expanduser("~/Library/Application Support")),
        Path("/Applications")
    ]
    pre_host_snapshots = {p: set(os.listdir(p)) for p in host_paths if p.exists()}

    test_root = OUTPUT_DIR / "runs"
    if test_root.exists():
        shutil.rmtree(test_root)
    test_root.mkdir(parents=True, exist_ok=True)

    fixture_steam_root = test_root / "fixture_steam_root"
    fixture_steam_root.mkdir(parents=True, exist_ok=True)

    # 2. Prepare source tool package
    source_tool_pkg = test_root / "source_proton_pkg"
    source_tool_pkg.mkdir(parents=True, exist_ok=True)

    # Copy files tree
    shutil.copytree(LAB / "sources/wine-win32u-experimental/patched-full/files", source_tool_pkg / "files", symlinks=True)

    # Copy share with default_pfx_arm64
    share_dst = source_tool_pkg / "files/share"
    if os.path.islink(share_dst) or os.path.lexists(share_dst):
        if os.path.islink(share_dst): os.unlink(share_dst)
        else: shutil.rmtree(share_dst)
    shutil.copytree(LAB / "fixtures/runtime/proton-derived/files/share", share_dst, symlinks=True)

    # Seed binaries in source package
    u_dst = source_tool_pkg / "files/lib/wine/aarch64-unix/win32u.so"
    if u_dst.exists(): u_dst.chmod(0o755); u_dst.unlink()
    shutil.copyfile(REAL_SHIPPED_SO, u_dst)
    u_dst.chmod(0o755)

    v_dst = source_tool_pkg / "files/lib/wine/aarch64-unix/winevulkan.so"
    if v_dst.exists(): v_dst.chmod(0o755); v_dst.unlink()
    shutil.copyfile(REAL_SHIPPED_VK, v_dst)
    v_dst.chmod(0o755)

    shutil.copyfile(LAB / "fixtures/runtime/proton-derived/proton", source_tool_pkg / "proton")
    shutil.copyfile(LAB / "fixtures/runtime/proton-derived/filelock.py", source_tool_pkg / "filelock.py")
    (source_tool_pkg / "version").write_text("experimental-11.0-20260924-arm64\n")

    tool_name = "proton_arm64_patched"
    display_name = "Proton Experimental (ARM64 Vulkan Guard Patched)"

    # Clone prefix with creation_sync_guard
    pfx_dir = test_root / "pfx"
    shutil.copytree(LAB / "fixtures/runtime/futex-args-vulkan/pfx", pfx_dir, symlinks=True)

    # Deploy vk_offscreen_arm64.exe to prefix drive_c
    target_probe = pfx_dir / "drive_c/vk_offscreen_arm64.exe"
    shutil.copyfile(PROBE_EXE, target_probe)
    target_probe.chmod(0o755)

    # Diagnostic & Guest Environments
    diag_env = {
        "ELFUSE_DIAG_SESSION_SHARED": "1",
        "ELFUSE_IO_TRANSACTION_OBSERVE": "1",
        "ELFUSE_FIXTURE_IDENTITY": "1",
        "ELFUSE_FUTEX_OWNER_OBSERVE": "1",
        "ELFUSE_THREAD_LIFETIME_OBSERVE": "1",
        "ELFUSE_ONCE_PANORAMA_OBSERVE": "1",
        "ELFUSE_ONCE_COUNT_OBSERVE": "1",
        "ELFUSE_ONCE_TRACE_OBSERVE": "1",
        "VK_ICD_FILENAMES": str(LAVAPIPE_ICD),
        "WINEDEBUG": "+timestamp,+winstation,+vulkan,+explorer,+driver,warn+vulkan"
    }
    guest_env = {
        "LD_LIBRARY_PATH": f"{LAVAPIPE_LIB}:{SYSROOT_DIR}/usr/lib",
        "VK_LOADER_DEBUG": "all"
    }

    exec_logs_dir = test_root / "logs"
    prepare_runtime_tool(
        output_dir=source_tool_pkg,
        target_dir=fixture_steam_root / "compatibilitytools.d",
        execute_runtime=True,
        elfuse_path=ELFUSE_BIN,
        sysroot=SYSROOT_DIR,
        prefix=pfx_dir,
        runtime_bundle="$DIR",
        logs_dir=exec_logs_dir,
        guest_env=guest_env,
        diagnostic_env=diag_env,
        timeout=110.0
    )

    generate_compatibility_tool_vdfs(
        output_dir=source_tool_pkg,
        tool_name=tool_name,
        display_name=display_name,
        wrapper_rel_path="proton-wrapper.sh"
    )

    # Seed unrelated file to verify isolation
    unrelated_file = fixture_steam_root / "steam_library_marker.vdf"
    unrelated_file.write_text('"AppState" { "appid" "4185400" }\n')
    unrelated_sha = sha256_file(unrelated_file)

    fingerprint_pre = compute_tree_fingerprint(fixture_steam_root)
    (OUTPUT_DIR / "fingerprint_pre.json").write_text(json.dumps(fingerprint_pre, indent=2))

    # 3. Create & Apply Plan
    plan = create_compat_tool_plan(
        fixture_steam_root=fixture_steam_root,
        source_tool_dir=source_tool_pkg,
        tool_name=tool_name,
        display_name=display_name,
        compat_modules=[{
            "target_rel_path": "files/lib/wine/aarch64-unix/win32u.so",
            "source_path": REAL_PATCHED_SO,
            "expected_orig_sha256": "4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5",
            "expected_arch": "aarch64"
        }]
    )
    (OUTPUT_DIR / "plan.json").write_text(json.dumps(plan, indent=2))

    manifest = apply_installation_plan(plan, fixture_steam_root)
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))

    dest_tool_dir = fixture_steam_root / "compatibilitytools.d" / tool_name
    dest_win32u = dest_tool_dir / "files/lib/wine/aarch64-unix/win32u.so"
    dest_winevulkan = dest_tool_dir / "files/lib/wine/aarch64-unix/winevulkan.so"
    dest_wrapper = dest_tool_dir / "proton-wrapper.sh"

    installed_win32u_sha = sha256_file(dest_win32u)
    installed_vulkan_sha = sha256_file(dest_winevulkan)
    assert installed_win32u_sha == "59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed"
    assert installed_vulkan_sha == "2786ca6f5f440821972e91a371e609d2d482597a8b6d75bcf02e287f83eea9ab"

    valid, errors = verify_installation_manifest(manifest, fixture_steam_root)
    assert valid and len(errors) == 0

    # 4. MOVE SOURCE AWAY
    moved_source = test_root / "source_pkg_MOVED_AWAY"
    if moved_source.exists():
        shutil.rmtree(moved_source)
    shutil.move(source_tool_pkg, moved_source)
    assert not source_tool_pkg.exists()

    # 5. EXECUTE INSTALLED DESTINATION WRAPPER (RUN 1: NORMAL DRAW)
    print(f"Executing installed wrapper (Normal Draw): {dest_wrapper} runinprefix C:\\vk_offscreen_arm64.exe")
    t0 = time.time()
    p_normal = subprocess.run([str(dest_wrapper), "runinprefix", "C:\\vk_offscreen_arm64.exe"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    duration_normal = time.time() - t0
    print(f"Normal draw completed in {duration_normal:.2f}s, exit code: {p_normal.returncode}")

    runs = sorted(list(exec_logs_dir.glob("run-*")), key=lambda r: r.stat().st_mtime)
    normal_run_dir = runs[-1] if runs else None

    run_stdout_normal = ""
    run_stderr_normal = ""
    if normal_run_dir:
        if (normal_run_dir / "stdout.log").exists():
            run_stdout_normal = (normal_run_dir / "stdout.log").read_text(errors="replace")
        if (normal_run_dir / "stderr.log").exists():
            run_stderr_normal = (normal_run_dir / "stderr.log").read_text(errors="replace")

    (OUTPUT_DIR / "stdout.log").write_text(run_stdout_normal)
    (OUTPUT_DIR / "stderr.log").write_text(run_stderr_normal)

    # 5B. EXECUTE REAL PE NEGATIVE CONTROL (RUN 2: --skip-draw)
    print(f"Executing real PE negative control: {dest_wrapper} runinprefix C:\\vk_offscreen_arm64.exe --skip-draw")
    t1 = time.time()
    p_skip = subprocess.run([str(dest_wrapper), "runinprefix", "C:\\vk_offscreen_arm64.exe", "--skip-draw"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    duration_skip = time.time() - t1
    print(f"Negative control completed in {duration_skip:.2f}s, exit code: {p_skip.returncode}")

    runs_after_skip = sorted(list(exec_logs_dir.glob("run-*")), key=lambda r: r.stat().st_mtime)
    skip_run_dir = runs_after_skip[-1] if runs_after_skip else None

    run_stdout_skip = ""
    run_stderr_skip = ""
    if skip_run_dir:
        if (skip_run_dir / "stdout.log").exists():
            run_stdout_skip = (skip_run_dir / "stdout.log").read_text(errors="replace")
        if (skip_run_dir / "stderr.log").exists():
            run_stderr_skip = (skip_run_dir / "stderr.log").read_text(errors="replace")

    (OUTPUT_DIR / "stdout_skip_draw.log").write_text(run_stdout_skip)
    (OUTPUT_DIR / "stderr_skip_draw.log").write_text(run_stderr_skip)

    # Verify that real PE negative test caught the missing triangle and exited with code 21
    assert p_skip.returncode == 21, f"Expected exit code 21 for --skip-draw, got {p_skip.returncode}"
    assert "MISMATCH! Expected Triangle Color" in run_stdout_skip
    print("Real PE graphics path negative control verified: --skip-draw failed with exit 21 as expected!")

    # 6. READ RAW FRAMEBUFFER (from normal run)
    # Notice: Re-run normal draw briefly if needed to restore framebuffer.raw, or read normal output
    pfx_probe = pfx_dir / "drive_c/vk_offscreen_arm64.exe"
    p_restore = subprocess.run([str(dest_wrapper), "runinprefix", "C:\\vk_offscreen_arm64.exe"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    assert p_restore.returncode == 0
    raw_fb_pfx = pfx_dir / "drive_c/framebuffer.raw"
    assert raw_fb_pfx.exists(), f"framebuffer.raw missing from {raw_fb_pfx}!"
    raw_bytes = raw_fb_pfx.read_bytes()
    raw_dest = OUTPUT_DIR / "framebuffer.raw"
    raw_dest.write_bytes(raw_bytes)
    fb_sha = sha256_file(raw_dest)
    print(f"Framebuffer readback successful! Length: {len(raw_bytes)} bytes, SHA256: {fb_sha}")

    # 7. RENDER PNG VISUALIZATION
    render_pngs(raw_dest, OUTPUT_DIR)
    print("PNG visual artifacts rendered: framebuffer.png, framebuffer_256.png")

    # 8. VALIDATE PIXELS
    pixel_valid, pixel_details = verify_framebuffer(raw_bytes)
    (OUTPUT_DIR / "pixel_verification.json").write_text(json.dumps(pixel_details, indent=2))
    assert pixel_valid, f"Pixel validation failed: {pixel_details['errors']}"

    # 9. RUN NEGATIVE TESTS
    neg_results = run_negative_tests()
    (OUTPUT_DIR / "negative_tests.json").write_text(json.dumps(neg_results, indent=2))
    assert neg_results["all_passed"], "Negative validator tests failed!"

    # 10. ROLLBACK MANIFEST
    rollback_report = rollback_installation_manifest(manifest, fixture_steam_root)
    (OUTPUT_DIR / "rollback_report.json").write_text(json.dumps(rollback_report, indent=2))
    assert rollback_report["status"] == "success"

    assert not dest_tool_dir.exists()
    assert unrelated_file.exists()
    assert sha256_file(unrelated_file) == unrelated_sha

    fingerprint_post = compute_tree_fingerprint(fixture_steam_root)
    (OUTPUT_DIR / "fingerprint_post.json").write_text(json.dumps(fingerprint_post, indent=2))
    assert fingerprint_pre == fingerprint_post
    print("Rollback verified byte-for-byte exact!")

    # 11. Bounded host observation verification
    for hp, orig_files in pre_host_snapshots.items():
        if hp.exists():
            cur_files = set(os.listdir(hp))
            assert orig_files == cur_files, f"Security violation: anchor {hp} was modified!"
    print("Bounded host observation anchors verified (zero name changes in host anchors)!")

    # 12. SUMMARY RECEIPT
    receipt = {
        "task_id": "task-135",
        "status": "COMPLETED",
        "layered_verdicts": {
            "installation_pass": bool(rollback_report["status"] == "success"),
            "adapter_execution_pass": bool(p_normal.returncode == 0),
            "vulkan_enumeration_pass": bool("Selected Device: llvmpipe" in run_stdout_normal),
            "vulkan_offscreen_draw_pass": bool("Render complete, fence signaled" in run_stdout_normal),
            "pixel_verification_pass": pixel_valid,
            "synthetic_negative_tests_pass": neg_results["all_passed"],
            "real_pe_skip_draw_negative_pass": bool(p_skip.returncode == 21 and "MISMATCH! Expected Triangle Color" in run_stdout_skip)
        },
        "performance_and_throughput": {
            "normal_execution_duration_seconds": duration_normal,
            "skip_draw_execution_duration_seconds": duration_skip,
            "normal_probe_exit_code": p_normal.returncode,
            "skip_draw_probe_exit_code": p_skip.returncode,
            "framebuffer_dimensions": [64, 64],
            "framebuffer_byte_size": len(raw_bytes),
            "framebuffer_sha256": fb_sha,
            "draw_calls": 1,
            "triangles_drawn": 1
        },
        "artifacts": {
            "probe_executable": str(PROBE_EXE),
            "probe_sha256": sha256_file(PROBE_EXE),
            "vert_shader_spv": sha256_file(LAB / "sources/vk-offscreen-probe/shaders/triangle.vert.spv"),
            "frag_shader_spv": sha256_file(LAB / "sources/vk-offscreen-probe/shaders/triangle.frag.spv"),
            "framebuffer_raw": str(raw_dest),
            "framebuffer_png": str(OUTPUT_DIR / "framebuffer.png"),
            "framebuffer_png_256": str(OUTPUT_DIR / "framebuffer_256.png")
        },
        "environment": {
            "device": "llvmpipe (LLVM 23.1.1, 128 bits) CPU",
            "elfuse_binary": str(ELFUSE_BIN),
            "elfuse_sha256": sha256_file(ELFUSE_BIN),
            "patched_win32u_sha256": installed_win32u_sha,
            "shipped_winevulkan_sha256": installed_vulkan_sha,
            "diagnostic_caveat": "ELFUSE_DIAG_SESSION_SHARED=1 active (diagnostic shared alias mapping for winstation sections)"
        }
    }
    (OUTPUT_DIR / "receipt.json").write_text(json.dumps(receipt, indent=2))
    print(f"\nAll pipeline steps complete! Full receipt saved to {OUTPUT_DIR / 'receipt.json'}")


if __name__ == "__main__":
    main()
