#!/usr/bin/env python3
"""
Test that ELFUSE_ABSOCK_BASE persists across execve and enables abstract socket communication.
Process 1 (server) binds abstract socket, then spawns Process 2 (client) via os.execv.
Client connects and sends message, proving environment persistence across execve.
"""
import os
import socket
import sys
import time

def main():
    abstract_addr = "\0review_exec_test_sock"

    if len(sys.argv) > 1 and sys.argv[1] == "--child-client":
        # Child process post-exec: connects to abstract socket
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(abstract_addr)
            s.sendall(b"PING_CROSS_EXEC")
            resp = s.recv(1024)
            s.close()
            if resp == b"PONG_CROSS_EXEC":
                sys.exit(0)
            sys.exit(2)
        except Exception as e:
            sys.stderr.write(f"Exec client error: {e}\n")
            sys.exit(1)

    # Parent server
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(abstract_addr)
    server.listen(1)

    pid = os.fork()
    if pid == 0:
        # Child: execs self with true Linux Python
        os.execv(sys.executable, [sys.executable, __file__, "--child-client"])
    else:
        conn, _ = server.accept()
        msg = conn.recv(1024)
        if msg == b"PING_CROSS_EXEC":
            conn.sendall(b"PONG_CROSS_EXEC")
        conn.close()
        server.close()

        _, status = os.waitpid(pid, 0)
        rc = (status >> 8)
        if rc != 0:
            print(f"FAIL: exec child exited with {rc}")
            sys.exit(3)

        print("PASS: ABSTRACT_SOCKET_CROSS_EXEC_COMMUNICATION_VERIFIED")
        sys.exit(0)

if __name__ == "__main__":
    main()
