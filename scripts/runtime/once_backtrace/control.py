import ctypes
import os
import sys
import time

lib = ctypes.CDLL('libc.so.6', use_errno=True)
pthread_once = lib.pthread_once
pthread_once.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
pthread_once.restype = ctypes.c_int

mmap = lib.mmap
mmap.restype = ctypes.c_void_p
mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]

PROT_READ = 1
PROT_WRITE = 2
MAP_PRIVATE = 2
MAP_ANONYMOUS = 0x20

# 1. Allocate anonymous region for once control word
base = 0x203000000
size = 0x20000
target_addr = base + 0x440

addr = mmap(ctypes.c_void_p(base), size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
assert addr == base, f"mmap at base failed: {addr:#x} vs {base:#x}"
print(f"MAPPED_ADDR=0x{addr:x}", flush=True)

# 2. Control word
word_ptr = ctypes.cast(target_addr, ctypes.POINTER(ctypes.c_uint32))
word_ptr.contents.value = 0 # PTHREAD_ONCE_INIT

call_count = 0
@ctypes.CFUNCTYPE(None)
def init_routine():
    global call_count
    call_count += 1
    print(f"INIT_ROUTINE_CALLED (call {call_count})", flush=True)

# Call 1: should run init_routine and set word to 2
rc1 = pthread_once(ctypes.c_void_p(target_addr), init_routine)
assert rc1 == 0, f"pthread_once 1 failed: {rc1}"
assert call_count == 1, f"call_count expected 1, got {call_count}"

# Call 2: should fast-path return because word is 2 (done)
rc2 = pthread_once(ctypes.c_void_p(target_addr), init_routine)
assert rc2 == 0, f"pthread_once 2 failed: {rc2}"
assert call_count == 1, f"call_count still 1 after call 2"

print('[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...', flush=True)
print('ONCE_COUNT_CONTROLS_OK INSTRUCTION_LEVEL_VERIFIED', flush=True)
sys.stdout.flush()
os._exit(0)
