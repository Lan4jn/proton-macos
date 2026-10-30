import ctypes
import json
import os
from pathlib import Path
import platform
import struct
import sys

PATTERN = 0x1234ABCD
SIZE = 65536

def classify(obs):
    if obs.get('cleanup_errors') or obs.get('error'):
        return 'PROBE_ERROR'
    if obs.get('before') != {'shared_rw':0, 'private_ro':0, 'shared_ro':0}:
        return 'INVALID_INITIAL_STATE'
    after = obs.get('after', {})
    if after.get('shared_rw') != PATTERN or after.get('shared_ro') != PATTERN or obs.get('file_value') != PATTERN:
        return 'SHARED_OR_FILE_UPDATE_FAILED'
    if after.get('private_ro') == PATTERN:
        return 'OBSERVED_COHERENT'
    if after.get('private_ro') == 0:
        return 'PRIVATE_STALE_BUT_SHARED_OK'
    return 'UNEXPECTED_PRIVATE_VALUE'

def main():
    lab = Path(__file__).resolve().parents[3]
    path = Path(sys.argv[1])
    if not path.is_absolute() or not path.parent.resolve().is_relative_to(lab/'fixtures/runtime/private-map-coherence'):
        raise ValueError('Probe file must have a lab-local absolute path')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_longlong]
    libc.mmap.restype = ctypes.c_void_p
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    libc.munmap.restype = ctypes.c_int
    fd = os.open(path, os.O_RDWR|os.O_CREAT|os.O_EXCL, 0o600)
    maps = {}; obs = {'platform':platform.system(), 'file':str(path), 'size':SIZE, 'cleanup_errors':[]}
    try:
        os.ftruncate(fd, SIZE)
        for name, prot, flags in [('shared_rw',3,1), ('private_ro',1,2), ('shared_ro',1,1)]:
            ptr = libc.mmap(None, SIZE, prot, flags, fd, 0)
            if ptr == ctypes.c_void_p(-1).value or ptr is None:
                raise OSError(ctypes.get_errno(), 'mmap failed: '+name)
            maps[name] = ptr
        obs['addresses'] = {k:hex(v) for k,v in maps.items()}
        obs['before'] = {k:ctypes.c_uint32.from_address(p).value for k,p in maps.items()}
        ctypes.c_uint32.from_address(maps['shared_rw']).value = PATTERN
        obs['after'] = {k:ctypes.c_uint32.from_address(p).value for k,p in maps.items()}
        obs['file_value'] = struct.unpack('<I',os.pread(fd,4,0))[0]
        os.fsync(fd)
        obs['private_after_fsync'] = ctypes.c_uint32.from_address(maps['private_ro']).value
    except Exception as e:
        obs['error'] = repr(e)
    finally:
        for name, ptr in maps.items():
            if libc.munmap(ptr, SIZE) != 0:
                obs['cleanup_errors'].append({'map':name, 'errno':ctypes.get_errno()})
        os.close(fd)
    obs['verdict'] = classify(obs)
    print(json.dumps(obs, sort_keys=True),flush=True)
    return 0 if obs['verdict'] in ('OBSERVED_COHERENT','PRIVATE_STALE_BUT_SHARED_OK') else 2

if __name__ == '__main__': raise SystemExit(main())
