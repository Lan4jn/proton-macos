#!/usr/bin/env python3
import ctypes
import json
import sys
from pathlib import Path

def main():
    print("=== ABI INCOMPATIBILITY PROBE ===", flush=True)
    mvk_path = "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib64/libMoltenVK.dylib"
    error_msg = None
    success = False
    try:
        ctypes.CDLL(mvk_path)
        success = True
    except Exception as e:
        error_msg = str(e)
        print(f"Captured rejection: {error_msg}", flush=True)

    result = {
        "probe": "guest_dlopen_host_macho_dylib",
        "target_library": mvk_path,
        "success": success,
        "error": error_msg,
        "verdict": "DEFINITIVE_ABI_BARRIER" if "invalid ELF header" in (error_msg or "") else "UNKNOWN"
    }

    out_file = Path("/Users/mewcapoo/Projects/proton-macos-lab/logs/moltenvk/abi_probe_result.json")
    out_file.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote probe result to {out_file}", flush=True)

if __name__ == "__main__":
    main()
