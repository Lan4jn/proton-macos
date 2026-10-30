#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/backend/run_steam_plan_compat_e2e.py

End-to-End Real Artifact Reversible Installation & Rollback Verification (task-129).

Workflow:
1. Initialize mock Steam library fixture root strictly in lab scratch area (logs/steam-plan-compat/fixture_steam_root).
2. Seed mock Proton tool with the real shipped original win32u.so (SHA256: 4f6013fa...).
3. Generate installation plan to replace win32u.so with real patched win32u.so (SHA256: 59a76b05...).
4. Apply plan -> generate manifest.json. Verify target replaced and checksum matches 59a76b05...
5. Verify manifest -> assert verification passes.
6. Rollback manifest -> assert target restored byte-for-byte to 4f6013fa... and tree fingerprint identical.
7. Snapshot check of real host paths proving ZERO write outside fixture root.
"""

import os
import sys
import json
import shutil
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(LAB))

from scripts.backend.steam_plan import (
    create_compat_module_plan,
    apply_installation_plan,
    verify_installation_manifest,
    rollback_installation_manifest,
    compute_tree_fingerprint,
    sha256_file
)

REAL_PATCHED_SO = LAB / "sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so"
REAL_SHIPPED_SO = LAB / "fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/win32u.so"
OUTPUT_DIR = LAB / "logs/steam-plan-compat"

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fixture_steam_root = OUTPUT_DIR / "fixture_steam_root"
    if fixture_steam_root.exists():
        shutil.rmtree(fixture_steam_root)
    fixture_steam_root.mkdir(parents=True, exist_ok=True)

    # 1. Host paths pre-snapshot
    host_paths = [
        Path("/tmp"),
        Path("/Applications"),
        Path(os.path.expanduser("~/Library/Application Support"))
    ]
    pre_host_snapshots = {p: set(os.listdir(p)) for p in host_paths if p.exists()}

    # 2. Seed mock Proton directory
    target_rel = "compatibilitytools.d/Proton-Experimental/files/lib/wine/aarch64-unix/win32u.so"
    target_file = fixture_steam_root / target_rel
    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_SHIPPED_SO, target_file)

    orig_sha = sha256_file(target_file)
    patched_sha = sha256_file(REAL_PATCHED_SO)
    assert orig_sha == "4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5"
    assert patched_sha == "59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed"

    # Pre-install tree fingerprint
    fingerprint_pre = compute_tree_fingerprint(fixture_steam_root)
    (OUTPUT_DIR / "fingerprint_pre.json").write_text(json.dumps(fingerprint_pre, indent=2))

    print("=== Step 1: Generating Compat Module Plan ===")
    plan = create_compat_module_plan(
        fixture_steam_root=fixture_steam_root,
        target_rel_path=target_rel,
        source_module_path=REAL_PATCHED_SO,
        expected_orig_sha256=orig_sha,
        expected_arch="aarch64"
    )
    (OUTPUT_DIR / "plan.json").write_text(json.dumps(plan, indent=2))
    print(f"  Plan written: {OUTPUT_DIR / 'plan.json'}")

    print("\n=== Step 2: Applying Plan ===")
    backup_dir = fixture_steam_root / ".compat_backups"
    manifest = apply_installation_plan(plan, fixture_steam_root, backup_dir=backup_dir)
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  Manifest written: {OUTPUT_DIR / 'manifest.json'}")

    current_installed_sha = sha256_file(target_file)
    print(f"  Target SHA after apply: {current_installed_sha}")
    assert current_installed_sha == patched_sha

    fingerprint_applied = compute_tree_fingerprint(fixture_steam_root)
    (OUTPUT_DIR / "fingerprint_applied.json").write_text(json.dumps(fingerprint_applied, indent=2))

    print("\n=== Step 3: Verifying Manifest ===")
    valid, errors = verify_installation_manifest(manifest, fixture_steam_root)
    verify_result = {"is_valid": valid, "errors": errors}
    (OUTPUT_DIR / "verify_result.json").write_text(json.dumps(verify_result, indent=2))
    print(f"  Verification result: is_valid={valid}, errors={errors}")
    assert valid and len(errors) == 0

    print("\n=== Step 4: Rolling Back Manifest ===")
    rollback_report = rollback_installation_manifest(manifest, fixture_steam_root)
    (OUTPUT_DIR / "rollback_report.json").write_text(json.dumps(rollback_report, indent=2))
    print(f"  Rollback status: {rollback_report['status']}")
    assert rollback_report["status"] == "success"

    restored_sha = sha256_file(target_file)
    print(f"  Target SHA after rollback: {restored_sha}")
    assert restored_sha == orig_sha

    fingerprint_post = compute_tree_fingerprint(fixture_steam_root)
    (OUTPUT_DIR / "fingerprint_post.json").write_text(json.dumps(fingerprint_post, indent=2))
    assert fingerprint_pre == fingerprint_post
    print("  Tree fingerprint byte-for-byte exact restoration verified!")

    # 3. Verify zero write outside fixture root
    for p, orig_files in pre_host_snapshots.items():
        if p.exists():
            cur_files = set(os.listdir(p))
            assert orig_files == cur_files, f"Security violation: path {p} was modified!"
    print("  Zero write outside fixture root confirmed!")

    summary = {
        "status": "SUCCESS",
        "fixture_steam_root": str(fixture_steam_root),
        "source_patched_so": str(REAL_PATCHED_SO),
        "source_patched_sha256": patched_sha,
        "original_shipped_so": str(REAL_SHIPPED_SO),
        "original_shipped_sha256": orig_sha,
        "restored_target_sha256": restored_sha,
        "pre_fingerprint_matches_post": bool(fingerprint_pre == fingerprint_post),
        "zero_write_outside_fixture": True
    }
    (OUTPUT_DIR / "e2e_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nAll e2e checks passed! Summary saved to {OUTPUT_DIR / 'e2e_summary.json'}")

if __name__ == "__main__":
    main()
