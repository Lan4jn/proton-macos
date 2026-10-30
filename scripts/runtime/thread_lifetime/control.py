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

def futex_call(op, val, timeout=None):
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

worker_started = False
worker_exited = False

def worker_fn():
    global worker_started, worker_exited
    worker_started = True
    # Worker waits on futex for up to 1 second
    r, e = futex_call(128, 0, TS(1, 0)) # 128 = FUTEX_WAIT_PRIVATE
    # Worker finishes and exits
    worker_exited = True

# 1. Spawn worker thread
t = threading.Thread(target=worker_fn)
t.start()

# 2. Main thread waits briefly for worker to start and sleep
time.sleep(0.05)
assert worker_started, "Worker did not start"

# 3. Main thread wakes worker
woken = 0
for _ in range(20):
    r, e = futex_call(129, 1) # 129 = FUTEX_WAKE_PRIVATE
    if r == 1:
        woken = 1
        break
    time.sleep(0.01)

assert woken == 1, "Failed to wake worker thread"

# 4. Join worker thread
t.join(timeout=2.0)
assert not t.is_alive(), "Worker thread did not exit cleanly"
assert worker_exited, "Worker did not set exited flag"

# Wait 1.1 seconds so the watchdog takes at least one periodic snapshot
time.sleep(1.1)

print('THREAD_LIFETIME_CONTROLS_OK CLONE FUTEX EXIT SNAPSHOT', flush=True)
