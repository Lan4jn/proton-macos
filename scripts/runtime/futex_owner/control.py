import ctypes
import errno
import os
import sys
import threading
import time

lib = ctypes.CDLL('libc.so.6', use_errno=True)
lib.syscall.restype = ctypes.c_long
word = ctypes.c_uint32(0)

class TS(ctypes.Structure):
    _fields_ = [('sec', ctypes.c_long), ('nsec', ctypes.c_long)]

def call(op, val, timeout=None):
    ctypes.set_errno(0)
    ret = lib.syscall(
        ctypes.c_long(98),
        ctypes.byref(word),
        ctypes.c_int(op),
        ctypes.c_uint32(val),
        ctypes.byref(timeout) if timeout is not None else ctypes.c_void_p(0),
        ctypes.c_void_p(0),
        ctypes.c_uint32(0)
    )
    return ret, ctypes.get_errno()

print('[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...', flush=True)

# 1. EAGAIN: expected 1, but word is 0
r1, e1 = call(128, 1) # 128 = FUTEX_WAIT_PRIVATE
assert (r1, e1) == (-1, errno.EAGAIN), f"EAGAIN failed: {r1}, {e1}"

# 2. ETIMEDOUT: expected 0, timeout 20ms
r2, e2 = call(128, 0, TS(0, 20000000))
assert (r2, e2) == (-1, errno.ETIMEDOUT), f"ETIMEDOUT failed: {r2}, {e2}"

# 3. Cross-thread WAIT / WAKE
wakes = []
def wake():
    for _ in range(50):
        time.sleep(0.01)
        r = call(129, 1) # 129 = FUTEX_WAKE_PRIVATE
        wakes.append(r)
        if r[0] == 1:
            return

t = threading.Thread(target=wake)
t.start()
result = call(128, 0, TS(2, 0))
t.join()
assert result == (0, 0), f"Wait failed: {result}"
assert (1, 0) in wakes, f"Wake not seen in wakes: {wakes}"

print('FUTEX_OWNER_CONTROLS_OK EAGAIN TIMEOUT WAIT_WAKE', flush=True)
