import os
import sys

def main():
    print("=== SMOKE TEST START ===", flush=True)
    # 1. Pipe creation
    r, w = os.pipe()
    print(f"Created pipe: r={r}, w={w}", flush=True)

    # 2. Write data
    msg = b"PING_FROM_PIPE"
    written = os.write(w, msg)
    print(f"Wrote {written} bytes to w={w}", flush=True)

    # 3. Dup read end
    r_dup = os.dup(r)
    print(f"Duped r={r} to r_dup={r_dup}", flush=True)

    # 4. Close original r
    os.close(r)
    print(f"Closed r={r}", flush=True)

    # 5. Read from r_dup
    chunk = os.read(r_dup, 1024)
    print(f"Read {len(chunk)} bytes from r_dup={r_dup}: {chunk.decode()}", flush=True)
    assert chunk == msg, "Content mismatch!"

    # 6. Fork child to test cross-fork inheritance
    pid = os.fork()
    if pid == 0:
        # In child
        child_msg = b"MSG_FROM_CHILD"
        os.write(w, child_msg)
        os.close(w)
        os.close(r_dup)
        os._exit(0)

    # In parent
    _, status = os.waitpid(pid, 0)
    print(f"Child {pid} exited with status {status}", flush=True)

    child_chunk = os.read(r_dup, 1024)
    print(f"Parent read {len(child_chunk)} bytes: {child_chunk.decode()}", flush=True)
    assert child_chunk == b"MSG_FROM_CHILD"

    # 7. Close write end to test EOF
    os.close(w)
    print(f"Closed w={w}", flush=True)

    eof_chunk = os.read(r_dup, 1024)
    print(f"EOF read returned {len(eof_chunk)} bytes (expected 0 for EOF)", flush=True)
    assert len(eof_chunk) == 0, "Expected clean EOF!"

    os.close(r_dup)
    print("=== SMOKE TEST PASS ===", flush=True)

if __name__ == "__main__":
    main()
