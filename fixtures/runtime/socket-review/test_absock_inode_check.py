#!/usr/bin/env python3
import os
import socket
import sys
import time
from pathlib import Path

def test_inode_and_exchange():
    base_dir = Path("/Users/mewcapoo/Projects/proton-macos-lab/.sr")
    abstract_addr = "\0review_inode_test_sock"

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(abstract_addr)
    server.listen(1)

    # At this point, the server socket node must exist inside .sr/n<namespace>/
    subdirs = list(base_dir.glob("n*"))
    print(f"Server bound: found subdirs in .sr: {[s.name for s in subdirs]}")
    if not subdirs:
        print("FAIL: no namespace directory created in .sr")
        sys.exit(1)

    ns_dir = subdirs[0]
    sock_files = list(ns_dir.iterdir())
    print(f"Files inside namespace dir {ns_dir.name}: {[f.name for f in sock_files]}")
    if not sock_files:
        print("FAIL: no socket file created in namespace directory")
        sys.exit(2)

    sock_file = sock_files[0]
    st = os.stat(sock_file)
    print(f"OBSERVED REAL INODE: {st.st_ino}, mode: {oct(st.st_mode)}, path: {sock_file}")

    pid = os.fork()
    if pid == 0:
        # Child client connects and sends message
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(abstract_addr)
            client.sendall(b"PING_INODE_CHECK")
            resp = client.recv(1024)
            client.close()
            if resp == b"PONG_INODE_CHECK":
                os._exit(0)
            os._exit(4)
        except Exception as e:
            sys.stderr.write(f"Child error: {e}\n")
            os._exit(5)
    else:
        conn, _ = server.accept()
        msg = conn.recv(1024)
        if msg == b"PING_INODE_CHECK":
            conn.sendall(b"PONG_INODE_CHECK")
        conn.close()
        server.close()

        _, status = os.waitpid(pid, 0)
        rc = (status >> 8)
        if rc != 0:
            print(f"FAIL: child exited with {rc}")
            sys.exit(6)

        print("PASS: ABSTRACT_SOCKET_INODE_AND_COMMUNICATION_VERIFIED")
        sys.exit(0)

if __name__ == "__main__":
    test_inode_and_exchange()
