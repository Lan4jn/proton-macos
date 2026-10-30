#!/usr/bin/env python3
"""
Test Linux pathname socket shortening under elfuse.
Guest path is ~104-106 bytes (< 108 bytes Linux sun_path limit).
Under elfuse, this translates to host path in sysroot:
  /Users/.../arch-case/tmp/aaaa... (~150 bytes),
which exceeds macOS 104-byte sun_path limit, triggering absock_shorten_path.
"""

import os
import socket
import sys
import time

def test_shortening():
    # Guest path is 105 bytes. In guest it fits in 108 bytes.
    # In host it becomes /Users/mewcapoo/.../arch-case/tmp/aaaa... (~150 bytes)
    # This triggers absock_shorten_path, which symlinks it into absock_dir!
    guest_sock = "/tmp/" + "x" * 95 + ".sock"
    
    print(f"Testing guest socket path: length={len(guest_sock)}")
    if os.path.exists(guest_sock):
        try:
            os.unlink(guest_sock)
        except:
            pass

    pid = os.fork()
    if pid == 0:
        # Child client
        try:
            time.sleep(0.15)
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(guest_sock)
            s.sendall(b"SHORTENING_PING")
            data = s.recv(1024)
            s.close()
            if data == b"SHORTENING_PONG":
                os._exit(0)
            os._exit(2)
        except Exception as e:
            sys.stderr.write(f"Child error: {e}\n")
            os._exit(1)
    else:
        # Parent server
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(guest_sock)
            server.listen(1)
            server.settimeout(5.0)
            conn, _ = server.accept()
            msg = conn.recv(1024)
            if msg == b"SHORTENING_PING":
                conn.sendall(b"SHORTENING_PONG")
            conn.close()
            server.close()
            try:
                os.unlink(guest_sock)
            except:
                pass
            
            _, status = os.waitpid(pid, 0)
            child_rc = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (status >> 8)
            if child_rc == 0 and msg == b"SHORTENING_PING":
                print("PASS: PATHNAME_SHORTENING_COMMUNICATION_SUCCESS")
                sys.exit(0)
            else:
                print(f"FAIL: child_rc={child_rc}, msg={msg}")
                sys.exit(1)
        except Exception as e:
            sys.stderr.write(f"Server error: {e}\n")
            server.close()
            try:
                os.unlink(guest_sock)
            except:
                pass
            os.kill(pid, 9)
            os.waitpid(pid, 0)
            sys.exit(3)

if __name__ == "__main__":
    test_shortening()
