#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/backend/run_e2e_steam_plan.py

Executable runner for the end-to-end reversible Steam installation plan & manifest validation.
Generates plan.json, manifest.json, verify.json, and rollback_report.json in logs/steam-plan/.
"""

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(LAB))

from scripts.backend.steam_plan import (
    create_installation_plan,
    apply_installation_plan,
    verify_installation_manifest,
    rollback_installation_manifest,
    compute_tree_fingerprint,
    SteamPlanError
)

log_dir = LAB / "logs/steam-plan"
log_dir.mkdir(parents=True, exist_ok=True)

sandbox = log_dir / "e2e_fixture_run"
if sandbox.exists():
    shutil.rmtree(sandbox)
sandbox.mkdir(parents=True, exist_ok=True)

# 1. Setup fixture Steam directory
fixture_steam = sandbox / "mock_steam_root"
fixture_steam.mkdir(parents=True, exist_ok=True)

# Setup existing files
compat_d = fixture_steam / "compatibilitytools.d"
compat_d.mkdir(parents=True, exist_ok=True)
(compat_d / "existing_system_tool.txt").write_text("prior_tool_config\n")
(fixture_steam / "steamapps").mkdir(parents=True, exist_ok=True)
(fixture_steam / "steamapps" / "libraryfolders.vdf").write_text('"LibraryFolders" { "0" "/mock" }\n')

# 2. Setup candidate source tool
src_tool = sandbox / "candidate_proton_tool"
src_tool.mkdir(parents=True, exist_ok=True)
(src_tool / "toolmanifest.vdf").write_text('"manifest" { "version" "2" "commandline" "/proton run" }\n')
(src_tool / "compatibilitytool.vdf").write_text('"compatibilitytools" { "compat_tools" { "proton_arm64_e2e" { "install_path" "." "display_name" "Proton ARM64" "from_oslist" "windows" "to_oslist" "linux" } } }\n')
(src_tool / "proton").write_text("#!/bin/sh\necho Proton Live Mock\n")
os.chmod(src_tool / "proton", 0o755)

sub = src_tool / "files" / "bin"
sub.mkdir(parents=True, exist_ok=True)
(sub / "wine").write_bytes(b"\x7fELF\x02\x01\x01\x00WINE_BINARY_PAYLOAD")
os.chmod(sub / "wine", 0o755)

print("=== [STEP 1] Baseline Fingerprint ===")
baseline_fingerprint = compute_tree_fingerprint(fixture_steam)
print(f"Baseline files: {list(baseline_fingerprint.keys())}")

print("\n=== [STEP 2] Create Pure Plan ===")
t0 = time.monotonic()
plan = create_installation_plan(
    fixture_steam_root=fixture_steam,
    source_tool_dir=src_tool,
    tool_name="proton_arm64_e2e"
)
plan_time = time.monotonic() - t0
print(f"Plan created in {plan_time*1000:.2f}ms, steps: {plan['total_steps']}")
(log_dir / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")

# Verify pureness: baseline MUST NOT be modified
post_plan_fingerprint = compute_tree_fingerprint(fixture_steam)
assert baseline_fingerprint == post_plan_fingerprint, "Plan creation modified filesystem!"

print("\n=== [STEP 3] Apply Plan ===")
t1 = time.monotonic()
manifest = apply_installation_plan(plan, fixture_steam)
apply_time = time.monotonic() - t1
print(f"Applied in {apply_time*1000:.2f}ms, installed files: {len(manifest['installed_files'])}")
(log_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

print("\n=== [STEP 4] Verify Manifest on Disk ===")
is_valid, errors = verify_installation_manifest(manifest, fixture_steam)
print(f"Manifest verification valid: {is_valid}, errors: {errors}")
verify_record = {
    "is_valid": is_valid,
    "errors": errors,
    "files_verified": len(manifest['installed_files'])
}
(log_dir / "verify.json").write_text(json.dumps(verify_record, indent=2) + "\n")
assert is_valid, f"Verification failed: {errors}"

print("\n=== [STEP 5] Rollback Installation ===")
t2 = time.monotonic()
rollback_report = rollback_installation_manifest(manifest, fixture_steam)
rollback_time = time.monotonic() - t2
print(f"Rollback completed in {rollback_time*1000:.2f}ms, removed: {len(rollback_report['files_removed'])}")
(log_dir / "rollback_report.json").write_text(json.dumps(rollback_report, indent=2) + "\n")

print("\n=== [STEP 6] Post-Rollback Exact Byte Comparison ===")
final_fingerprint = compute_tree_fingerprint(fixture_steam)
is_byte_exact = (baseline_fingerprint == final_fingerprint)
print(f"Byte-for-byte exact equality restored: {is_byte_exact}")
assert is_byte_exact, "Byte-exact rollback failed!"

print("\n=== [STEP 7] Negative Boundary Test ===")
bad_roots = [
    Path(os.path.expanduser("~/Library/Application Support/Steam")),
    Path("/Applications"),
    Path("/usr/local")
]
rejected_count = 0
for b in bad_roots:
    try:
        create_installation_plan(b, src_tool)
    except SteamPlanError as e:
        print(f"Properly rejected forbidden path '{b}': {e}")
        rejected_count += 1

assert rejected_count == len(bad_roots), "Negative security test failed!"
print(f"All {rejected_count} security boundary tests passed!")

# Summary receipt
receipt = {
    "plan_file": str(log_dir / "plan.json"),
    "manifest_file": str(log_dir / "manifest.json"),
    "verify_file": str(log_dir / "verify.json"),
    "rollback_report_file": str(log_dir / "rollback_report.json"),
    "total_plan_steps": plan["total_steps"],
    "installed_files_count": len(manifest["installed_files"]),
    "created_directories_count": len(manifest["created_directories"]),
    "verification_passed": is_valid,
    "byte_exact_rollback": is_byte_exact,
    "forbidden_paths_rejected": rejected_count,
    "status": "PASS"
}
(log_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(f"\nSaved master receipt to {log_dir / 'receipt.json'}")
