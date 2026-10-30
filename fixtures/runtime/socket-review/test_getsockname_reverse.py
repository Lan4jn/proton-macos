#!/usr/bin/env python3
"""
Test reverse mapping of pathname UNIX sockets via getsockname().
Ensures that a shortened socket path (>104 bytes in host) returns the guest spelling
rather than the internal shortened symlink path.
"""
import os
import socket
import sys

def main():
    guest_sock = "/tmp/" + "r" * 95 + ".sock"
    if os.path.exists(guest_sock):
        try:
            os.unlink(guest_sock)
        except:
            pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(guest_sock)
        bound_name = server.getsockname()
        print(f"Bound guest path: {guest_sock}")
        print(f"getsockname() returned: {bound_name}")
        server.close()
        try:
            os.unlink(guest_sock)
        except:
            pass

        if bound_name == guest_sock:
            print("PASS: GETSOCKNAME_REVERSE_MAPPING_VERIFIED")
            sys.exit(0)
        else:
            print(f"FAIL: bound_name mismatch: expected {guest_sock}, got {bound_name}")
            sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"getsockname test error: {e}\n")
        server.close()
        sys.exit(2)

if __name__ == "__main__":
    main()
