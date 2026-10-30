#!/usr/bin/env python3
"""
scripts/runtime/fex_phase_control/test_phase_classifier.py

Pure offline unit tests for Arm A and Arm B classification rules:
- Proves negative cases (exit 124 timeout, exit -11 crash, missing X64_FEX_OK, cleanup failure)
  are NEVER falsely classified as SUCCESS.
- Proves positive case requires ALL of:
  exit == 0, target_exit == 0, timed_out is False, 'X64_FEX_OK' in stdout, cleanup_errors == [].
- Proves phase marker extraction for Arm B (INIT_ENTER, THROW_ENTER, etc.).
"""

import sys

def classify_run(exit_code: int, target_exit: int, timed_out: bool, stdout_text: str, stderr_text: str, cleanup_errors: list) -> dict:
    has_marker = "X64_FEX_OK" in stdout_text
    has_cleanup_err = len(cleanup_errors) > 0
    fex_loaded = ("libarm64ecfex.dll" in stderr_text and "builtin" in stderr_text) or ("libarm64ecfex" in stderr_text)

    # Extract phase markers
    phase_markers = [l.strip() for l in stderr_text.splitlines() if "[PHASE_TRACE]" in l]
    badalloc_traces = [l.strip() for l in stderr_text.splitlines() if "[BADALLOC_TRACE]" in l]

    if timed_out or exit_code == 124 or target_exit == 124:
        classification = "TIMEOUT_BEFORE_PE" if not has_marker else "TIMEOUT_AFTER_OUTPUT"
        is_success = False
    elif has_cleanup_err:
        classification = "CLEANUP_FAILURE"
        is_success = False
    elif exit_code == 0 and target_exit == 0 and has_marker and not timed_out:
        classification = "SUCCESS_PE_OUTPUT_CLEAN_EXIT0"
        is_success = True
    elif exit_code == -11 or target_exit == -11:
        classification = "HOST_SIGSEGV_CRASH"
        is_success = False
    elif exit_code != 0:
        classification = f"FAILURE_EXIT_{exit_code}"
        is_success = False
    elif not has_marker:
        classification = "FAILURE_MISSING_OUTPUT_MARKER"
        is_success = False
    else:
        classification = "UNKNOWN_OUTCOME"
        is_success = False

    return {
        "classification": classification,
        "is_success": is_success,
        "has_fex_ok_marker": has_marker,
        "fex_loaded": fex_loaded,
        "phase_marker_count": len(phase_markers),
        "phase_markers": phase_markers,
        "badalloc_trace_count": len(badalloc_traces),
    }

def run_tests():
    fails = 0

    # 1. Negative Case: Timeout 124 with no output
    c = classify_run(exit_code=124, target_exit=None, timed_out=True, stdout_text="", stderr_text="wine-preloader watchdog", cleanup_errors=[])
    if c["is_success"] is not False or c["classification"] != "TIMEOUT_BEFORE_PE":
        print("FAIL: test 1 timeout not rejected"); fails += 1

    # 2. Negative Case: Exit 0 but missing X64_FEX_OK
    c = classify_run(exit_code=0, target_exit=0, timed_out=False, stdout_text="Some other output", stderr_text="Loaded dll", cleanup_errors=[])
    if c["is_success"] is not False or c["classification"] != "FAILURE_MISSING_OUTPUT_MARKER":
        print("FAIL: test 2 missing marker not rejected"); fails += 1

    # 3. Negative Case: Output present but target crashed with -11
    c = classify_run(exit_code=-11, target_exit=-11, timed_out=False, stdout_text="X64_FEX_OK", stderr_text="SIGSEGV", cleanup_errors=[])
    if c["is_success"] is not False or c["classification"] != "HOST_SIGSEGV_CRASH":
        print("FAIL: test 3 crash not rejected"); fails += 1

    # 4. Negative Case: Exit 0 and output present, but cleanup_errors non-empty
    c = classify_run(exit_code=0, target_exit=0, timed_out=False, stdout_text="X64_FEX_OK", stderr_text="clean", cleanup_errors=["orphan left"])
    if c["is_success"] is not False or c["classification"] != "CLEANUP_FAILURE":
        print("FAIL: test 4 cleanup error not rejected"); fails += 1

    # 5. Positive Case: Exit 0, Target 0, not timed out, marker present, no cleanup errors
    c = classify_run(exit_code=0, target_exit=0, timed_out=False, stdout_text="X64_FEX_OK\n", stderr_text="Loaded builtin", cleanup_errors=[])
    if c["is_success"] is not True or c["classification"] != "SUCCESS_PE_OUTPUT_CLEAN_EXIT0":
        print("FAIL: test 5 positive case failed"); fails += 1

    # 6. Arm B Phase Extraction Test: Validates markers are parsed from stderr
    stderr_sample = (
        "[PHASE_TRACE] INIT_ENTER\n"
        "[PHASE_TRACE] INIT_DONE\n"
        "trace:loaddll:Loaded builtin\n"
    )
    c = classify_run(exit_code=0, target_exit=0, timed_out=False, stdout_text="X64_FEX_OK", stderr_text=stderr_sample, cleanup_errors=[])
    if c["phase_marker_count"] != 2 or "[PHASE_TRACE] INIT_ENTER" not in c["phase_markers"]:
        print("FAIL: test 6 phase marker extraction failed"); fails += 1

    if fails == 0:
        print("ALL 6 PURE CLASSIFIER UNIT TESTS PASSED.")
        return 0
    else:
        print(f"CLASSIFIER TESTS FAILED: {fails} failures.")
        return 1

if __name__ == "__main__":
    sys.exit(run_tests())
