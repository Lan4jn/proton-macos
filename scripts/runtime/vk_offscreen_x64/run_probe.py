import hashlib
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
PROBE_EXE = LAB / "sources/vk-offscreen-x64/vk_offscreen_x64.exe"
BUNDLED_PYTHON = Path("/Users/mewcapoo/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3")

OUTPUT_DIR = LAB / "logs/vk-offscreen-x64"



def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    test_root = OUTPUT_DIR / "runs"
    test_root.mkdir(parents=True, exist_ok=False)
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

    tool_name = "proton_x64_offscreen"
    display_name = "Proton Experimental (FEX x64 Offscreen Probe)"

    # Clone prefix with creation_sync_guard
    pfx_dir = test_root / "pfx"
    shutil.copytree(LAB / "fixtures/runtime/futex-args-vulkan/pfx", pfx_dir, symlinks=True)

    # Deploy vk_offscreen_x64.exe to prefix drive_c
    target_probe = pfx_dir / "drive_c/vk_offscreen_x64.exe"
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


    records = {}
    for label, extra in [('skip_draw', ['--skip-draw']), ('normal', [])]:
        cmd = [str(dest_wrapper), 'runinprefix', 'C:\\vk_offscreen_x64.exe'] + extra
        cmd[2] = 'C:' + chr(92) + 'vk_offscreen_x64.exe'
        before = set(exec_logs_dir.glob('run-*'))
        t0 = time.monotonic()
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=125)
        newruns = set(exec_logs_dir.glob('run-*')) - before
        run = max(newruns, key=lambda x:x.stat().st_mtime) if newruns else None
        raw = run / 'stdout.log' if run else None
        out = raw.read_text(errors='replace') if raw else p.stdout
        err = (run/'stderr.log').read_text(errors='replace') if run else p.stderr
        (OUTPUT_DIR/(label+'_stdout.log')).write_text(out)
        (OUTPUT_DIR/(label+'_stderr.log')).write_text(err)
        result = json.loads((run/'result.json').read_text()) if run and (run/'result.json').exists() else None
        records[label] = {'command':cmd, 'wrapper_exit':p.returncode, 'seconds':time.monotonic()-t0,'run_dir':str(run),'result':result,'first_error_lines':[{'line':i+1,'text':l} for i,l in enumerate(err.splitlines()) if any(k in l.lower() for k in ['error','err:','einval','fault','exception'])][:12]}
        fb=pfx_dir/'drive_c/framebuffer.raw'
        if fb.exists():
            shutil.copyfile(fb,OUTPUT_DIR/(label+'_framebuffer.raw'))
            data=fb.read_bytes()
            ok, details=verify_framebuffer(data)
            records[label]['pixel_valid']=ok
            records[label]['pixel_details']=details
            records[label]['framebuffer_sha256']=hashlib.sha256(data).hexdigest()
        records[label]['negative_pass']=p.returncode==21 and 'MISMATCH! Expected Triangle Color' in out
        records[label]['normal_pass']=p.returncode==0 and records[label].get('pixel_valid',False)
        (OUTPUT_DIR/'receipt.json').write_text(json.dumps({'task':'task-137','probe_sha256':sha256_file(PROBE_EXE),'gate':'1','renderer':'CPU llvmpipe, not hardware GPU','runs':records},indent=2))
        print(label,p.returncode,records[label].get('pixel_valid'),flush=True)
    rollback=rollback_installation_manifest(manifest,fixture_steam_root)
    (OUTPUT_DIR/'rollback.json').write_text(json.dumps(rollback,indent=2,default=str))

if __name__ == '__main__':
    main()
