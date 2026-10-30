#!/usr/bin/env python3
"""
scripts/integration/check_prerequisites.py

Deterministic Integration Prerequisite Checker.
Supports both:
1. Default direct mode: Reads artifacts/proton/identity.json, validates elfuse baseline execution,
   and strictly determines Wine / FEX execution readiness without synthesizing third-party packages.
2. Public manifest mode (--public-manifest): Reads public Proton bundle manifest (artifacts/public-proton/bundle.json),
   verifies publisher checksums via backend bundle verification, and strictly differentiates:
   - PUBLIC_REDISTRIBUTION_VERIFIED (publisher checksums verified, Valve origin claimed, not independently signed)
   - FULL_PROTON_NOT_VALIDATED (full Proton Python launcher entered wineboot but not validated)
   - X64_NOT_VERIFIED (Windows x64 PE execution through FEX has not succeeded / in-progress)

Exit Codes:
   0 : Direct Steam mode prerequisites READY for execution testing (does NOT prove game/Windows execution)
   1 : elfuse baseline execution FAILED or missing
   2 : CLI argument / usage error or missing file
  10 : Public manifest verified, but execution remains unvalidated (this tool only checks prerequisites; no auto-pass)
  20 : Direct Steam package acquisition BLOCKED (or public bundle verification failed)
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def evaluate_prerequisites(identity_data, elfuse_verified: bool):
    raw_path = identity_data.get("local_package_path")
    local_path = raw_path.strip() if isinstance(raw_path, str) else None
    is_blocked = identity_data.get("download_blocked", True)
    sha256 = identity_data.get("sha256")

    package_status = "READY"
    blocker_reason = None

    if not local_path or is_blocked:
        package_status = "BLOCKED"
        blocker_reason = (
            "Official package missing: Steam depot App 4427310 / Depot 4427311 "
            "requires authenticated subscription (ownersonly)."
        )
    else:
        pkg_path = Path(local_path)
        if not pkg_path.exists() or not pkg_path.is_dir():
            package_status = "BLOCKED"
            blocker_reason = f"Specified package path does not exist or is not a directory: {local_path}"
        elif sha256 is None or identity_data.get("acquisition_status") != "verified":
            package_status = "LOCAL_PATH_PRESENT_UNVERIFIED"
            blocker_reason = (
                f"Directory exists at {local_path} but package SHA-256 and identity "
                "have not been verified against official manifest."
            )

    elfuse_status = "VERIFIED" if elfuse_verified else "FAILED"

    # Strict separation: Wine/FEX cannot be run unless BOTH elfuse and package are ready
    if elfuse_status != "VERIFIED" or package_status != "READY":
        wine_status = "NOT_RUN"
        fex_status = "NOT_RUN"
    else:
        wine_status = "PENDING_EXECUTION"
        fex_status = "PENDING_EXECUTION"

    return {
        "elfuse_status": elfuse_status,
        "package_status": package_status,
        "blocker_reason": blocker_reason,
        "wine_execution_status": wine_status,
        "fex_execution_status": fex_status,
        "upstream_app_id": identity_data.get("app_id", 4427310),
        "upstream_depot_id": identity_data.get("depot_id", 4427311),
    }


def evaluate_public_manifest(manifest_path: Path, elfuse_verified: bool, lab_root: Path):
    manifest_p = Path(manifest_path).resolve()
    if not manifest_p.exists() or not manifest_p.is_file():
        raise FileNotFoundError(f"Missing public manifest file: {manifest_path}")

    # Add lab_root to sys.path to load scripts.backend.bundle
    if str(lab_root) not in sys.path:
        sys.path.insert(0, str(lab_root))

    try:
        from scripts.backend.bundle import verify_bundle
        bundle_info = verify_bundle(manifest_p)
        bundle_verified = True
        verification_error = None
    except Exception as e:
        bundle_info = {}
        bundle_verified = False
        verification_error = str(e)

    elfuse_status = "VERIFIED" if elfuse_verified else "FAILED"

    if not bundle_verified:
        package_status = "CORRUPTED"
        package_detail = f"Public bundle verification failed: {verification_error}"
        blocker_reason = f"Public bundle verification failed: {verification_error}"
        full_proton_status = "NOT_RUN"
        full_proton_detail = "Bundle checksum verification failed; cannot run Proton launcher."
        x64_status = "NOT_RUN"
        x64_detail = "Bundle checksum verification failed; cannot run x64 PE emulation."
        wine_status = "NOT_RUN"
        wine_detail = "Bundle checksum verification failed; cannot run Wine components."
    else:
        package_status = "PUBLIC_REDISTRIBUTION_VERIFIED"
        package_detail = "Publisher checksums verified; Valve origin claimed; independent Valve signature NOT verified"
        blocker_reason = None
        if elfuse_status == "VERIFIED":
            full_proton_status = "FULL_PROTON_NOT_VALIDATED"
            full_proton_detail = (
                "Proton Python compatibility launcher requires Linux Python and rootfs; "
                "execution is not validated by this prerequisite check (historical experiments documented in reports/public-proton.md and logs/runtime/)."
            )
            wine_status = "COMPONENT_EXECUTION_NOT_CHECKED"
            wine_detail = "Direct Wine component execution is not checked by this prerequisite tool."
            x64_status = "X64_NOT_VERIFIED"
            x64_detail = (
                "Windows x64 PE execution through FEX has not been verified by this prerequisite check tool "
                "(requires verified stdout and exit 0 from test harness)."
            )
        else:
            full_proton_status = "NOT_RUN"
            full_proton_detail = "elfuse baseline failed; full Proton launcher cannot run."
            wine_status = "NOT_RUN"
            wine_detail = "elfuse baseline failed; Wine components cannot run."
            x64_status = "NOT_RUN"
            x64_detail = "elfuse baseline failed; x64 PE execution cannot run."

    return {
        "elfuse_status": elfuse_status,
        "package_status": package_status,
        "package_detail": package_detail,
        "publisher": bundle_info.get("publisher", "The412Banner/winlator-contents"),
        "provenance": bundle_info.get("provenance", "PUBLIC_REDISTRIBUTOR_CHECKSUM_VERIFIED_VALVE_ORIGIN_CLAIMED"),
        "independent_valve_signature_verified": bundle_info.get("independent_valve_signature_verified", False),
        "upstream_app_id": bundle_info.get("app", 4427310),
        "upstream_depot_id": bundle_info.get("depot", 4427311),
        "upstream_build_id": bundle_info.get("build", 25502785),
        "archive_sha256": bundle_info.get("archive_sha256"),
        "full_proton_status": full_proton_status,
        "full_proton_detail": full_proton_detail,
        "wine_execution_status": wine_status,
        "wine_execution_detail": wine_detail,
        "x64_execution_status": x64_status,
        "x64_execution_detail": x64_detail,
        "blocker_reason": blocker_reason,
    }


def generate_conclusion(results: dict) -> str:
    lines = []
    if results["elfuse_status"] != "VERIFIED":
        lines.append("Conclusion: Baseline ELF execution (elfuse) FAILED.")
        lines.append("            Wine / FEX tests CANNOT RUN.")
    elif results["package_status"] == "BLOCKED":
        lines.append("Conclusion: Execution blocked at official package acquisition (Exit 20).")
        lines.append("            No third-party packages substituted.")
        lines.append("            ELF execution capability verified; Wine / FEX tests NOT RUN.")
    elif results["package_status"] == "LOCAL_PATH_PRESENT_UNVERIFIED":
        lines.append("Conclusion: Local directory present but UNVERIFIED (Exit 20).")
        lines.append("            Run scripts/proton/audit_proton.py before execution.")
        lines.append("            Wine / FEX tests NOT RUN pending package validation.")
    elif results["package_status"] == "READY":
        lines.append("Conclusion: Prerequisites READY for Wine / FEX execution testing (Exit 0).")
        lines.append("            (Prerequisites verified; execution tests pending).")
    else:
        lines.append("Conclusion: Unknown prerequisite state.")
    return "\n".join(lines)


def generate_public_conclusion(results: dict) -> str:
    lines = []
    if results["elfuse_status"] != "VERIFIED":
        lines.append("Conclusion: Baseline ELF execution (elfuse) FAILED (Exit 1).")
        lines.append("            Wine / FEX tests CANNOT RUN.")
    elif results["package_status"] != "PUBLIC_REDISTRIBUTION_VERIFIED":
        lines.append(f"Conclusion: Public bundle verification FAILED (Exit 20): {results.get('blocker_reason')}")
    else:
        lines.append("Conclusion: Public Proton package checksums verified by publisher manifest (Exit 10).")
        lines.append("            Status: PUBLIC_REDISTRIBUTION_VERIFIED")
        lines.append("            Valve origin claimed but NOT independently signed by Valve.")
        lines.append("            Wine Component Execution : COMPONENT_EXECUTION_NOT_CHECKED")
        lines.append("            Full Proton Launcher     : FULL_PROTON_NOT_VALIDATED")
        lines.append("            Windows x64 Execution    : X64_NOT_VERIFIED")
        lines.append("            Notice: A command plan or package checksum is NOT evidence of Windows execution success.")
        lines.append("            CLI returns Exit 10 (unvalidated runtime state); no automated passing is claimed.")
    return "\n".join(lines)


def verify_elfuse(lab_root: Path):
    elfuse_bin = lab_root / "sources" / "elfuse" / "build" / "elfuse"
    fixture_hello = lab_root / "fixtures" / "elfuse" / "hello"

    if not elfuse_bin.exists() or not os.access(elfuse_bin, os.X_OK):
        return False, "elfuse binary missing or not executable"
    if not fixture_hello.exists():
        return False, "fixtures/elfuse/hello fixture missing"

    cmd = [str(elfuse_bin), "--timeout", "5", str(fixture_hello)]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and "hello" in proc.stdout.strip():
            return True, proc.stdout.strip()
        return False, f"Non-zero exit or bad output: code={proc.returncode}, stdout={proc.stdout.strip()}"
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Check Proton Integration Prerequisites")
    parser.add_argument("--lab-root", type=str, default=None, help="Root path of proton-macos-lab")
    parser.add_argument("--public-manifest", type=str, default=None, help="Path to public Proton bundle manifest (e.g. artifacts/public-proton/bundle.json)")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    if args.lab_root:
        lab_root = Path(args.lab_root).resolve()
    else:
        lab_root = Path(__file__).resolve().parent.parent.parent

    elfuse_ok, elfuse_detail = verify_elfuse(lab_root)

    if args.public_manifest:
        manifest_path = Path(args.public_manifest)
        if not manifest_path.is_absolute():
            manifest_path = (lab_root / manifest_path).resolve()

        if not manifest_path.exists() or not manifest_path.is_file():
            print(f"[ERROR] Missing public manifest file: {manifest_path}", file=sys.stderr)
            sys.exit(2)

        results = evaluate_public_manifest(manifest_path, elfuse_verified=elfuse_ok, lab_root=lab_root)
        results["elfuse_detail"] = elfuse_detail
        conclusion_text = generate_public_conclusion(results)
        results["conclusion"] = conclusion_text

        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print("==========================================================")
            print("Proton Integration Prerequisite Check (Public Manifest Mode)")
            print("==========================================================")
            print(f"ELF Runtime Baseline (elfuse) : {results['elfuse_status']} ({elfuse_detail})")
            print(f"Package Acquisition Status    : {results['package_status']}")
            print(f"Publisher / Provenance        : {results['publisher']} ({results['provenance']})")
            print(f"Independent Valve Signature   : {results['independent_valve_signature_verified']}")
            print(f"Wine Component Execution      : {results['wine_execution_status']}")
            print(f"Full Proton Launcher Status   : {results['full_proton_status']}")
            print(f"FEX x64 Emulation Status      : {results['x64_execution_status']}")
            print("==========================================================")
            print(conclusion_text)

        # Exit codes in public manifest mode:
        # 1: elfuse failed
        # 20: public bundle corrupted/unverified
        # 10: public redistribution verified, but x64 execution / full proton not verified
        # 0: all verified (including x64)
        if results["elfuse_status"] != "VERIFIED":
            sys.exit(1)
        elif results["package_status"] != "PUBLIC_REDISTRIBUTION_VERIFIED":
            sys.exit(20)
        elif results["x64_execution_status"] != "VERIFIED":
            sys.exit(10)
        else:
            sys.exit(0)

    else:
        # Default direct mode: check artifacts/proton/identity.json
        identity_file = lab_root / "artifacts" / "proton" / "identity.json"
        if not identity_file.exists():
            print(f"[ERROR] Missing identity file: {identity_file}", file=sys.stderr)
            sys.exit(2)

        try:
            with open(identity_file, "r", encoding="utf-8") as f:
                identity_data = json.load(f)
        except Exception as e:
            print(f"[ERROR] Failed to read identity file: {e}", file=sys.stderr)
            sys.exit(2)

        results = evaluate_prerequisites(identity_data, elfuse_verified=elfuse_ok)
        results["elfuse_detail"] = elfuse_detail

        conclusion_text = generate_conclusion(results)
        results["conclusion"] = conclusion_text

        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print("==========================================================")
            print("Proton Integration Prerequisite Check (Direct Steam Mode)")
            print("==========================================================")
            print(f"ELF Runtime Baseline (elfuse) : {results['elfuse_status']} ({elfuse_detail})")
            print(f"Proton Package Acquisition    : {results['package_status']}")
            if results["blocker_reason"]:
                print(f"  - Reason: {results['blocker_reason']}")
            print(f"Wine / wineserver Execution   : {results['wine_execution_status']}")
            print(f"FEX x64 Emulation Execution   : {results['fex_execution_status']}")
            print("==========================================================")
            print(conclusion_text)

        if results["elfuse_status"] != "VERIFIED":
            sys.exit(1)
        elif results["package_status"] in ("BLOCKED", "LOCAL_PATH_PRESENT_UNVERIFIED"):
            sys.exit(20)
        elif results["package_status"] == "READY":
            sys.exit(0)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
