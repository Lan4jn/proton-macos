#!/usr/bin/env python3
import hashlib, json, os, shutil, sys, time
from pathlib import Path

lab = Path("/Users/mewcapoo/Projects/proton-macos-lab").resolve()
sys.path.insert(0, str(lab))
from scripts.backend.process import run_isolated

rt = lab / "sources/elfuse-once478-derived/build/elfuse"
srcp = lab / "fixtures/runtime/futex-args-vulkan/pfx"
baseargv = json.loads((lab / "logs/vulkan-null-driver/result.json").read_text())["result"]["argv"]

extra = {
    "ELFUSE_DIAG_SESSION_SHARED": "1",
    "ELFUSE_IO_TRANSACTION_OBSERVE": "1",
    "ELFUSE_FIXTURE_IDENTITY": "1",
    "ELFUSE_FUTEX_OWNER_OBSERVE": "1",
    "ELFUSE_FUTEX_TARGET_UADDR": "0x20102d478",
    "ELFUSE_THREAD_LIFETIME_OBSERVE": "1",
    "ELFUSE_ONCE_PANORAMA_OBSERVE": "1",
    "ELFUSE_ONCE_COUNT_OBSERVE": "1",
    "ELFUSE_ONCE_TRACE_OBSERVE": "1",
    "ELFUSE_ONCE_COUNT_UADDR": "0x20102d478",
    "ELFUSE_ONCE_TRACE_UADDR": "0x20102d478",
}

root = lab / "logs/once478"
root.mkdir(parents=True, exist_ok=True)
run_tag = f"run-{int(time.time())}"
rd = root / run_tag
rd.mkdir()
pfx = rd / "pfx"
shutil.copytree(srcp, pfx, symlinks=True)

wine_root = lab / "sources/wine-win32u-experimental/patched-full/files"
wine = wine_root / "bin-arm64/wine"
server = wine_root / "bin-arm64/wineserver"
relay = str(wine_root / "lib/wine/aarch64-unix") + ":" + str(wine_root / "lib/wine")

argv = baseargv[:]
argv[0] = str(rt)
for i, a in enumerate(argv):
    if a.startswith("WINEPREFIX="):
        a = "WINEPREFIX=" + str(pfx)
    elif a.startswith("WINELOADER="):
        a = "WINELOADER=" + str(wine)
    elif a.startswith("WINESERVER="):
        a = "WINESERVER=" + str(server)
    elif a.startswith("WINEDEBUG="):
        a = a + ",+loaddll"
    if a.startswith("unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;"):
        prefix = "unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES;"
        a = a.replace(prefix, prefix + " export LD_DEBUG=libs; export WINEDLLPATH='" + relay + "';", 1)
        a = a.replace("/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wine", str(wine))
        oldlib = "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib"
        a = a.replace(oldlib, str(wine_root / "lib"))
    argv[i] = a

# Dynamic SHA computation
actual_probe_file = pfx / "drive_c/vk_enum_arm64.exe"
probe_sha = hashlib.sha256(actual_probe_file.read_bytes()).hexdigest()
mod = str(wine_root / "lib/wine/aarch64-unix/win32u.so")
msha = hashlib.sha256(Path(mod).read_bytes()).hexdigest()
rt_sha = hashlib.sha256(rt.read_bytes()).hexdigest()

print(f"Starting once478 run: {run_tag}")
print(f"Runtime SHA: {rt_sha}")
print(f"Module SHA: {msha}")
print(f"Probe SHA: {probe_sha}")

start = time.monotonic()
res = run_isolated(argv, rd, timeout=62, extra_env=extra)
secs = time.monotonic() - start

out = Path(res["stdout"]).read_text(errors="replace")
err = Path(res["stderr"]).read_text(errors="replace")

# Parse traces
mlines = [x for x in err.splitlines() if mod in x and "calling init:" in x]
steps = [x for x in out.splitlines() if "[WIN_ARM64_VK] Step " in x]
once_entries = [x for x in err.splitlines() if x.startswith("ONCE_ENTRY_COUNT") and "x0_uaddr=0x20102d478" in x]
target_once_lines = [x for x in err.splitlines() if x.startswith("ONCE_ENTRY_COUNT") and "is_target=1" in x]
bt_frames = [x for x in err.splitlines() if x.startswith("ONCE_BACKTRACE_FRAME")]
bt_summaries = [x for x in err.splitlines() if x.startswith("ONCE_BACKTRACE_SUMMARY")]
enter = [x for x in err.splitlines() if x.startswith("FUTEX_OWNER_ENTER") and "uaddr=0x20102d478" in x]
futex_args = [x for x in err.splitlines() if "20102d478" in x and "FUTEX" in x]
ret = [x for x in out.splitlines() if "vkCreateInstance" in x and ("return" in x.lower() or "VK_SUCCESS" in x)]
step4 = [x for x in out.splitlines() if "Step 4" in x]

rec = {
    "run_tag": run_tag,
    "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "runtime_path": str(rt),
    "runtime_sha256": rt_sha,
    "module_expected": mod,
    "module_sha256": msha,
    "module_load_lines": mlines,
    "module_load_confirmed": bool(mlines),
    "probe_path": str(actual_probe_file),
    "probe_sha256": probe_sha,
    "wine_loader": str(wine),
    "wine_server": str(server),
    "winelldllpath": relay,
    "prefix": str(pfx),
    "argv": argv,
    "extra_env": extra,
    "exit": res["exit"],
    "timed_out": res["timed_out"],
    "seconds": secs,
    "stdout_bytes": len(out.encode()),
    "stderr_bytes": len(err.encode()),
    "run_dir": res.get("run_dir", str(rd)),
    "steps": steps,
    "has_step3": any("Step 3" in x for x in steps),
    "has_step4": bool(step4),
    "target_once_entries": once_entries,
    "target_once_entry_count": len(once_entries),
    "backtrace_frame_count": len(bt_frames),
    "backtrace_summaries": bt_summaries,
    "vkCreateInstance_returned": bool(ret),
    "stdout_tail": out.splitlines()[-20:],
}

(rd / "receipt.json").write_text(json.dumps(rec, indent=2) + "\n")
print(f"=== Execution Complete: exit={rec['exit']}, timed_out={rec['timed_out']}, once_entries={len(once_entries)}, bt_frames={len(bt_frames)} ===")
for s in bt_summaries:
    print(" ", s)
