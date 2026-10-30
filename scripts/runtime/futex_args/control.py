import ctypes,errno,threading,time
lib=ctypes.CDLL('libc.so.6',use_errno=True); lib.syscall.restype=ctypes.c_long
word=ctypes.c_uint32(0)
class TS(ctypes.Structure): _fields_=[('sec',ctypes.c_long),('nsec',ctypes.c_long)]
def call(op,val,timeout=None):
    ctypes.set_errno(0)
    ret=lib.syscall(ctypes.c_long(98),ctypes.byref(word),ctypes.c_int(op),ctypes.c_uint32(val),ctypes.byref(timeout) if timeout is not None else ctypes.c_void_p(0),ctypes.c_void_p(0),ctypes.c_uint32(0))
    return ret,ctypes.get_errno()
print('[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...',flush=True)
assert call(128,1)==(-1,errno.EAGAIN)
assert call(128,0,TS(0,20000000))==(-1,errno.ETIMEDOUT)
wakes=[]
def wake():
    for _ in range(50):
        time.sleep(.01); r=call(129,1); wakes.append(r)
        if r[0]==1: return
t=threading.Thread(target=wake); t.start(); result=call(128,0,TS(1,0)); t.join(); assert result==(0,0),result; assert (1,0) in wakes,wakes
print('FUTEX_CONTROLS_OK EAGAIN TIMEOUT WAIT_WAKE',flush=True)
