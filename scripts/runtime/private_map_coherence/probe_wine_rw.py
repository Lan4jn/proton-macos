import ctypes
import json
import os
from pathlib import Path
import sys

SIZE = 65536
FIRST = 0x1234abcd
SECOND = 0x55667788
PRIVATE = 0xdeadbeef


def main():
    path = Path(sys.argv[1])
    lab = Path(__file__).resolve().parents[3]
    if not path.is_absolute() or path.is_symlink() or path.parent.resolve() != lab/'fixtures/runtime/private-map-coherence':
        raise ValueError('Expected a new file directly in the lab probe directory')
    rw = os.open(path, os.O_CREAT|os.O_EXCL|os.O_RDWR, 0o600)
    ro = -1
    maps = {}
    obs = {'file': str(path), 'mapping_length': SIZE, 'client_fd_access':'O_RDONLY',
           'client_prot': 'READ|WRITE', 'client_flags':'MAP_PRIVATE', 'cleanup_errors':[]}
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_longlong]
    libc.mmap.restype = ctypes.c_void_p
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    libc.munmap.restype = ctypes.c_int
    try:
        os.ftruncate(rw, SIZE)
        ro = os.open(path, os.O_RDONLY)
        for name, flags, fd in [('server_shared',1,rw), ('client_private',2,ro)]:
            p = libc.mmap(None, SIZE, 3, flags, fd, 0)
            if p is None or p == ctypes.c_void_p(-1).value:
                raise OSError(ctypes.get_errno(), 'mmap '+name)
            maps[name] = p
        read = lambda name: ctypes.c_uint32.from_address(maps[name]).value
        obs['initial'] = {k:read(k) for k in maps}
        ctypes.c_uint32.from_address(maps['server_shared']).value = FIRST
        obs['after_server_write'] = {k:read(k) for k in maps}
        ctypes.c_uint32.from_address(maps['client_private']).value = PRIVATE
        obs['after_private_write'] = {k:read(k) for k in maps}
        ctypes.c_uint32.from_address(maps['server_shared']).value = SECOND
        obs['after_second_server_write'] = {k:read(k) for k in maps}
        obs['file_value'] = int.from_bytes(os.pread(rw, 4, 0),'little')
    except Exception as e:
        obs['error'] = repr(e)
    finally:
        for name,p in maps.items():
            if libc.munmap(p,SIZE): obs['cleanup_errors'].append([name,ctypes.get_errno()])
        if ro >= 0: os.close(ro)
        os.close(rw)
    if obs.get('error') or obs['cleanup_errors']:
        obs['verdict'] = 'PROBE_ERROR'
    elif obs['initial'] != {'server_shared':0,'client_private':0}:
        obs['verdict'] = 'INVALID_INITIAL_STATE'
    elif obs['after_private_write'] != {'server_shared':FIRST,'client_private':PRIVATE} or obs['after_second_server_write'] != {'server_shared':SECOND,'client_private':PRIVATE} or obs['file_value'] != SECOND:
        obs['verdict'] = 'PRIVATE_WRITE_ISOLATION_FAILED'
    elif obs['after_server_write']['server_shared'] != FIRST:
        obs['verdict'] = 'SHARED_UPDATE_FAILED'
    elif obs['after_server_write']['client_private'] == FIRST:
        obs['verdict'] = 'LIVE_UNTIL_PRIVATE_WRITE_OBSERVED'
    elif obs['after_server_write']['client_private'] == 0:
        obs['verdict'] = 'PRIVATE_SNAPSHOT_WITH_WRITE_ISOLATION'
    else:
        obs['verdict'] = 'UNEXPECTED_PRIVATE_VALUE'
    print(json.dumps(obs,sort_keys=True),flush=True)
    return 0 if obs['verdict'] in ('LIVE_UNTIL_PRIVATE_WRITE_OBSERVED','PRIVATE_SNAPSHOT_WITH_WRITE_ISOLATION') else 2

if __name__ == '__main__': raise SystemExit(main())
