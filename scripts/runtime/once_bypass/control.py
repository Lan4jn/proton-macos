import ctypes
import errno
import os
import sys

lib = ctypes.CDLL('libc.so.6', use_errno=True)
lib.syscall.restype = ctypes.c_long

word = ctypes.c_uint32(1)
uaddr = ctypes.addressof(word)

print(f"[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...", flush=True)

# Call futex WAIT with val=1
# Under baseline (no bypass), this call is passed expected 1 and will block until timeout or return.
# Under ELFUSE_DIAG_ONCE_BYPASS=1, the runtime detects uaddr, mutates word to 2, and returns 0 immediately.
ctypes.set_errno(0)
ret = lib.syscall(
    ctypes.c_long(98),
    ctypes.byref(word),
    ctypes.c_int(128), # FUTEX_WAIT_PRIVATE
    ctypes.c_uint32(1),
    ctypes.c_void_p(0),
    ctypes.c_void_p(0),
    ctypes.c_uint32(0)
)
err = ctypes.get_errno()

print(f"FUTEX_CALL_RETURNED ret={ret} err={err} final_word={word.value}", flush=True)
if ret == 0 and word.value == 2:
    print("ONCE_BYPASS_CONTROLS_OK MUTATED_TO_2", flush=True)
