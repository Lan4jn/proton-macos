#!/usr/bin/env python3
import os
import socket
import sys
import time
from pathlib import Path

def test_shortening_inode():
    base_dir = Path("/Users/mewcapoo/Projects/proton-macos-lab/.sr")
    
    # Guest path 105 bytes (< 108 bytes Linux sun_path limit)
    # Host path in sysroot will be ~150 bytes, triggering shortening
    guest_sock = "/tmp/" + "s" * 95 + ".sock"
    
    if os.path.exists(guest_sock):
        try:
            os.unlink(guest_sock)
        except:
            pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(guest_sock)
    server.listen(1)

    # Inode inspection in .sr/n<namespace>/
    subdirs = list(base_dir.glob("n*"))
    print(f"Server bound: found subdirs in .sr: {[s.name for s in subdirs]}")
    if not subdirs:
        print("FAIL: no namespace directory created in .sr")
        sys.exit(1)

    ns_dir = subdirs[0]
    entries = list(ns_dir.iterdir())
    print(f"Entries inside namespace dir {ns_dir.name}: {[e.name for e in entries]}")
    if not entries:
        print("FAIL: no shortening symlink created in namespace directory")
        sys.exit(2)

    link_entry = entries[0]
    st = os.lstat(link_entry)
    target = os.readlink(link_entry)
    print(f"OBSERVED SHORTENING SYMLINK: inode={st.st_ino}, mode={oct(st.st_mode)}, link={link_entry.name} -> {target}")

    pid = os.fork()
    if pid == 0:
        # Child client
        try:
            time.sleep(0.15)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(guest_sock)
            client.sendall(b"SHORTENING_PING")
            resp = client.recv(1024)
            client.close()
            if resp == b"SHORTENING_PONG":
                os._exit(0)
            os._exit(4)
        except Exception as e:
            sys.stderr.write(f"Child error: {e}\n")
            os._exit(5)
    else:
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
        rc = (status >> 8)
        if rc != 0:
            print(f"FAIL: child exited with {rc}")
            sys.exit(6)

        print("PASS: PATHNAME_SHORTENING_INODE_AND_COMMUNICATION_VERIFIED")
        sys.exit(0)

if __name__ == "__main__":
    test_shortening_inode()
