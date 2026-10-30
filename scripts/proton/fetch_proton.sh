#!/usr/bin/env bash
# scripts/proton/fetch_proton.sh
#
# Metadata inspector and anonymous acquisition probe for official Valve Proton Experimental (ARM64)
# App ID: 4427310, Depot ID: 4427311
#
# Design and Safety Contract:
# - Pre-evaluates package size metadata against 8 GiB limit BEFORE any fetch action (clearly marked as historical metadata estimate).
# - Explicitly disallows in-session authenticated downloads (--username) to protect credentials;
#   prompts the user to stage packages manually into artifacts/proton/raw.
# - Enforces strict process timeouts (35s) and isolated TMPDIR/HOME environments.
# - Preserves ALL historical and new logs in separate mktemp directories (logs/proton/check.XXXXXX); never overwrites or deletes logs.
# - Separates Stage 1 (app_info) and Stage 2 (app_update) into independent log files.
# - Differentiates exit codes:
#     0  : Size pre-evaluation check passed
#     2  : Command syntax / argument error or disabled feature
#     10 : Unknown state / Network failure / Timeout / Non-conclusive error
#     20 : Confirmed acquisition blocker (Steam authentication / No subscription)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TOOLS_DIR="${SCRIPT_DIR}/tools"
STEAMCMD_DIR="${TOOLS_DIR}/steamcmd"
STEAMCMD_HOME="${STEAMCMD_DIR}/home"
STEAMCMD_TMP="${STEAMCMD_DIR}/tmp"
LOGS_DIR="${LAB_ROOT}/logs/proton"
ARTIFACTS_DIR="${LAB_ROOT}/artifacts/proton"

APP_ID="4427310"
DEPOT_ID="4427311"
MAX_SIZE_BYTES=8589934592 # 8 GiB (8,589,934,592 bytes)

# Historical upstream metadata estimate (App 4427310 / Depot 4427311, Source: SteamDB 2026-09-21, Build 25406135)
ESTIMATED_DISK_SIZE_BYTES=2083000000     # ~1.94 GiB
ESTIMATED_DOWNLOAD_SIZE_BYTES=497455000   # ~474.41 MiB
METADATA_OBSERVED_DATE="2026-09-21"
METADATA_BUILD_ID="25406135"

TIMEOUT_SECONDS=35
STEAMCMD_EXEC="${STEAMCMD_BIN:-${STEAMCMD_DIR}/steamcmd.sh}"

mkdir -p "${TOOLS_DIR}" "${LOGS_DIR}" "${ARTIFACTS_DIR}" "${STEAMCMD_HOME}/Library/Application Support" "${STEAMCMD_TMP}"

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --check-only     Run isolated anonymous SteamCMD probe to verify depot accessibility and auth blocker.
  --eval-size      Pre-evaluate package metadata sizes against the 8 GiB safety threshold.
  --username <USR> [DISABLED] In-lab authenticated download is disabled to prevent credential leakage.
  -h, --help       Display this help message and exit.

Exit Codes:
   0 : Success / Pre-evaluation check passed
   2 : Argument or syntax error
  10 : Network failure, curl/tar error, unexpected failure, or timeout (unknown outcome)
  20 : Verified blocked by Steam authentication (No subscription / ownersonly)
EOF
}

evaluate_size_metadata() {
    echo "=========================================================="
    echo "Historical Metadata Estimate for App ${APP_ID} Depot ${DEPOT_ID}"
    echo "=========================================================="
    echo "  - Metadata Source     : SteamDB public record"
    echo "  - Recorded Date       : ${METADATA_OBSERVED_DATE}"
    echo "  - Build ID            : ${METADATA_BUILD_ID}"
    echo "  - Est. Disk Size      : ~1.94 GiB (${ESTIMATED_DISK_SIZE_BYTES} bytes)"
    echo "  - Est. Download Size  : ~474.41 MiB (${ESTIMATED_DOWNLOAD_SIZE_BYTES} bytes)"
    echo "  - Safety Threshold    : 8.00 GiB (${MAX_SIZE_BYTES} bytes)"
    echo ""
    echo "[DISCLAIMER] The above values are historical metadata estimates and do NOT constitute"
    echo "             an absolute guarantee of current remote package size."

    if (( ESTIMATED_DISK_SIZE_BYTES > MAX_SIZE_BYTES )); then
        echo "[ERROR] Pre-evaluation failed: Estimated size exceeds 8 GiB threshold!"
        return 20
    fi
    echo "[PASS] Pre-evaluation passed: Estimated size is well below 8 GiB safety threshold."
    return 0
}

ensure_steamcmd() {
    if [[ ! -x "${STEAMCMD_EXEC}" ]]; then
        if [[ -n "${STEAMCMD_BIN:-}" ]]; then
            echo "[ERROR] Specified STEAMCMD_BIN (${STEAMCMD_BIN}) does not exist or is not executable." >&2
            return 10
        fi
        echo "[INFO] SteamCMD not found. Installing into isolated ${STEAMCMD_DIR}..."
        mkdir -p "${STEAMCMD_DIR}"
        if ! curl -sSL --max-time 30 "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_osx.tar.gz" | tar -xz -C "${STEAMCMD_DIR}"; then
            echo "[ERROR] Failed to download or extract steamcmd_osx.tar.gz." >&2
            return 10
        fi
    fi
    return 0
}

run_steamcmd_with_timeout() {
    local log_file="$1"
    shift
    local runner="${TOOLS_DIR}/run_timeout.py"

    HOME="${STEAMCMD_HOME}" \
    TMPDIR="${STEAMCMD_TMP}" \
    "${runner}" "${TIMEOUT_SECONDS}" \
    "${STEAMCMD_EXEC}" "$@" 2>&1 | tee "${log_file}"
}

check_anonymous_probe() {
    echo "=========================================================="
    echo "Probing App ${APP_ID} Depot ${DEPOT_ID} via Isolated Anonymous SteamCMD"
    echo "=========================================================="

    # First evaluate size metadata
    evaluate_size_metadata

    # Ensure steamcmd exists or fail gracefully with 10
    if ! ensure_steamcmd; then
        echo "[ERROR] SteamCMD bootstrap failed."
        return 10
    fi

    # Create fresh unique directory for this run. NEVER overwrite or delete historical logs.
    local run_dir
    run_dir=$(mktemp -d "${LOGS_DIR}/check.XXXXXX")
    echo ""
    echo "[INFO] Run evidence directory: ${run_dir}"

    local stage1_log="${run_dir}/stage1_app_info.log"
    local stage2_log="${run_dir}/stage2_app_update.log"

    echo ""
    echo "[STAGE 1] Querying App Metadata (AppID: ${APP_ID})..."
    local ret1=0
    run_steamcmd_with_timeout "${stage1_log}" +login anonymous +app_info_print "${APP_ID}" +quit || ret1=$?

    if [[ ${ret1} -eq 124 ]]; then
        echo "[TIMEOUT] SteamCMD timed out (35s) while querying app info in Stage 1."
        return 10
    elif [[ ${ret1} -ne 0 ]]; then
        echo "[ERROR] SteamCMD exited with non-zero status (${ret1}) in Stage 1."
        return 10
    fi

    # Check for network connection failure in Stage 1
    if grep -qE "Connecting anonymously to Steam Public\.\.\.FAILED|No connection to the Steam servers" "${stage1_log}"; then
        echo "[NETWORK_ERROR] Could not connect to Steam Public servers in Stage 1."
        return 10
    fi

    echo ""
    echo "[STAGE 2] Probing License and Depot Update Permissions..."
    local ret2=0
    run_steamcmd_with_timeout "${stage2_log}" +login anonymous +app_license_request "${APP_ID}" +app_update "${APP_ID}" validate +quit || ret2=$?

    if [[ ${ret2} -eq 124 ]]; then
        echo "[TIMEOUT] SteamCMD timed out (35s) while attempting app update in Stage 2."
        return 10
    fi

    # Check for network connection failure in Stage 2
    if grep -qE "Connecting anonymously to Steam Public\.\.\.FAILED|No connection to the Steam servers" "${stage2_log}"; then
        echo "[NETWORK_ERROR] Could not connect to Steam Public servers in Stage 2."
        return 10
    fi

    echo ""
    echo "=========================================================="
    echo "Diagnostic Verification Results:"
    echo "=========================================================="

    if grep -q "section_type.*ownersonly" "${stage1_log}"; then
        echo "  [CONFIRMED Stage 1] App ${APP_ID} metadata declares section_type: 'ownersonly'."
    fi

    # Final verdict based on real Stage 2 output
    if grep -qE "Not for anonymous users|Failed to install app '${APP_ID}' \(No subscription\)" "${stage2_log}"; then
        echo "  [FIRST BLOCKER Stage 2] Steam requires an authenticated user with an active subscription."
        echo "  [STATUS] Acquisition blocked (Exit 20)."
        echo "  [LOG PRESERVED] Stage 1 log: ${stage1_log}"
        echo "  [LOG PRESERVED] Stage 2 log: ${stage2_log}"
        echo "  [USER INSTRUCTION] To test with official Valve ARM64 Proton, please export the"
        echo "                     installed files from your own Steam client into artifacts/proton/raw,"
        echo "                     then run: python3 scripts/proton/audit_proton.py artifacts/proton/raw/"
        return 20
    fi

    # If neither blocker string nor explicit success was returned, classify as unknown
    echo "[UNKNOWN] Stage 2 completed without definitive blocker signature. Retaining logs in ${run_dir}."
    return 10
}

main() {
    if [[ $# -eq 0 ]]; then
        usage
        exit 2
    fi

    local mode=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --check-only)
                mode="check"
                shift
                ;;
            --eval-size)
                mode="eval-size"
                shift
                ;;
            --username)
                echo "[ERROR] In-lab authenticated download via --username is deliberately disabled." >&2
                echo "        Reason: Strict policy prohibits passing or caching user Steam credentials inside the lab." >&2
                echo "        Guidance: Export the official package from your authorized Steam client" >&2
                echo "                  into 'artifacts/proton/raw' and run the offline audit tool." >&2
                exit 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                echo "[ERROR] Unknown or unexpected argument: $1" >&2
                usage >&2
                exit 2
                ;;
        esac
    done

    case "${mode}" in
        check)
            check_anonymous_probe
            ;;
        eval-size)
            evaluate_size_metadata
            ;;
        *)
            usage
            exit 2
            ;;
    esac
}

main "$@"
