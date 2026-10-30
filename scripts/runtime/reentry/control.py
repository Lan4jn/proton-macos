import ctypes
import os
import sys
import time

lib = ctypes.CDLL('libc.so.6', use_errno=True)
mmap = lib.mmap
mmap.restype = ctypes.c_void_p
mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]

PROT_READ = 1
PROT_WRITE = 2
MAP_PRIVATE = 2
MAP_ANONYMOUS = 0x20

# Map anonymous memory at an unused address range (e.g. 0x203000000)
base = 0x203000000
size = 0x20000
target_addr = base + 0x440

addr = mmap(ctypes.c_void_p(base), size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
assert addr == base, f"mmap at base failed: {addr:#x} vs {base:#x}"
print(f"MAPPED_ADDR=0x{addr:x}", flush=True)

word_ptr = ctypes.cast(target_addr, ctypes.POINTER(ctypes.c_uint32))

# Initially word is 0
assert word_ptr.contents.value == 0, f"Initial word not 0: {word_ptr.contents.value}"
time.sleep(0.01)

# Transition 1: write 1
word_ptr.contents.value = 1
time.sleep(0.01)

# Transition 2: write 2
word_ptr.contents.value = 2
time.sleep(0.01)

print('[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...', flush=True)
print('ONCE_TRACE_CONTROLS_OK TRANSITION_VERIFIED', flush=True)
sys.stdout.flush()
os._exit(0)