import ctypes, os, sys
AT_SYSINFO_EHDR=33
class Timespec(ctypes.Structure):
 _fields_=[("tv_sec",ctypes.c_long),("tv_nsec",ctypes.c_long)]
libc=ctypes.CDLL("libc.so.6",use_errno=True)
libc.getauxval.argtypes=[ctypes.c_ulong]; libc.getauxval.restype=ctypes.c_ulong
libc.clock_gettime.argtypes=[ctypes.c_int,ctypes.POINTER(Timespec)]; libc.clock_gettime.restype=ctypes.c_int
base=libc.getauxval(AT_SYSINFO_EHDR)
print(f"VDSO_DISABLE_PROBE_START pid={os.getpid()} AT_SYSINFO_EHDR=0x{base:x}",flush=True)
if base != 0: print("FAIL: vDSO auxv still present",flush=True); sys.exit(1)
ts=Timespec()
for i in range(1000):
 rc=libc.clock_gettime(1,ctypes.byref(ts))
 if rc: print(f"CLOCK_GETTIME_FAIL i={i} errno={ctypes.get_errno()}",flush=True); sys.exit(2)
print(f"LIBC_CLOCK_GETTIME_SYSCALL_FALLBACK_PASS iterations=1000 sec={ts.tv_sec} nsec={ts.tv_nsec}",flush=True)
print("VDSO_DISABLE_PROBE_PASS",flush=True)
