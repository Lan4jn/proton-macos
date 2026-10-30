#!/usr/bin/env bash
# run_all_baseline.sh - elfuse HVF/ELF baseline verification runner
#
# Runs baseline positive and negative test fixtures under elfuse on macOS ARM64 HVF.
# Enforces strict assertions on exit codes and stdout/stderr patterns.
# Returns non-zero overall exit code if any fixture fails.
#
# Constraints & Guarantees:
#   - Confined strictly to lab directory; no /tmp usage.
#   - Preserves all fixture full outputs in a dedicated logs/elfuse/run.XXXXXX directory without deletion.
#   - Does not overwrite existing log files or create/overwrite symlinks.
#   - Supports ELFUSE_BIN environment variable override for testing fake/alternative binaries.
#   - Validates that any user-supplied --log path lies within the lab and does not already exist.

set -uo pipefail

# 1. Resolve repository root dynamically
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

LOGS_DIR="$REPO_ROOT/logs/elfuse"
FIXTURES_DIR="$REPO_ROOT/fixtures/elfuse"
DEFAULT_ELFUSE="$REPO_ROOT/sources/elfuse/build/elfuse"
ELFUSE_BIN="${ELFUSE_BIN:-$DEFAULT_ELFUSE}"

mkdir -p "$LOGS_DIR" "$FIXTURES_DIR"

# Create a dedicated run directory inside lab logs/elfuse/ for this execution
RUN_DIR="$(mktemp -d "$LOGS_DIR/run.XXXXXX")"

# 2. Parse arguments
LOG_PATH="${LOG:-}"
while [ $# -gt 0 ]; do
    case "$1" in
        --log)
            if [ $# -lt 2 ] || [ -z "$2" ]; then
                echo "ERROR: --log requires a non-empty path argument" >&2
                exit 2
            fi
            LOG_PATH="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--log <path>]"
            echo "  ELFUSE_BIN: Override path to elfuse binary (default: $DEFAULT_ELFUSE)"
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option '$1'" >&2
            exit 2
            ;;
    esac
done

if [ -n "$LOG_PATH" ]; then
    # Resolve absolute path for validation
    resolved_dir=""
    target_dir="$(dirname "$LOG_PATH")"
    if [ ! -d "$target_dir" ]; then
        echo "ERROR: directory for log file does not exist: $target_dir" >&2
        exit 2
    fi
    abs_target_dir="$(cd "$target_dir" && pwd)"
    resolved_log="${abs_target_dir}/$(basename "$LOG_PATH")"

    # Enforce lab boundary: resolved log must reside within REPO_ROOT
    case "$resolved_log" in
        "$REPO_ROOT"/*|"$REPO_ROOT")
            ;;
        *)
            echo "ERROR: --log path '$LOG_PATH' (resolved '$resolved_log') is outside lab root '$REPO_ROOT'" >&2
            exit 2
            ;;
    esac

    # Enforce non-overwrite: refuse if log file already exists
    if [ -e "$resolved_log" ]; then
        echo "ERROR: log file '$resolved_log' already exists; refusing to overwrite existing evidence" >&2
        exit 2
    fi
    FINAL_LOG_PATH="$resolved_log"
else
    FINAL_LOG_PATH="$RUN_DIR/suite.log"
fi

# Setup logging: redirect stdout & stderr to log file while printing to console
exec > >(tee -a "$FINAL_LOG_PATH") 2>&1

echo "============================================================"
echo " elfuse HVF/ELF Baseline Test Suite"
echo " Date: $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
echo " Host: $(uname -sm) ($(sw_vers -productVersion 2>/dev/null || echo 'macOS'))"
echo " Lab Root: $REPO_ROOT"
echo " Binary: $ELFUSE_BIN"
echo " Run Directory: $RUN_DIR"
echo " Suite Log: $FINAL_LOG_PATH"
echo "============================================================"

# Check binary existence
if [ ! -x "$ELFUSE_BIN" ]; then
    echo "ERROR: elfuse binary not found or not executable at $ELFUSE_BIN"
    exit 1
fi

TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

run_test() {
    local test_name="$1"
    local expected_rc="$2"
    local expected_pattern="$3"
    shift 3
    local cmd=("$@")

    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    echo ""
    echo "------------------------------------------------------------"
    echo "[TEST $TOTAL_TESTS] $test_name"
    echo "Command: ${cmd[*]}"
    echo "Expected Exit Code: $expected_rc"
    echo "Expected Pattern: '$expected_pattern'"

    local out_file="$RUN_DIR/test_${TOTAL_TESTS}.stdout"

    local start_time
    start_time="$(python3 -c 'import time; print(time.time())')"

    # Run command directly and save unabridged output in lab run directory
    "${cmd[@]}" > "$out_file" 2>&1
    local actual_rc=$?

    local end_time
    end_time="$(python3 -c 'import time; print(time.time())')"
    local elapsed
    elapsed="$(python3 -c "print(f'{$end_time - $start_time:.4f}')")"

    echo "Actual Exit Code: $actual_rc"
    echo "Elapsed Time: ${elapsed}s"
    echo "Full Output Preserved at: $out_file"
    echo "Output Preview:"
    head -n 20 "$out_file"
    local line_count
    line_count="$(wc -l < "$out_file" | tr -d ' ')"
    if [ "$line_count" -gt 20 ]; then
        echo "... [$line_count lines total, full output preserved in $out_file]"
    fi

    local test_ok=1

    # Check exit code
    if [ "$actual_rc" -ne "$expected_rc" ]; then
        echo "FAIL: Exit code mismatch (expected $expected_rc, got $actual_rc)"
        test_ok=0
    fi

    # Check expected pattern
    if ! grep -q -E "$expected_pattern" "$out_file"; then
        echo "FAIL: Output did not match expected pattern '$expected_pattern'"
        test_ok=0
    fi

    if [ "$test_ok" -eq 1 ]; then
        echo "RESULT: PASS"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        echo "RESULT: FAIL"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
}

# --- Pre-run: Verify Codesign Entitlements ---
echo ""
echo "--- Codesign & Entitlements Inspection ---"
codesign -v "$ELFUSE_BIN" || echo "codesign check returned non-zero (ignored for fake binary tests)"
codesign -d --entitlements :- "$ELFUSE_BIN" 2>&1 || true

# --- Test 1: Minimal Assembly Hello (write + exit 0) ---
run_test \
    "Assembly write(1, msg, 6) + exit(0)" \
    0 \
    "^hello$" \
    "$ELFUSE_BIN" --timeout 5 "$FIXTURES_DIR/hello"

# --- Test 2: Freestanding C Linux ELF (write + exit 42) ---
run_test \
    "Freestanding C Linux ELF (exit 42)" \
    42 \
    "Freestanding C ELF on HVF" \
    "$ELFUSE_BIN" --timeout 5 "$FIXTURES_DIR/test_freestanding"

# --- Test 3: mmap + JIT Dynamic Execution ---
run_test \
    "mmap RW -> write AArch64 code -> mprotect RX -> JIT exec" \
    0 \
    "mmap\+JIT success: computed 77" \
    "$ELFUSE_BIN" --timeout 5 "$FIXTURES_DIR/test_mmap_jit"

# --- Test 4: clone(SIGCHLD) + wait4 Process Lifecycle ---
run_test \
    "clone(SIGCHLD) child creation + wait4 status reaping" \
    0 \
    "Parent reaped child exit code 10" \
    "$ELFUSE_BIN" --timeout 5 "$FIXTURES_DIR/test_fork"

# --- Test 5: Dynamic Linker ld-linux-aarch64.so.1 Direct Execution ---
LD_SO="$REPO_ROOT/sources/elfuse/externals/test-fixtures/glibc/2.36-9+deb12u14/ld-linux-aarch64.so.1"
run_test \
    "glibc ld-linux-aarch64.so.1 dynamic interpreter diagnostic" \
    0 \
    "Usage: .*ld-linux-aarch64\.so\.1" \
    "$ELFUSE_BIN" --timeout 5 "$LD_SO" --help

# --- Negative Test 1: Nonexistent ELF File ---
run_test \
    "Negative: Nonexistent ELF file rejection" \
    1 \
    "cannot read /nonexistent_file_for_test|No such file or directory" \
    "$ELFUSE_BIN" --timeout 5 /nonexistent_file_for_test

# --- Negative Test 2: Corrupted/Truncated ELF File ---
printf '\x7fELF\x02\x01\x01\x00truncated_bad_data' > "$FIXTURES_DIR/corrupted.elf"
run_test \
    "Negative: Corrupted/Truncated ELF header rejection" \
    1 \
    "failed to read ELF header|failed to load ELF" \
    "$ELFUSE_BIN" --timeout 5 "$FIXTURES_DIR/corrupted.elf"

# Summary
echo ""
echo "============================================================"
echo " Test Summary: $TOTAL_TESTS executed"
echo " Passed: $PASSED_TESTS"
echo " Failed: $FAILED_TESTS"
echo " Artifacts retained in: $RUN_DIR"
echo "============================================================"

if [ "$FAILED_TESTS" -gt 0 ]; then
    echo "SUITE STATUS: FAILED ($FAILED_TESTS test(s) failed)"
    exit 1
else
    echo "SUITE STATUS: ALL TESTS PASSED"
    exit 0
fi
