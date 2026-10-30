#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/runtime/fex_init/diagnostics.py

Pure parsing and classification library for FEX/Proton execution logs.
Safe to import; never executes child processes, network, or long-running commands.
Classify functions are strictly pure without disk I/O side effects.

Core Principles:
1. Strict True Positive: only ':trace:loaddll:build_module Loaded ... libarm64ecfex.dll ... builtin'
   without failure counts as loaded. Prefixes like 'not Loaded' or 'skip Loaded' do not trigger false positives.
2. Strict True Negative: 'could not load ... libarm64ecfex.dll' is explicitly classified as failure.
3. Search strings and probe attempts (e.g. looking_for) are not false positives.
4. error_observed is 'UNKNOWN' when neither error nor success marker is reached.
5. target_entry is strictly decoupled from whole_success.
6. hello-x64.exe stdout with target_exit -11 is classified as PARTIAL_OUTPUT_THEN_CRASH, whole_success=False.
   NtTerminateProcess trace exit_code 0 does not constitute clean process exit 0.
7. Timeout (overall 124) and cleanup_errors prevent whole_success (no false greens).
   For minimal targets, whole_success strictly requires overall exit == target_exit == expected_code.
8. Metadata extraction is an independent function; classify_run_outcome performs zero disk I/O.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

LAB = Path(__file__).resolve().parents[3]


def get_file_sha256(path: Optional[Union[str, Path]]) -> Optional[str]:
    """Compute SHA-256 digest of a local file safely; returns None if path is None or file missing."""
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def extract_run_context_metadata(
    binary_path: Optional[Union[str, Path]] = None,
    target_pe_path: Optional[Union[str, Path]] = None,
    prefix_path: Optional[Union[str, Path]] = None,
) -> Dict:
    """
    Extract contextual reproducibility metadata explicitly from given paths.
    Independent function: does not hardcode non-existent paths.
    """
    fex_dll_exists = False
    ntdll_dll_exists = False
    if prefix_path:
        pfx = Path(prefix_path)
        fex_dll = pfx / "drive_c" / "windows" / "system32" / "libarm64ecfex.dll"
        ntdll_dll = pfx / "drive_c" / "windows" / "system32" / "ntdll.dll"
        fex_dll_exists = fex_dll.is_file()
        ntdll_dll_exists = ntdll_dll.is_file()

    return {
        "binary_sha256": get_file_sha256(binary_path),
        "target_pe_sha256": get_file_sha256(target_pe_path),
        "prefix_path": str(prefix_path) if prefix_path else None,
        "key_dll_resolutions": {
            "libarm64ecfex.dll": fex_dll_exists,
            "ntdll.dll": ntdll_dll_exists,
        },
    }


def classify_fex_module_marker(lines: Union[str, List[str]]) -> Dict[str, Union[bool, Optional[str]]]:
    """
    Parse wine stderr lines for libarm64ecfex.dll load markers.
    Anchored to Wine's loaddll trace prefix to avoid false positives on 'not Loaded' or 'skip Loaded'.
    Returns:
        {
            "loaded": bool,
            "failure": bool,
            "failure_reason": Optional[str]
        }
    """
    if isinstance(lines, str):
        lines = lines.splitlines()

    has_loaded = False
    has_failed = False
    failure_reason = None

    for line in lines:
        # Match error line: e.g. "could not load L\"...\\libarm64ecfex.dll\", status c0000135"
        if re.search(r"could\s+not\s+load\s+.*libarm64ecfex\.dll", line, re.IGNORECASE):
            has_failed = True
            m_status = re.search(r"status\s+([0-9a-fA-F]+)", line)
            if m_status:
                failure_reason = m_status.group(1)
        # Match success line: anchored to loaddll trace prefix or start of line
        elif re.search(r"(?i)(?:^|loaddll:(?:build_module|build_ntdll_module)\s+)Loaded\s+.*libarm64ecfex\.dll.*:\s*builtin", line):
            has_loaded = True

    return {
        "loaded": has_loaded and not has_failed,
        "failure": has_failed,
        "failure_reason": failure_reason,
    }


def classify_error_observed(lines: Union[str, List[str]], fex_loaded: bool) -> Union[bool, str]:
    """
    Classify whether low-address / shim infrastructure collision occurred:
    - True if explicit collision line (e.g. try_map_free_area error) is present.
    - False if FEX module was successfully loaded (code path bypassed collision).
    - 'UNKNOWN' if neither error nor success marker is observed.
    """
    if isinstance(lines, str):
        lines = lines.splitlines()

    has_err = any(
        ("try_map_free_area" in l) or ("Address already in use" in l and "0xfeffff0000" in l)
        for l in lines
    )
    if has_err:
        return True
    if fex_loaded:
        return False
    return "UNKNOWN"


def classify_target_entry(target_name: str, target_exit: Optional[int], stdout_text: str) -> bool:
    """
    Classify whether target execution reached entry point:
    - minimal-arm64.exe: reached entry if exit is 37
    - minimal-x64.exe: reached entry if exit is 43
    - hello-x64.exe: reached entry if stdout contains exact 'X64_FEX_OK'
    """
    if target_name == "minimal-arm64.exe":
        return target_exit == 37
    if target_name == "minimal-x64.exe":
        return target_exit == 43
    if target_name == "hello-x64.exe":
        stdout_lines = stdout_text.splitlines()
        return any(l.strip() == "X64_FEX_OK" for l in stdout_lines)
    return False


def classify_run_outcome(
    target_name: str,
    res: Dict,
    stdout_text: str,
    stderr_text: str,
    elfuse_flavor: str = "derived",
    metadata: Optional[Dict] = None,
) -> Dict:
    """
    Pure structured classifier for a run_isolated result.
    Decouples target_entry, partial crashes, and whole_success.
    Performs zero disk I/O side effects.
    """
    lines = stderr_text.splitlines()
    fex_info = classify_fex_module_marker(lines)
    fex_loaded = fex_info["loaded"]
    fex_failure = fex_info["failure"]

    error_obs = classify_error_observed(lines, fex_loaded=fex_loaded)
    target_exit = res.get("target_exit")
    exit_code = res.get("exit")
    timed_out = res.get("timed_out", False)
    cleanup_errors = res.get("cleanup_errors", [])

    target_entry = classify_target_entry(target_name, target_exit, stdout_text)

    # Detect partial output then crash (hello stdout reached, but process crashed)
    partial_crash = False
    if target_name == "hello-x64.exe" and target_entry:
        if target_exit == -11 or (target_exit is not None and target_exit < 0):
            partial_crash = True

    # Whole success criteria:
    # Requires zero timeouts (timed_out=False and exit!=124), zero cleanup errors,
    # not partial_crash, target_entry=True, and overall exit matching expected target exit code.
    whole_success = False
    if not timed_out and exit_code != 124 and not cleanup_errors and not partial_crash and target_entry:
        if target_name == "hello-x64.exe":
            whole_success = (exit_code == 0 and target_exit == 0)
        elif target_name == "minimal-x64.exe":
            whole_success = (exit_code == 43 and target_exit == 43)
        elif target_name == "minimal-arm64.exe":
            whole_success = (exit_code == 37 and target_exit == 37)

    # Derive high-level status string
    if timed_out or exit_code == 124:
        status = "TIMEOUT"
    elif cleanup_errors:
        status = "CLEANUP_FAILED"
    elif partial_crash:
        status = "PARTIAL_OUTPUT_THEN_CRASH"
    elif whole_success:
        status = "WHOLE_SUCCESS"
    elif target_entry:
        status = "TARGET_ENTRY_REACHED"
    elif fex_failure:
        status = "FEX_MODULE_LOAD_FAILED"
    elif fex_loaded:
        status = "FEX_MODULE_LOADED_NO_ENTRY"
    else:
        status = "NOT_LOADED"

    return {
        "target": target_name,
        "elfuse_flavor": elfuse_flavor,
        "status": status,
        "whole_success": whole_success,
        "partial_output_then_crash": partial_crash,
        "target_entry": target_entry,
        "fex_module_marker": fex_loaded,
        "fex_module_load_failure": fex_failure,
        "fex_failure_reason": fex_info["failure_reason"],
        "error_observed": error_obs,
        "timeout": timed_out,
        "exit": exit_code,
        "target_exit": target_exit,
        "supervisor_exit": res.get("supervisor_exit"),
        "seconds": res.get("seconds"),
        "cleanup_errors": cleanup_errors,
        "run_dir": res.get("run_dir"),
        "stderr_lines_count": len(lines),
        "metadata": metadata,
    }
