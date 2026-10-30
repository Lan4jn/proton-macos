#!/usr/bin/env python3
"""
run_probe.py - Orchestrator for HVF read-only host mapping probe.

Hardening features:
1. Pre-flight check on all output targets via lexists, symlink checks, and lab boundary checks.
   Halts without compiling, signing, or running if old outputs exist.
2. Backing seed file created exclusively with O_CREAT | O_EXCL (no unlink), fsync, and full write.
3. Strict execution metadata binding (probe_returncode, timed_out, seed SHA256 before/after).
4. Safe decoding of stdout/stderr from subprocess.TimeoutExpired to prevent TypeError.
5. Dynamic report generation reflecting actual test results, controls, and evaluated cases.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from classifier import ProbeClassifier

LAB_DIR = Path("/Users/mewcapoo/Projects/proton-macos-lab")
SCRIPTS_DIR = LAB_DIR / "scripts" / "runtime" / "hvf_readonly_probe"
FIXTURES_DIR = LAB_DIR / "fixtures" / "runtime" / "hvf-readonly-probe"
LOGS_DIR = LAB_DIR / "logs" / "hvf-readonly-probe"
REPORTS_DIR = LAB_DIR / "reports"

PROBE_SRC = SCRIPTS_DIR / "probe.c"
PROBE_BIN = FIXTURES_DIR / "probe"
ENTITLEMENTS = FIXTURES_DIR / "entitlements.plist"
SEED_FILE = FIXTURES_DIR / "backing_seed.bin"
JSONL_LOG = LOGS_DIR / "probe.jsonl"
TEXT_LOG = LOGS_DIR / "probe.log"
REPORT_MD = REPORTS_DIR / "hvf-readonly-probe.md"


def safe_decode(val: Any) -> str:
    """Safely decodes bytes, str, or None to string without raising TypeError."""
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_path_boundary(path: Path, lab_dir: Path = LAB_DIR) -> None:
    """
    Verifies that path is strictly within lab_dir and no parent component is a symlink.
    Fails closed if outside lab_dir or if symlink is detected.
    """
    resolved_lab = lab_dir.resolve()
    try:
        path.resolve().relative_to(resolved_lab)
    except ValueError:
        raise PermissionError(f"Path outside lab boundary: {path}")

    curr = path.parent
    while True:
        if os.path.islink(str(curr)) or curr.is_symlink():
            raise PermissionError(f"Parent directory component cannot be a symlink: {curr}")
        if curr.resolve() == resolved_lab or curr == curr.parent:
            break
        curr = curr.parent


def preflight_check_outputs(output_paths: List[Path], lab_dir: Path = LAB_DIR) -> bool:
    """
    Validates that none of the output targets exist (lexists) or are symlinks.
    Also verifies boundary and parent path safety.
    Returns True if all preflight checks pass (all targets clean/absent).
    Returns False if any target already exists (halt closed).
    Raises PermissionError or ValueError on symlink or boundary violation.
    """
    for p in output_paths:
        verify_path_boundary(p, lab_dir)

        if os.path.islink(str(p)) or p.is_symlink():
            raise PermissionError(f"Output path cannot be a symlink: {p}")

        if os.path.lexists(str(p)):
            return False
    return True


def create_seed_file(path: Path, size: int = 65536, lab_dir: Path = LAB_DIR) -> None:
    """
    Creates backing seed file using O_CREAT | O_EXCL | O_RDWR (and O_NOFOLLOW if available).
    Strictly refuses to unlink existing files. Rejects symlinks.
    Writes full content with fsync and guarantees file descriptor closure.
    """
    verify_path_boundary(path, lab_dir)

    if os.path.islink(str(path)) or path.is_symlink():
        raise PermissionError(f"Seed file path cannot be a symlink: {path}")

    if os.path.lexists(str(path)):
        raise FileExistsError(f"Seed file already exists; unlinking is forbidden: {path}")

    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = os.open(str(path), flags, 0o600)
    try:
        magic = b"HVF_RO_PROBE_MAGIC_SEED_DATA_BLOCK_0x20000000\n"
        content = magic + (b"\xaa\x55\x12\x34" * ((size - len(magic)) // 4))
        if len(content) < size:
            content += b"\x00" * (size - len(content))
        to_write = content[:size]
        written = 0
        while written < len(to_write):
            n = os.write(fd, to_write[written:])
            if n == 0:
                raise IOError("Failed to write full seed file content: 0 bytes written")
            written += n
        os.fsync(fd)
    finally:
        os.close(fd)


def generate_report(
    report_path: Path,
    logs_dir: Path,
    lab_dir: Path,
    src_sha: str,
    bin_sha: str,
    seed_sha_before: str,
    seed_sha_after: str,
    parsed_data: Dict[str, Any],
    classification: Dict[str, Any],
    unit_test_count: Optional[int] = None,
) -> List[str]:
    """Generates the dynamic report (<= 12 lines) without hardcoded test counts or controls."""
    verdict = classification["verdict"]
    reason = classification["reason"]
    vm_create_ok = parsed_data.get("vm_create", {}).get("success", False) if parsed_data.get("vm_create") else False
    vm_destroy_ok = parsed_data.get("vm_destroy", {}).get("success", False) if parsed_data.get("vm_destroy") else False

    cases_by_id = {c.get("case_id"): c for c in parsed_data.get("cases", []) if isinstance(c, dict)}
    ret_a = cases_by_id.get("A", {}).get("hv_map_return_hex", "N/A")
    ret_b = cases_by_id.get("B", {}).get("hv_map_return_hex", "N/A")
    ret_c = cases_by_id.get("C", {}).get("hv_map_return_hex", "N/A")
    ret_d = cases_by_id.get("D", {}).get("hv_map_return_hex", "N/A")

    case_a_ok = cases_by_id.get("A", {}).get("hv_map_success") is True
    case_d_ok = cases_by_id.get("D", {}).get("hv_map_success") is True
    controls_ok = case_a_ok and case_d_ok
    if controls_ok:
        controls_desc = "Positive controls A & D succeeded; no silent retry or Blind Reuse performed."
    else:
        controls_desc = f"Controls: Positive controls failed (Case A={case_a_ok}, Case D={case_d_ok})."

    seed_matched_str = f"matched ({seed_sha_before[:12]}...)" if seed_sha_before == seed_sha_after else f"MISMATCH (before={seed_sha_before[:8]}, after={seed_sha_after[:8]})"

    total_cases = len(cases_by_id)
    if unit_test_count is not None:
        eval_line = f"- Test count: {unit_test_count} unit tests evaluated; 1 live probe execution ({total_cases} cases evaluated)."
    else:
        eval_line = f"- Test count: 1 live probe execution ({total_cases} cases evaluated)."

    rel_logs = logs_dir.relative_to(lab_dir) if logs_dir.is_relative_to(lab_dir) else logs_dir

    report_lines = [
        f"# HVF Read-Only Host Mapping Probe Report",
        f"- Evidence: {rel_logs}/probe.jsonl, {rel_logs}/probe.log",
        eval_line,
        f"- Artifacts: Source SHA {src_sha[:12]}..., Binary SHA {bin_sha[:12]}..., Seed SHA {seed_matched_str}.",
        f"- VM Lifecycle: hv_vm_create={'OK' if vm_create_ok else 'FAILED'}, hv_vm_destroy={'OK' if vm_destroy_ok else 'FAILED'}.",
        f"- Cases: A(anon RWX)={ret_a}, B(file RO->HV_R)={ret_b}, C(file RO->HV_RWX)={ret_c}, D(file RW->HV_RWX)={ret_d}.",
        f"- Admission Verdict: {verdict} ({reason}).",
        f"- Controls: {controls_desc}",
        f"- Unmeasured Scope: vCPU execution, guest address translation coherence, Wine/Proton runtime memory patching.",
    ]
    assert len(report_lines) <= 12, f"Report exceeds 12 lines: {len(report_lines)}"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines) + "\n")

    return report_lines


def run_probe_workflow(
    lab_dir: Path = LAB_DIR,
    scripts_dir: Optional[Path] = None,
    fixtures_dir: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
    reports_dir: Optional[Path] = None,
    subproc_runner: Callable = subprocess.run,
) -> Dict[str, Any]:
    scripts_dir = scripts_dir or (lab_dir / "scripts" / "runtime" / "hvf_readonly_probe")
    fixtures_dir = fixtures_dir or (lab_dir / "fixtures" / "runtime" / "hvf-readonly-probe")
    logs_dir = logs_dir or (lab_dir / "logs" / "hvf-readonly-probe")
    reports_dir = reports_dir or (lab_dir / "reports")

    probe_src = scripts_dir / "probe.c"
    probe_bin = fixtures_dir / "probe"
    entitlements = fixtures_dir / "entitlements.plist"
    seed_file = fixtures_dir / "backing_seed.bin"
    jsonl_log = logs_dir / "probe.jsonl"
    text_log = logs_dir / "probe.log"
    report_md = reports_dir / "hvf-readonly-probe.md"

    log_lines = []

    def log(msg: str):
        print(msg)
        log_lines.append(msg)

    # Pre-flight check: if any output target exists, halt without compilation or execution
    output_targets = [seed_file, probe_bin, jsonl_log, text_log, report_md]
    if not preflight_check_outputs(output_targets, lab_dir=lab_dir):
        log("[PREFLIGHT HALT] Existing outputs detected. Halting without compilation, codesign, or execution.")
        return {
            "halted": True,
            "reason": "EXISTING_OUTPUTS_DETECTED",
        }

    log("=== [1/6] Initializing backing seed file ===")
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    create_seed_file(seed_file, 65536, lab_dir=lab_dir)
    seed_sha_before = sha256_file(seed_file)
    src_sha = sha256_file(probe_src)
    log(f"Seed file created: {seed_file} (size={seed_file.stat().st_size})")
    log(f"Seed file SHA256 (before): {seed_sha_before}")
    log(f"Source SHA256: {src_sha}")

    log("=== [2/6] Compiling probe.c with clang ===")
    compile_cmd = [
        "clang",
        "-Wall",
        "-Wextra",
        "-O2",
        "-framework", "Hypervisor",
        str(probe_src),
        "-o", str(probe_bin),
    ]
    log(f"Running: {' '.join(compile_cmd)}")
    c_res = subproc_runner(compile_cmd, capture_output=True, text=True)
    if c_res.returncode != 0:
        log(f"Compilation failed: {safe_decode(c_res.stderr)}")
        return {"halted": True, "reason": "COMPILATION_FAILED"}
    log("Compilation succeeded.")

    log("=== [3/6] Signing binary with hypervisor entitlement ===")
    sign_cmd = [
        "codesign",
        "--entitlements", str(entitlements),
        "-f",
        "-s", "-",
        str(probe_bin),
    ]
    log(f"Running: {' '.join(sign_cmd)}")
    s_res = subproc_runner(sign_cmd, capture_output=True, text=True)
    if s_res.returncode != 0:
        log(f"Codesign failed: {safe_decode(s_res.stderr)}")
        return {"halted": True, "reason": "CODESIGN_FAILED"}
    log("Codesign succeeded.")

    verify_cmd = ["codesign", "-d", "--entitlements", ":-", str(probe_bin)]
    v_res = subproc_runner(verify_cmd, capture_output=True, text=True)
    v_stdout = safe_decode(v_res.stdout)
    log(f"Verified entitlements:\n{v_stdout.strip()}")
    if "com.apple.security.hypervisor" not in v_stdout:
        log("ERROR: com.apple.security.hypervisor entitlement missing!")
        return {"halted": True, "reason": "ENTITLEMENT_MISSING"}

    bin_sha = sha256_file(probe_bin)
    log(f"Binary SHA256: {bin_sha}")

    log("=== [4/6] Executing probe (single run, timeout: inner 5s, outer 8s) ===")
    run_cmd = [str(probe_bin), str(seed_file)]
    log(f"Executing: {' '.join(run_cmd)}")

    probe_stdout = ""
    probe_stderr = ""
    probe_returncode = -1
    timed_out = False

    try:
        p_res = subproc_runner(
            run_cmd,
            capture_output=True,
            timeout=5.0,
        )
        probe_stdout = safe_decode(p_res.stdout)
        probe_stderr = safe_decode(p_res.stderr)
        probe_returncode = p_res.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        probe_stdout = safe_decode(e.stdout)
        probe_stderr = safe_decode(e.stderr)
        probe_returncode = -1
        log("[TIMEOUT] Probe process timed out after 5.0 seconds")

    log(f"Probe exit code: {probe_returncode} (timed_out={timed_out})")
    if probe_stderr.strip():
        log(f"Probe stderr:\n{probe_stderr.strip()}")

    seed_sha_after = sha256_file(seed_file)
    log(f"Seed file SHA256 (after): {seed_sha_after}")
    log(f"Seed file unchanged: {seed_sha_before == seed_sha_after}")

    log("=== [5/6] Classifying probe output ===")
    classifier = ProbeClassifier()
    parsed_data = classifier.parse_input(probe_stdout)
    classification = classifier.classify_execution(
        parsed_data,
        probe_returncode=probe_returncode,
        timed_out=timed_out,
        seed_sha_before=seed_sha_before,
        seed_sha_after=seed_sha_after,
    )
    log(f"Verdict: {classification['verdict']}")
    log(f"Reason: {classification['reason']}")

    # Save probe JSONL
    logs_dir.mkdir(parents=True, exist_ok=True)
    with open(jsonl_log, "w") as f:
        f.write(probe_stdout)

    # Save full text log
    with open(text_log, "w") as f:
        f.write("\n".join(log_lines) + "\n\nRaw Probe STDOUT:\n" + probe_stdout + "\nRaw Probe STDERR:\n" + probe_stderr)

    log(f"Logs written to {jsonl_log} and {text_log}")

    log("=== [6/6] Generating reports (<= 12 lines) ===")
    report_lines = generate_report(
        report_path=report_md,
        logs_dir=logs_dir,
        lab_dir=lab_dir,
        src_sha=src_sha,
        bin_sha=bin_sha,
        seed_sha_before=seed_sha_before,
        seed_sha_after=seed_sha_after,
        parsed_data=parsed_data,
        classification=classification,
    )
    log(f"Report written to {report_md} ({len(report_lines)} lines)")

    return {
        "halted": False,
        "classification": classification,
        "parsed_data": parsed_data,
        "probe_returncode": probe_returncode,
        "timed_out": timed_out,
        "seed_sha_before": seed_sha_before,
        "seed_sha_after": seed_sha_after,
    }


def main():
    res = run_probe_workflow()
    if res.get("halted"):
        print(f"Workflow halted: {res.get('reason')}")
        sys.exit(0)


if __name__ == "__main__":
    main()
