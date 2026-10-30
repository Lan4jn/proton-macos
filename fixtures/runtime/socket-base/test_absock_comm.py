#!/usr/bin/env python3
"""
Test Linux abstract UNIX domain socket bind, connect, send, recv under elfuse.
Runs under true Linux Python 3.14 via elfuse.
"""

import os
import socket
import sys
import time

def test_abstract_socket(socket_name: str = "elfuse_absock_test"):
    # Linux abstract namespace socket: first byte is NUL
    abstract_addr = f"\0{socket_name}"
    
    pid = os.fork()
    if pid == 0:
        # Child: acts as client, connects and sends message
        try:
            time.sleep(0.1)  # Give server time to listen
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(abstract_addr)
            s.sendall(b"HELLO_ABSOCK_FROM_CHILD")
            s.close()
            os._exit(0)
        except Exception as e:
            sys.stderr.write(f"Child client error: {e}\n")
            os._exit(1)
    else:
        # Parent: acts as server, binds abstract socket, accepts connection
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(abstract_addr)
            server.listen(1)
            server.settimeout(5.0)
            conn, _ = server.accept()
            data = conn.recv(1024)
            conn.close()
            server.close()
            
            _, status = os.waitpid(pid, 0)
            child_rc = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (status >> 8)
            
            if child_rc != 0:
                print(f"FAIL: child exited with {child_rc}")
                sys.exit(1)
                
            if data == b"HELLO_ABSOCK_FROM_CHILD":
                print("PASS: ABSTRACT_SOCKET_COMMUNICATION_SUCCESS")
                sys.exit(0)
            else:
                print(f"FAIL: unexpected data received: {data}")
                sys.exit(2)
        except Exception as e:
            sys.stderr.write(f"Server error: {e}\n")
            server.close()
            os.kill(pid, 9)
            os.waitpid(pid, 0)
            sys.exit(3)

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "elfuse_absock_test"
    test_abstract_socket(name)
