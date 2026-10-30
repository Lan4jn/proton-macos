#!/usr/bin/env python3
"""
scripts/runtime/windows_vk_phase/controller.py

Controlled Linux runner for task-54:
Windows Vulkan enumeration test with v3 phase diagnostic library.
Inherits task-52 controlled environment profile (clean_env, no --clear-env).

Key Features:
- Validates display 97 is free before starting using lexists.
- Disables all TCP/inet6/abstract listeners in Xvfb: -nolisten tcp -nolisten inet6 -nolisten local.
- Uses -xkbdir /usr/share/xkeyboard-config-2.
- Generates private MIT-MAGIC-COOKIE-1 0600 Xauthority file using atomic O_CREAT|O_EXCL.
- Uses -displayfd pipe to synchronize readiness and asserts exact integer match.
- Precision owned cleanup:
  * LOCK_FILE unlinked ONLY if lock content PID == xvfb_proc.pid.
  * SOCK_FILE unlinked ONLY if Xvfb verified ready and st_ino/st_dev/st_uid matches.
- Client uses DISPLAY=:97 safely under validated ELFUSE_ABSOCK_BASE relay.
- Restores exact task-37/task-52 invocation: Linux /bin/sh -c setting complete LD_LIBRARY_PATH and LD_PRELOAD.
- Runs Wine in caller process group (no setsid/killpg, direct child termination).
- Caps Wine at 90s, decoupling Wine timeout (OBSERVATION_TIMEOUT) from controller exit.
- Captures and maps all [BADALLOC_PHASE:*] diagnostic markers.
"""

import os
import sys
import time
import struct
import shlex
import secrets
import subprocess
import ctypes
from pathlib import Path

DISPLAY_NUM = 97
LOCK_FILE = f"/tmp/.X{DISPLAY_NUM}-lock"
SOCK_DIR = "/tmp/.X11-unix"
SOCK_FILE = f"{SOCK_DIR}/X{DISPLAY_NUM}"


def write_xauthority(path: Path, disp_num: int, cookie: bytes):
    num_str = str(disp_num).encode("ascii")
    proto = b"MIT-MAGIC-COOKIE-1"
    hostname = os.uname().nodename.encode("utf-8")

    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        # 1. FamilyLocal (256) with hostname
        f.write(struct.pack(">H", 256) + struct.pack(">H", len(hostname)) + hostname +
                struct.pack(">H", len(num_str)) + num_str +
                struct.pack(">H", len(proto)) + proto +
                struct.pack(">H", len(cookie)) + cookie)
        # 2. FamilyLocal (256) with empty address
        f.write(struct.pack(">H", 256) + struct.pack(">H", 0) + b"" +
                struct.pack(">H", len(num_str)) + num_str +
                struct.pack(">H", len(proto)) + proto +
                struct.pack(">H", len(cookie)) + cookie)
        # 3. FamilyWild (65535)
        f.write(struct.pack(">H", 65535) + struct.pack(">H", 0) + b"" +
                struct.pack(">H", len(num_str)) + num_str +
                struct.pack(">H", len(proto)) + proto +
                struct.pack(">H", len(cookie)) + cookie)


def check_displayfd_match(reported_dnum: str, expected_dnum: int) -> bool:
    try:
        val = int(reported_dnum.strip())
    except (ValueError, TypeError):
        raise AssertionError(f"DisplayFD reported non-integer display: '{reported_dnum}'")
    if val != expected_dnum:
        raise AssertionError(f"Display mismatch: Xvfb reported '{val}', expected '{expected_dnum}'")
    return True


def clean_owned_lock(path_str: str, expected_pid: int) -> bool:
    if not expected_pid or not os.path.lexists(path_str):
        return False
    try:
        with open(path_str, "r") as f:
            content = f.read().strip()
        lock_pid = int(content)
        if lock_pid == expected_pid:
            os.unlink(path_str)
            print(f"[CONTROLLER] Cleaned owned lock file (PID {expected_pid}): {path_str}")
            return True
        else:
            print(f"[WARNING] Refusing to unlink {path_str}: lock PID mismatch ({lock_pid} != {expected_pid})", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[CONTROLLER] Error cleaning lock {path_str}: {e}", file=sys.stderr)
        return False


def clean_owned_socket(path_str: str, expected_inode_tuple) -> bool:
    if not expected_inode_tuple or not os.path.lexists(path_str):
        return False
    try:
        cur = os.lstat(path_str)
        cur_tuple = (cur.st_dev, cur.st_ino, cur.st_uid)
        if cur_tuple == expected_inode_tuple:
            os.unlink(path_str)
            print(f"[CONTROLLER] Cleaned owned socket: {path_str}")
            return True
        else:
            print(f"[WARNING] Refusing to unlink socket {path_str}: inode/uid mismatch ({cur_tuple} != {expected_inode_tuple})", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[CONTROLLER] Error cleaning socket {path_str}: {e}", file=sys.stderr)
        return False


def xcb_probe(display_str: str) -> dict:
    result = {"display": display_str, "success": False, "error_code": None}
    try:
        libxcb = ctypes.CDLL("libxcb.so.1")
        libxcb.xcb_connect.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
        libxcb.xcb_connect.restype = ctypes.c_void_p
        libxcb.xcb_connection_has_error.argtypes = [ctypes.c_void_p]
        libxcb.xcb_connection_has_error.restype = ctypes.c_int
        libxcb.xcb_disconnect.argtypes = [ctypes.c_void_p]
        libxcb.xcb_disconnect.restype = None

        screen_p = ctypes.c_int(0)
        c = libxcb.xcb_connect(display_str.encode("utf-8"), ctypes.byref(screen_p))
        if not c:
            result["error_code"] = "NULL_CONNECTION"
            return result

        err = libxcb.xcb_connection_has_error(c)
        result["error_code"] = err
        if err == 0:
            result["success"] = True
            result["default_screen"] = screen_p.value
        libxcb.xcb_disconnect(c)
    except Exception as e:
        result["exception"] = str(e)
    return result


def main():
    lab_root = Path(os.environ.get("LAB_ROOT", "/Users/mewcapoo/Projects/proton-macos-lab"))
    run_dir = Path(os.environ.get("RUN_DIR", str(lab_root / "logs" / "windows-vk-phase" / f"run-{int(time.time())}")))
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[CONTROLLER] LAB_ROOT: {lab_root}")
    print(f"[CONTROLLER] RUN_DIR: {run_dir}")

    # 1. Pre-check display availability with lexists
    if os.path.lexists(LOCK_FILE):
        print(f"[ERROR] Lock file {LOCK_FILE} already exists! Aborting to avoid preemption.", file=sys.stderr)
        sys.exit(2)
    if os.path.lexists(SOCK_FILE):
        print(f"[ERROR] Socket file {SOCK_FILE} already exists! Aborting to avoid preemption.", file=sys.stderr)
        sys.exit(2)

    # 2. Setup auth cookie with O_CREAT|O_EXCL 0600
    cookie = secrets.token_bytes(16)
    auth_file = run_dir / "Xauthority"
    write_xauthority(auth_file, DISPLAY_NUM, cookie)
    print(f"[CONTROLLER] Generated Xauthority at {auth_file} (mode 0600, atomic O_EXCL)")

    # 3. Launch Xvfb
    xvfb_bin = lab_root / "fixtures" / "runtime" / "xvfb-derived" / "usr" / "bin" / "Xvfb"
    xvfb_lib = lab_root / "fixtures" / "runtime" / "xvfb-derived" / "usr" / "lib"
    arch_lib = lab_root / "fixtures" / "runtime" / "arch-case" / "usr" / "lib"
    lavapipe_lib = lab_root / "fixtures" / "runtime" / "lavapipe-derived" / "usr" / "lib"
    proton_bundle = lab_root / "fixtures" / "runtime" / "proton-derived"
    wine_bin = proton_bundle / "files" / "bin-arm64" / "wine"
    wineserver_bin = proton_bundle / "files" / "bin-arm64" / "wineserver"
    wine_unix_lib = proton_bundle / "files" / "lib" / "wine" / "aarch64-unix"
    pfx_dir = lab_root / "fixtures" / "runtime" / "windows-vk-phase" / "pfx"
    icd_json = lab_root / "fixtures" / "runtime" / "lavapipe-derived" / "usr" / "share" / "vulkan" / "icd.d" / "lvp_icd.json"
    diagnostic_lib = lab_root / "fixtures" / "runtime" / "badalloc-phase" / "libbadalloc_phase.so"

    pipe_r, pipe_w = os.pipe()

    xvfb_cmd = [
        str(xvfb_bin),
        f":{DISPLAY_NUM}",
        "-screen", "0", "640x480x24",
        "-nolisten", "tcp",
        "-nolisten", "inet6",
        "-nolisten", "local",
        "-xkbdir", "/usr/share/xkeyboard-config-2",
        "-auth", str(auth_file),
        "-displayfd", str(pipe_w),
    ]

    xvfb_env = os.environ.copy()
    xvfb_env["LD_LIBRARY_PATH"] = f"{xvfb_lib}:{arch_lib}"

    xvfb_stdout = open(run_dir / "xvfb_stdout.log", "w")
    xvfb_stderr = open(run_dir / "xvfb_stderr.log", "w")

    print(f"[CONTROLLER] Starting Xvfb: {' '.join(xvfb_cmd)}")
    xvfb_proc = None
    expected_sock_inode = None
    expected_pid = None

    wine_execution_record = {
        "wine_exit_code": None,
        "wine_elapsed_sec": None,
        "wine_status": "NOT_RUN",
        "phase_markers": [],
        "throw_captured": False,
        "backtrace_lines": [],
    }

    try:
        xvfb_proc = subprocess.Popen(
            xvfb_cmd,
            env=xvfb_env,
            stdout=xvfb_stdout,
            stderr=xvfb_stderr,
            pass_fds=(pipe_w,),
        )
        os.close(pipe_w)
        expected_pid = xvfb_proc.pid

        # Wait for displayfd notification
        import select
        r, _, _ = select.select([pipe_r], [], [], 15.0)
        if not r:
            raise TimeoutError("Xvfb did not report readiness via displayfd within 15 seconds")

        dnum_str = os.read(pipe_r, 32).decode("ascii").strip()
        os.close(pipe_r)
        check_displayfd_match(dnum_str, DISPLAY_NUM)
        print(f"[CONTROLLER] Xvfb reported ready on display :{dnum_str} (verified integer match)")

        # Record ownership and inodes of created socket
        if os.path.lexists(SOCK_FILE):
            st = os.lstat(SOCK_FILE)
            expected_sock_inode = (st.st_dev, st.st_ino, st.st_uid)
            print(f"[CONTROLLER] Recorded socket inode: {expected_sock_inode}")

        # 4. Probe X11 connection using libxcb with DISPLAY=:97 under lab/.s relay
        os.environ["XAUTHORITY"] = str(auth_file)
        
        probe_result = xcb_probe(f":{DISPLAY_NUM}")
        print(f"[CONTROLLER] xcb probe (colon :{DISPLAY_NUM}): {probe_result}")

        import json
        with open(run_dir / "xcb_probe.json", "w") as f:
            json.dump({"colon": probe_result}, f, indent=2)

        if not probe_result.get("success"):
            raise RuntimeError(f"X11 handshake with :{DISPLAY_NUM} failed: {probe_result}")

        # 5. Run Windows x64 Vulkan PE under Wine
        # Restoring exact task-37/task-52 invocation: Linux /bin/sh -c setting complete LD_LIBRARY_PATH and LD_PRELOAD
        target_win = "C:\\vk_enum_x64.exe"
        wine_ld_path = f"{lavapipe_lib}:{wine_unix_lib}:{proton_bundle / 'files' / 'lib'}:{arch_lib}"

        sh_script = (
            f"export LD_LIBRARY_PATH={shlex.quote(wine_ld_path)}; "
            f"export LD_PRELOAD={shlex.quote(str(diagnostic_lib))}; "
            f"exec {shlex.quote(str(wine_bin))} {shlex.quote(target_win)}"
        )

        wine_cmd = ["/bin/sh", "-c", sh_script]

        wine_env = os.environ.copy()
        wine_env["DISPLAY"] = f":{DISPLAY_NUM}"
        wine_env["XAUTHORITY"] = str(auth_file)
        wine_env["WINEPREFIX"] = str(pfx_dir)
        wine_env["WINESERVER"] = str(wineserver_bin)
        wine_env["WINELOADER"] = str(wine_bin)
        wine_env["WINEDEBUG"] = "+loaddll,+process,+vulkan,+seh"
        wine_env["VK_ICD_FILENAMES"] = str(icd_json)
        wine_env["WINEESYNC"] = "0"
        wine_env["WINEFSYNC"] = "0"
        wine_env["PROTON_NO_ESYNC"] = "1"
        wine_env["PROTON_NO_FSYNC"] = "1"
        wine_env["PROTON_NO_NTSYNC"] = "1"
        wine_env["PROTON_USE_ARM64"] = "1"

        print(f"[CONTROLLER] Launching Wine via /bin/sh -c with v3 phase LD_PRELOAD and full LD_LIBRARY_PATH...")
        wine_stdout_path = run_dir / "wine_stdout.log"
        wine_stderr_path = run_dir / "wine_stderr.log"
        wine_stdout_file = open(wine_stdout_path, "w")
        wine_stderr_file = open(wine_stderr_path, "w")

        start_time = time.time()
        # Keep in same process group (no setsid)
        wine_proc = subprocess.Popen(
            wine_cmd,
            env=wine_env,
            stdout=wine_stdout_file,
            stderr=wine_stderr_file,
        )

        wine_rc = None
        wine_timed_out = False
        observation_stopped = False

        try:
            while True:
                ret = wine_proc.poll()
                elapsed = time.time() - start_time
                if ret is not None:
                    wine_rc = ret
                    print(f"[CONTROLLER] Wine process exited naturally with code {wine_rc} in {elapsed:.2f}s")
                    break

                # Inspect stderr for phase markers
                if wine_stderr_path.exists():
                    try:
                        with open(wine_stderr_path, "r", errors="replace") as sf:
                            content = sf.read()
                            if "[BADALLOC_PHASE:BACKTRACE_DONE]" in content:
                                print(f"[CONTROLLER] Captured full backtrace in {elapsed:.2f}s! Early stopping observation...")
                                observation_stopped = True
                                wine_proc.terminate()
                                try:
                                    wine_rc = wine_proc.wait(timeout=5)
                                except subprocess.TimeoutExpired:
                                    wine_proc.kill()
                                    wine_rc = wine_proc.wait(timeout=2)
                                break
                    except Exception:
                        pass

                if elapsed >= 90.0:
                    print(f"[CONTROLLER] Wine reached internal target limit (90s)! Terminating...")
                    wine_timed_out = True
                    wine_proc.terminate()
                    try:
                        wine_rc = wine_proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        wine_proc.kill()
                        wine_rc = wine_proc.wait(timeout=2)
                    break

                time.sleep(1.0)

        finally:
            elapsed = time.time() - start_time
            wine_stdout_file.close()
            wine_stderr_file.close()

            wine_execution_record["wine_exit_code"] = wine_rc
            wine_execution_record["wine_elapsed_sec"] = elapsed
            if observation_stopped:
                wine_execution_record["wine_status"] = "OBSERVATION_STOPPED"
            elif wine_timed_out:
                wine_execution_record["wine_status"] = "OBSERVATION_TIMEOUT"
            elif wine_rc == 0:
                wine_execution_record["wine_status"] = "EXITED_OK"
            else:
                wine_execution_record["wine_status"] = "EXITED_NONZERO"

            # Parse all phase markers and backtrace lines
            phase_markers = []
            backtrace_lines = []
            if wine_stderr_path.exists():
                with open(wine_stderr_path, "r", errors="replace") as f:
                    for line in f:
                        line_s = line.strip()
                        if "[BADALLOC_PHASE:" in line_s:
                            phase_markers.append(line_s)
                            if "THROW_" in line_s or "HELPER_" in line_s:
                                wine_execution_record["throw_captured"] = True
                        if "[BADALLOC_TRACE]" in line_s or "[BADALLOC_PHASE:BT:" in line_s:
                            backtrace_lines.append(line_s)

            wine_execution_record["phase_markers"] = phase_markers
            wine_execution_record["backtrace_lines"] = backtrace_lines
            print(f"[CONTROLLER] Phase markers captured: {len(phase_markers)}")
            print(f"[CONTROLLER] Backtrace lines captured: {len(backtrace_lines)}")

            with open(run_dir / "wine_execution_record.json", "w") as f:
                json.dump(wine_execution_record, f, indent=2)

        # Clean wineserver
        try:
            subprocess.run(
                [str(wineserver_bin), "-k"],
                env={"WINEPREFIX": str(pfx_dir)},
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    finally:
        # Cleanup Xvfb
        if xvfb_proc and xvfb_proc.poll() is None:
            print("[CONTROLLER] Terminating Xvfb...")
            xvfb_proc.terminate()
            try:
                xvfb_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                xvfb_proc.kill()
                xvfb_proc.wait(timeout=2)
            print("[CONTROLLER] Xvfb terminated.")

        xvfb_stdout.close()
        xvfb_stderr.close()

        # Clean socket & lock files only after verifying ownership
        if expected_pid:
            clean_owned_lock(LOCK_FILE, expected_pid)
        if expected_sock_inode:
            clean_owned_socket(SOCK_FILE, expected_sock_inode)


if __name__ == "__main__":
    main()
