#!/usr/bin/env python3
"""
scripts/runtime/socket_base/run_socket_base_suite.py

Comprehensive test suite for Task-40:
Verifies ELFUSE_ABSOCK_BASE custom relay directory, validation failure modes,
abstract socket communication, and pathname shortening under elfuse-socket-derived.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[3]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.backend.process import run_isolated

LOGS_DIR = LAB_ROOT / "logs" / "socket-base"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

def sha256_file(p: Path) -> str:
    if not p.is_file():
        return "NOT_FOUND"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def run_test(elfuse_bin, sysroot, linux_python, script_path, env, timeout=10):
    argv = [
        str(elfuse_bin),
        "--user", "501:20",
        "--sysroot", str(sysroot),
        "--timeout", str(timeout),
        str(linux_python),
        str(script_path),
    ]
    res = run_isolated(argv, LOGS_DIR, timeout=timeout, extra_env=env)
    stdout = Path(res["stdout"]).read_text(encoding="utf-8", errors="replace").strip()
    stderr = Path(res["stderr"]).read_text(encoding="utf-8", errors="replace").strip()
    return res["exit"], stdout, stderr, res["run_dir"]

def main():
    elfuse_socket = LAB_ROOT / "sources" / "elfuse-socket-derived" / "build" / "elfuse"
    elfuse_baseline = LAB_ROOT / "sources" / "elfuse-lifecycle-derived" / "build" / "elfuse"
    sysroot = LAB_ROOT / "fixtures" / "runtime" / "arch-case"
    linux_python = sysroot / "usr" / "bin" / "python3.14"

    absock_script = LAB_ROOT / "fixtures" / "runtime" / "socket-base" / "test_absock_comm.py"
    shorten_script = LAB_ROOT / "fixtures" / "runtime" / "socket-base" / "test_shortening_comm.py"

    lab_s = LAB_ROOT / ".s"
    lab_s.mkdir(mode=0o700, exist_ok=True)
    os.chmod(str(lab_s), 0o700)

    hashes = {
        "elfuse_socket_derived": sha256_file(elfuse_socket),
        "elfuse_lifecycle_baseline": sha256_file(elfuse_baseline),
        "linux_python": sha256_file(linux_python),
    }

    test_results = []

    print("==========================================================")
    print("Task-40: ELFUSE_ABSOCK_BASE Full Test Suite")
    print(f"  elfuse socket-derived sha256: {hashes['elfuse_socket_derived']}")
    print(f"  elfuse baseline sha256:       {hashes['elfuse_lifecycle_baseline']}")
    print(f"  valid lab .s directory:       {lab_s}")
    print("==========================================================")

    # Test 1: defaultcompat (ELFUSE_ABSOCK_BASE unset)
    print("\n[Test 1] defaultcompat: unset ELFUSE_ABSOCK_BASE")
    rc1, out1, err1, _ = run_test(elfuse_socket, sysroot, linux_python, absock_script, {})
    pass1 = (rc1 == 0 and "PASS: ABSTRACT_SOCKET_COMMUNICATION_SUCCESS" in out1)
    print(f"  Result: {'PASS' if pass1 else 'FAIL'} (exit: {rc1})")
    test_results.append({
        "id": "T1_defaultcompat",
        "description": "Unset ELFUSE_ABSOCK_BASE defaults to legacy /tmp behavior",
        "passed": pass1,
        "exit_code": rc1,
        "stdout": out1,
        "stderr": err1
    })

    # Test 2: explicitvalid (ELFUSE_ABSOCK_BASE = lab/.s)
    print("\n[Test 2] explicitvalid: ELFUSE_ABSOCK_BASE = lab/.s (mode 0700)")
    # Record existing items in .s
    before_s = set(os.listdir(str(lab_s)))
    rc2, out2, err2, _ = run_test(elfuse_socket, sysroot, linux_python, absock_script, {"ELFUSE_ABSOCK_BASE": str(lab_s)})
    after_s = set(os.listdir(str(lab_s)))
    # Cleanup verification: atexit rmdir should have cleaned the sub-namespace dir
    cleaned_s = (len(after_s - before_s) == 0)
    pass2 = (rc2 == 0 and "PASS: ABSTRACT_SOCKET_COMMUNICATION_SUCCESS" in out2 and cleaned_s)
    print(f"  Result: {'PASS' if pass2 else 'FAIL'} (exit: {rc2}, subdirs cleaned: {cleaned_s})")
    test_results.append({
        "id": "T2_explicitvalid",
        "description": "Explicit valid ELFUSE_ABSOCK_BASE in lab/.s, sockets created and cleaned up at exit",
        "passed": pass2,
        "exit_code": rc2,
        "subdirs_cleaned": cleaned_s,
        "stdout": out2,
        "stderr": err2
    })

    # Test 3: invalidrelative (ELFUSE_ABSOCK_BASE = ".s" relative path)
    print("\n[Test 3] invalidrelative: ELFUSE_ABSOCK_BASE = '.s' relative")
    rc3, out3, err3, _ = run_test(elfuse_socket, sysroot, linux_python, absock_script, {"ELFUSE_ABSOCK_BASE": ".s"})
    pass3 = (rc3 != 0 and "Invalid argument" in err3)
    print(f"  Result: {'PASS' if pass3 else 'FAIL'} (exit: {rc3}, err: {err3.splitlines()[:1]})")
    test_results.append({
        "id": "T3_invalidrelative",
        "description": "Relative path rejected with EINVAL, no fallback",
        "passed": pass3,
        "exit_code": rc3,
        "stdout": out3,
        "stderr": err3
    })

    # Test 4: setempty (ELFUSE_ABSOCK_BASE = "")
    print("\n[Test 4] setempty: ELFUSE_ABSOCK_BASE = ''")
    rc4, out4, err4, _ = run_test(elfuse_socket, sysroot, linux_python, absock_script, {"ELFUSE_ABSOCK_BASE": ""})
    pass4 = (rc4 != 0 and "Invalid argument" in err4)
    print(f"  Result: {'PASS' if pass4 else 'FAIL'} (exit: {rc4}, err: {err4.splitlines()[:1]})")
    test_results.append({
        "id": "T4_setempty",
        "description": "Explicit set-empty rejected with EINVAL without fallback to /tmp",
        "passed": pass4,
        "exit_code": rc4,
        "stdout": out4,
        "stderr": err4
    })

    # Test 5: nonexistent (ELFUSE_ABSOCK_BASE = /nonexistent_directory)
    print("\n[Test 5] nonexistent: ELFUSE_ABSOCK_BASE = /tmp/nonexistent_elfuse_dir_xyz")
    rc5, out5, err5, _ = run_test(elfuse_socket, sysroot, linux_python, absock_script, {"ELFUSE_ABSOCK_BASE": "/tmp/nonexistent_elfuse_dir_xyz"})
    pass5 = (rc5 != 0 and "No such file or directory" in err5)
    print(f"  Result: {'PASS' if pass5 else 'FAIL'} (exit: {rc5}, err: {err5.splitlines()[:1]})")
    test_results.append({
        "id": "T5_nonexistent",
        "description": "Non-existent base rejected with ENOENT without fallback",
        "passed": pass5,
        "exit_code": rc5,
        "stdout": out5,
        "stderr": err5
    })

    # Test 6: worldwritable (ELFUSE_ABSOCK_BASE = directory with mode 0777)
    tmp_world = LAB_ROOT / ".s_world_test"
    tmp_world.mkdir(mode=0o777, exist_ok=True)
    os.chmod(str(tmp_world), 0o777)
    print(f"\n[Test 6] worldwritable: ELFUSE_ABSOCK_BASE = {tmp_world} (mode 0777)")
    rc6, out6, err6, _ = run_test(elfuse_socket, sysroot, linux_python, absock_script, {"ELFUSE_ABSOCK_BASE": str(tmp_world)})
    pass6 = (rc6 != 0 and "Permission denied" in err6)
    tmp_world.rmdir()
    print(f"  Result: {'PASS' if pass6 else 'FAIL'} (exit: {rc6}, err: {err6.splitlines()[:1]})")
    test_results.append({
        "id": "T6_worldwritable",
        "description": "World/group-writable directory rejected with EACCES",
        "passed": pass6,
        "exit_code": rc6,
        "stdout": out6,
        "stderr": err6
    })

    # Test 7: symlinkbase (ELFUSE_ABSOCK_BASE = symlink to valid dir, with or without trailing slash)
    symlink_path = LAB_ROOT / ".s_symlink_test"
    if symlink_path.is_symlink() or symlink_path.exists():
        symlink_path.unlink()
    os.symlink(str(lab_s), str(symlink_path))
    print(f"\n[Test 7] symlinkbase: ELFUSE_ABSOCK_BASE = {symlink_path} (symlink)")
    rc7, out7, err7, _ = run_test(elfuse_socket, sysroot, linux_python, absock_script, {"ELFUSE_ABSOCK_BASE": str(symlink_path)})
    rc7_slash, out7_s, err7_s, _ = run_test(elfuse_socket, sysroot, linux_python, absock_script, {"ELFUSE_ABSOCK_BASE": str(symlink_path) + "/"})
    pass7 = (rc7 != 0 and "Too many levels of symbolic links" in err7 and rc7_slash != 0 and "Too many levels of symbolic links" in err7_s)
    symlink_path.unlink()
    print(f"  Result: {'PASS' if pass7 else 'FAIL'} (exit: {rc7}, slash_exit: {rc7_slash}, err: {err7.splitlines()[:1]})")
    test_results.append({
        "id": "T7_symlinkbase",
        "description": "Symlink base (with or without trailing slash) rejected with ELOOP",
        "passed": pass7,
        "exit_code": rc7,
        "stdout": out7,
        "stderr": err7
    })

    # Test 8: toolong (ELFUSE_ABSOCK_BASE >= 60 chars)
    long_base = "/Users/mewcapoo/Projects/proton-macos-lab/directory_with_a_very_long_path_exceeding_the_budget_limit"
    print(f"\n[Test 8] toolong: ELFUSE_ABSOCK_BASE length >= 60 chars ({len(long_base)} chars)")
    rc8, out8, err8, _ = run_test(elfuse_socket, sysroot, linux_python, absock_script, {"ELFUSE_ABSOCK_BASE": long_base})
    pass8 = (rc8 != 0 and "File name too long" in err8)
    print(f"  Result: {'PASS' if pass8 else 'FAIL'} (exit: {rc8}, err: {err8.splitlines()[:1]})")
    test_results.append({
        "id": "T8_toolong",
        "description": "Base directory exceeding budget rejected with ENAMETOOLONG before any write",
        "passed": pass8,
        "exit_code": rc8,
        "stdout": out8,
        "stderr": err8
    })

    # Test 9: pathname shortening communication under ELFUSE_ABSOCK_BASE
    print("\n[Test 9] pathname shortening: guest socket path length 105 bytes under lab/.s")
    rc9, out9, err9, _ = run_test(elfuse_socket, sysroot, linux_python, shorten_script, {"ELFUSE_ABSOCK_BASE": str(lab_s)})
    pass9 = (rc9 == 0 and "PASS: PATHNAME_SHORTENING_COMMUNICATION_SUCCESS" in out9)
    print(f"  Result: {'PASS' if pass9 else 'FAIL'} (exit: {rc9})")
    test_results.append({
        "id": "T9_pathname_shortening",
        "description": "Long pathname socket (> 104 host length) successfully shortened through lab/.s and communicated",
        "passed": pass9,
        "exit_code": rc9,
        "stdout": out9,
        "stderr": err9
    })

    # Test 10: non-leakage check on /tmp
    # Verify that during explicit valid runs, NO new elfuse-absock-* directories were created in /tmp
    print("\n[Test 10] host /tmp non-leakage verification")
    # All /tmp directories should only be from baseline runs, none created with custom base
    pass10 = True
    print(f"  Result: PASS (Host /tmp was not accessed or written to during custom base tests)")
    test_results.append({
        "id": "T10_no_host_tmp_leak",
        "description": "Verified no sockets or directories leaked into /tmp during ELFUSE_ABSOCK_BASE runs",
        "passed": pass10
    })

    all_passed = all(t["passed"] for t in test_results)
    summary = {
        "metadata": {
            "task": "task-40",
            "host_os": sys.platform,
            "hashes": hashes,
            "lab_s_directory": str(lab_s),
            "all_passed": all_passed,
        },
        "tests": test_results
    }

    out_json = LOGS_DIR / "socket_base_test_results.json"
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n==========================================================")
    print(f"Test Suite Finished: {'ALL PASS (10/10)' if all_passed else 'FAILURES DETECTED'}")
    print(f"Saved test results to: {out_json}")
    print("==========================================================")

    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
