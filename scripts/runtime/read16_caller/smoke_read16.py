import os
import sys

def main():
    print("=== READ16 SMOKE TEST START ===", flush=True)
    r, w = os.pipe()
    os.write(w, b"1234567890123456") # 16 bytes
    data = os.read(r, 16)
    print(f"Read {len(data)} bytes: {data}", flush=True)
    assert len(data) == 16, "Expected 16 bytes"
    os.close(r)
    os.close(w)
    print("=== READ16 SMOKE TEST PASS ===", flush=True)

if __name__ == "__main__":
    main()
