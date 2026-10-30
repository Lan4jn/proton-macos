#!/usr/bin/env python3
"""
scripts/runtime/wine_badalloc/controller.py

Controlled Linux runner for Xvfb and Windows x64 Vulkan PE under Wine with
Linux ARM64 C++ exception callstack interposer (libbadalloc_trace.so).
Executes inside elfuse-socket-derived with Linux Python 3.14.

Guaranteed Gates:
1. Preflight verifies ELFUSE_ABSOCK_BASE in lab/.s (mode 0700) and abstract socket relay.
2. Xvfb isolated with -nolisten tcp -nolisten inet6 -nolisten local, client abstract display :97.
3. Private Xauthority created atomically with O_CREAT|O_EXCL mode 0600 (no -ac).
4. Synchronizes displayfd pipe, asserts int(dnum) == 97.
5. Precision cleanup of lock (PID match) and socket (st_dev/st_ino/st_uid match).
6. Same process group (no setsid, no killpg), direct Popen child management.
7. Wine injected with libbadalloc_trace.so via guest LD_PRELOAD, WINEDEBUG=+loaddll,+process,+vulkan,+seh.
"""

import ctypes
import json
import os
import secrets
import select
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

DISPLAY_NUM = 97
LOCK_FILE = f"/tmp/.X{DISPLAY_NUM}-lock"
SOCK_DIR = "/tmp/.X11-unix"
SOCK_FILE = f"{SOCK_DIR}/X{DISPLAY_NUM}"


def preflight_absock_base(lab_root: Path):
    absock_base = os.environ.get("ELFUSE_ABSOCK_BASE")
    if not absock_base:
        raise RuntimeError("FATAL: ELFUSE_ABSOCK_BASE environment variable is unset!")

    base_path = Path(absock_base).resolve()
    expected_path = (lab_root / ".s").resolve()
    if base_path != expected_path:
        raise RuntimeError(f"FATAL: ELFUSE_ABSOCK_BASE ({base_path}) does not match lab/.s ({expected_path})!")

    if not base_path.is_dir():
        raise RuntimeError(f"FATAL: ELFUSE_ABSOCK_BASE ({base_path}) is not an existing directory!")

    st = base_path.stat()
    mode = st.st_mode & 0o777
    if mode != 0o700:
        raise RuntimeError(f"FATAL: ELFUSE_ABSOCK_BASE mode ({oct(mode)}) is not 0700!")

    if st.st_uid != os.getuid():
        raise RuntimeError(f"FATAL: ELFUSE_ABSOCK_BASE owner ({st.st_uid}) != current uid ({os.getuid()})!")

    # Test abstract socket communication to verify relay works
    test_addr = f"\0test_preflight_badalloc_{os.getpid()}"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(test_addr)
        srv.listen(1)
        srv.settimeout(2.0)

        cli = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        cli.connect(test_addr)
        cli.sendall(b"PREFLIGHT_PING")

        conn, _ = srv.accept()
        data = conn.recv(64)
        conn.close()
        cli.close()
        srv.close()

        if data != b"PREFLIGHT_PING":
            raise RuntimeError(f"FATAL: Abstract socket preflight received unexpected data: {data}")
        print(f"[CONTROLLER] Preflight PASS: Abstract socket relay in {base_path} (mode 0700) verified.")
    except Exception as e:
        srv.close()
        raise RuntimeError(f"FATAL: Abstract socket preflight failed: {e}")


def write_xauthority(path: Path, disp_num: int, cookie: bytes):
    num_str = str(disp_num).encode("ascii")
    proto = b"MIT-MAGIC-COOKIE-1"
    hostname = os.uname().nodename.encode("utf-8")

    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        # 1. FamilyLocal (256)
        f.write(struct.pack(">H", 256) + struct.pack(">H", len(hostname)) + hostname +
                struct.pack(">H", len(num_str)) + num_str +
                struct.pack(">H", len(proto)) + proto +
                struct.pack(">H", len(cookie)) + cookie)
        # 2. FamilyWild (65535)
        f.write(struct.pack(">H", 65535) + struct.pack(">H", 0) +
                struct.pack(">H", len(num_str)) + num_str +
                struct.pack(">H", len(proto)) + proto +
                struct.pack(">H", len(cookie)) + cookie)


def check_displayfd_match(dnum_str: str, expected_num: int):
    val = int(dnum_str.strip())
    if val != expected_num:
        raise ValueError(f"displayfd reported display :{val}, expected :{expected_num}")
    return val


def clean_owned_lock(path_str: str, expected_pid: int) -> bool:
    if not os.path.lexists(path_str):
        return False
    try:
        content = Path(path_str).read_text(encoding="ascii").strip()
        lock_pid = int(content)
        if lock_pid == expected_pid:
            os.unlink(path_str)
            print(f"[CONTROLLER] Cleaned owned lock file: {path_str} (PID: {lock_pid})")
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
    lab_root = Path(os.environ.get("LAB_ROOT", "/Users/mewcapoo/Projects/proton-macos-lab")).resolve()
    if "TMPDIR" in os.environ and Path(os.environ["TMPDIR"]).parent.name.startswith("run-"):
        run_dir = Path(os.environ["TMPDIR"]).parent
    else:
        run_dir = Path(os.environ.get("RUN_DIR", str(lab_root / "logs" / "wine-badalloc" / f"run-{int(time.time())}"))).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[CONTROLLER] Initializing Wine + Xvfb bad_alloc observation runner...")
    print(f"[CONTROLLER] LAB_ROOT: {lab_root}")
    print(f"[CONTROLLER] RUN_DIR:  {run_dir}")

    # 1. Gate 1: Preflight ELFUSE_ABSOCK_BASE in lab/.s
    preflight_absock_base(lab_root)

    # 2. Gate 2: Display 97 free check
    if os.path.lexists(LOCK_FILE):
        raise RuntimeError(f"ABORT: Display {DISPLAY_NUM} lock file already exists: {LOCK_FILE}")
    if os.path.lexists(SOCK_FILE):
        raise RuntimeError(f"ABORT: Display {DISPLAY_NUM} socket already exists: {SOCK_FILE}")

    # 3. Gate 3: Private Xauthority
    cookie = secrets.token_bytes(16)
    auth_file = run_dir / "Xauthority"
    write_xauthority(auth_file, DISPLAY_NUM, cookie)
    print(f"[CONTROLLER] Private Xauthority created: {auth_file} (mode 0600)")

    # 4. Prepare Xvfb command
    xvfb_derived = lab_root / "fixtures" / "runtime" / "xvfb-derived"
    xvfb_bin = xvfb_derived / "usr" / "bin" / "Xvfb"
    xvfb_lib = xvfb_derived / "usr" / "lib"
    arch_lib = Path("/usr/lib")

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

    print(f"[CONTROLLER] Starting Xvfb on display :{DISPLAY_NUM}...")
    xvfb_proc = None
    expected_sock_inode = None
    expected_pid = None

    try:
        # Same process group, no setsid
        xvfb_proc = subprocess.Popen(
            xvfb_cmd,
            env=xvfb_env,
            stdout=xvfb_stdout,
            stderr=xvfb_stderr,
            pass_fds=(pipe_w,),
        )
        os.close(pipe_w)
        expected_pid = xvfb_proc.pid

        # Wait for displayfd notification (up to 15s)
        r, _, _ = select.select([pipe_r], [], [], 15.0)
        if not r:
            raise TimeoutError("Xvfb did not report readiness via displayfd within 15 seconds")

        dnum_str = os.read(pipe_r, 32).decode("ascii").strip()
        os.close(pipe_r)
        check_displayfd_match(dnum_str, DISPLAY_NUM)
        print(f"[CONTROLLER] Xvfb verified ready on display :{dnum_str}")

        if os.path.lexists(SOCK_FILE):
            st = os.lstat(SOCK_FILE)
            expected_sock_inode = (st.st_dev, st.st_ino, st.st_uid)
            print(f"[CONTROLLER] Recorded Xvfb socket inode: {expected_sock_inode}")

        # Probe X11 connection using libxcb with DISPLAY=:97 and XAUTHORITY
        os.environ["XAUTHORITY"] = str(auth_file)
        probe_res = xcb_probe(f":{DISPLAY_NUM}")
        print(f"[CONTROLLER] xcb probe on :{DISPLAY_NUM}: {probe_res}")
        if not probe_res.get("success"):
            raise RuntimeError(f"X11 connection handshake failed on display :{DISPLAY_NUM}: {probe_res}")

        # 5. Launch Wine with Windows x64 Vulkan PE and libbadalloc_trace.so
        bundle_root = lab_root / "fixtures" / "runtime" / "proton-derived"
        wine_bin = bundle_root / "files" / "bin-arm64" / "wine"
        wineserver_bin = bundle_root / "files" / "bin-arm64" / "wineserver"
        prefix_dir = lab_root / "fixtures" / "runtime" / "wine-badalloc" / "pfx"
        icd_json = lab_root / "fixtures" / "runtime" / "lavapipe-derived" / "usr" / "share" / "vulkan" / "icd.d" / "lvp_icd.json"
        lavapipe_lib = lab_root / "fixtures" / "runtime" / "lavapipe-derived" / "usr" / "lib"
        tracer_so = lab_root / "fixtures" / "runtime" / "badalloc-trace" / "libbadalloc_trace.so"
        target_win = "C:\\vk_enum_x64.exe"

        wine_cmd = [str(wine_bin), target_win]

        wine_env = os.environ.copy()
        wine_env["WINEPREFIX"] = str(prefix_dir)
        wine_env["DISPLAY"] = f":{DISPLAY_NUM}"
        wine_env["XAUTHORITY"] = str(auth_file)
        wine_env["LD_LIBRARY_PATH"] = f"{lavapipe_lib}:/usr/lib"
        wine_env["VK_ICD_FILENAMES"] = str(icd_json)
        wine_env["LD_PRELOAD"] = str(tracer_so)
        wine_env["WINEDEBUG"] = "+loaddll,+process,+vulkan,+seh"
        wine_env["PROTON_NO_ESYNC"] = "1"
        wine_env["PROTON_NO_FSYNC"] = "1"
        wine_env["PROTON_NO_NTSYNC"] = "1"
        wine_env["WINESERVER"] = str(wineserver_bin)
        wine_env["WINELOADER"] = str(wine_bin)

        wine_stdout_file = open(run_dir / "wine_stdout.log", "w")
        wine_stderr_file = open(run_dir / "wine_stderr.log", "w")

        print(f"[CONTROLLER] Launching Wine: {' '.join(wine_cmd)}")
        print(f"[CONTROLLER] Target PE: {target_win} (prefix: {prefix_dir})")
        print(f"[CONTROLLER] Injected LD_PRELOAD: {tracer_so}")
        print(f"[CONTROLLER] WINEDEBUG: {wine_env['WINEDEBUG']}")

        t_start = time.time()
        wine_proc = subprocess.Popen(
            wine_cmd,
            env=wine_env,
            stdout=wine_stdout_file,
            stderr=wine_stderr_file,
        )

        # Single controlled run: target 60-90s, early stop if first trace captured and settled
        max_duration = 85.0
        trace_captured = False
        trace_timestamp = None
        wine_rc = None

        while True:
            elapsed = time.time() - t_start
            wine_rc = wine_proc.poll()
            if wine_rc is not None:
                print(f"[CONTROLLER] Wine process exited naturally with code: {wine_rc} (elapsed: {elapsed:.2f}s)")
                break

            # Check if [BADALLOC_TRACE] appeared in wine_stderr.log
            if not trace_captured:
                wine_stderr_file.flush()
                try:
                    with open(run_dir / "wine_stderr.log", "r", errors="ignore") as f:
                        content = f.read()
                        if "[BADALLOC_TRACE]" in content:
                            trace_captured = True
                            trace_timestamp = time.time()
                            print(f"[CONTROLLER] >>> [BADALLOC_TRACE] CAPTURED at {elapsed:.2f}s! Waiting up to 10s for Wine to settle...")
                except Exception:
                    pass

            if trace_captured and (time.time() - trace_timestamp > 10.0):
                print(f"[CONTROLLER] [BADALLOC_TRACE] confirmed captured and post-trace period settled. Terminating Wine...")
                wine_proc.terminate()
                try:
                    wine_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    wine_proc.kill()
                    wine_proc.wait(timeout=2)
                wine_rc = wine_proc.poll()
                print(f"[CONTROLLER] Wine terminated after capturing trace (rc: {wine_rc})")
                break

            if elapsed >= max_duration:
                print(f"[CONTROLLER] Wine reached maximum observation window ({max_duration}s). Terminating...")
                wine_proc.terminate()
                try:
                    wine_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    wine_proc.kill()
                    wine_proc.wait(timeout=2)
                wine_rc = wine_proc.poll()
                print(f"[CONTROLLER] Wine terminated on timeout (rc: {wine_rc})")
                break

            time.sleep(1.0)

        wine_stdout_file.close()
        wine_stderr_file.close()

        # Stop wineserver
        try:
            subprocess.run([str(wineserver_bin), "-k"], env=wine_env, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    finally:
        # Cleanup Xvfb directly (no setsid, no killpg)
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

        # Precision cleanup
        if expected_pid:
            clean_owned_lock(LOCK_FILE, expected_pid)
        if expected_sock_inode:
            clean_owned_socket(SOCK_FILE, expected_sock_inode)

        if auth_file.is_file():
            try:
                auth_file.unlink()
                print(f"[CONTROLLER] Cleaned private Xauthority: {auth_file}")
            except Exception:
                pass


if __name__ == "__main__":
    main()
