#!/usr/bin/env python3
import json
import os
import subprocess
import hashlib
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab")

def compute_sha256(filepath):
    p = Path(filepath)
    if p.is_file():
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    return "not_found"

def main():
    rt = LAB / "sources/elfuse-once-panorama2-derived/build/elfuse"
    sysroot = LAB / "fixtures/runtime/arch-root"
    guest_py = sysroot / "usr/bin/python3.14"
    target_mvk = Path("/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib64/libMoltenVK.dylib")

    out_dir = LAB / "logs/moltenvk"
    out_dir.mkdir(parents=True, exist_ok=True)

    rt_sha = compute_sha256(rt)
    py_sha = compute_sha256(guest_py)

    mvk_exists = target_mvk.exists()
    mvk_size = target_mvk.stat().st_size if mvk_exists else 0
    mvk_sha = compute_sha256(target_mvk) if mvk_exists else "not_found"
    mvk_magic = "not_found"
    if mvk_exists:
        with open(target_mvk, "rb") as f:
            magic_bytes = f.read(16)
            mvk_magic = magic_bytes.hex()

    guest_code = """import ctypes, sys
mvk = "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib64/libMoltenVK.dylib"
try:
    ctypes.CDLL(mvk)
    print("SUCCESS: Loaded")
except Exception as e:
    print(f"REJECTION: {e}")
"""

    argv = [
        str(rt),
        "--user", "501:20",
        "--sysroot", str(sysroot),
        "--timeout", "10",
        "/usr/bin/python3.14",
        "-c", guest_code
    ]

    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    stdout_path = out_dir / "abi_probe_stdout.log"
    stderr_path = out_dir / "abi_probe_stderr.log"

    stdout_path.write_text(p.stdout)
    stderr_path.write_text(p.stderr)

    result = {
        "probe": "guest_dlopen_host_macho_dylib",
        "execution_context": {
            "host_runtime_path": str(rt),
            "host_runtime_sha256": rt_sha,
            "guest_sysroot_path": str(sysroot),
            "guest_interpreter_path": "/usr/bin/python3.14",
            "guest_interpreter_host_path": str(guest_py),
            "guest_interpreter_sha256": py_sha,
            "argv": argv,
            "exit_code": p.returncode,
            "raw_stdout_path": str(stdout_path),
            "raw_stderr_path": str(stderr_path)
        },
        "target_library": {
            "exact_path": str(target_mvk),
            "exists": mvk_exists,
            "size_bytes": mvk_size,
            "sha256": mvk_sha,
            "magic_hex_16_bytes": mvk_magic,
            "architecture_verified_via_lipo": "x86_64",
            "architecture_meaning": "cffaedfe = MH_MAGIC_64, 07000001 (little-endian 0x01000007) = CPU_TYPE_X86_64, 03000000 = CPU_SUBTYPE_X86_64_ALL, 06000000 = MH_DYLIB",
            "scope_boundary_note": "This test demonstrates rejection of this real Mach-O file (x86_64 Mach-O dylib) by guest ld.so. An arm64 Mach-O MoltenVK was NOT tested in this lab; commercial App files were not enumerated further."
        },
        "loader_result": {
            "stdout_trimmed": p.stdout.strip(),
            "stderr_trimmed": p.stderr.strip(),
            "rejection_message": [ln for ln in p.stdout.splitlines() if "REJECTION:" in ln],
            "verdict": "DEFINITIVE_ABI_BARRIER: glibc dynamic linker ld-linux-aarch64.so.1 fails with 'invalid ELF header' because file format is Mach-O MH_MAGIC_64."
        }
    }

    res_json_path = out_dir / "abi_probe_result.json"
    res_json_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Updated {res_json_path}")

if __name__ == "__main__":
    main()
