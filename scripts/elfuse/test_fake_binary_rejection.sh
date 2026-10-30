#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAKE_BIN="$REPO_ROOT/tools/elfuse/bin/fake_elfuse"
RUNNER="$REPO_ROOT/scripts/elfuse/run_all_baseline.sh"

echo "=== Testing runner failure detection via ELFUSE_BIN override ==="
echo "Injecting fake binary: $FAKE_BIN"

# Run runner with ELFUSE_BIN pointing to fake_elfuse
ELFUSE_BIN="$FAKE_BIN" "$RUNNER" > "$REPO_ROOT/logs/elfuse/fake_binary_injection.log" 2>&1
runner_exit=$?

echo "Runner exit code: $runner_exit"
if [ "$runner_exit" -ne 0 ]; then
    echo "SUCCESS: Runner properly failed and returned exit code $runner_exit when fake binary was injected!"
else
    echo "ERROR: Runner incorrectly reported success on fake binary!"
    exit 1
fi
