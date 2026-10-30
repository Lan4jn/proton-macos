import ctypes
import os
import sys
import time

AT_SYSINFO_EHDR = 33
CLOCK_MONOTONIC = 1

class Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]

libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.getauxval.argtypes = [ctypes.c_ulong]
libc.getauxval.restype = ctypes.c_ulong
libc.clock_gettime.argtypes = [ctypes.c_int, ctypes.POINTER(Timespec)]
libc.clock_gettime.restype = ctypes.c_int

base = libc.getauxval(AT_SYSINFO_EHDR)
print(f"VDSO_PROBE_START pid={os.getpid()}", flush=True)
print(f"AT_SYSINFO_EHDR=0x{base:x}", flush=True)
if base:
    print(f"VDSO_CLOCK_GETTIME_ST_VALUE=0x148 ENTRY=0x{base+0x148:x}", flush=True)

# Through glibc's public wrapper (expected to choose vDSO when usable).
ts = Timespec()
for i in range(1000):
    rc = libc.clock_gettime(CLOCK_MONOTONIC, ctypes.byref(ts))
    if rc != 0:
        err = ctypes.get_errno()
        print(f"LIBC_CLOCK_GETTIME_FAIL iteration={i} errno={err}", flush=True)
        sys.exit(10)
print(f"LIBC_CLOCK_GETTIME_PASS iterations=1000 sec={ts.tv_sec} nsec={ts.tv_nsec}", flush=True)

# Directly call the synthetic vDSO symbol to isolate its mapped entry.
if base:
    vdso_fn_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(Timespec))
    vdso_clock_gettime = vdso_fn_type(base + 0x148)
    for i in range(1000):
        rc = vdso_clock_gettime(CLOCK_MONOTONIC, ctypes.byref(ts))
        if rc != 0:
            err = ctypes.get_errno()
            print(f"DIRECT_VDSO_CLOCK_GETTIME_FAIL iteration={i} rc={rc} errno={err}", flush=True)
            sys.exit(11)
    print(f"DIRECT_VDSO_CLOCK_GETTIME_PASS iterations=1000 sec={ts.tv_sec} nsec={ts.tv_nsec}", flush=True)
else:
    print("AT_SYSINFO_EHDR_MISSING", flush=True)
    sys.exit(12)

print("VDSO_PROBE_PASS", flush=True)
