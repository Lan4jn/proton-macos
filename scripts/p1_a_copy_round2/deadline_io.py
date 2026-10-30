"""Bounded stream I/O with absolute monotonic deadlines."""
import errno
import os
import socket
import select
import time


def connect_unix(sock,path,deadline):
    sock.setblocking(False)
    result=sock.connect_ex(path)
    if result in (0,errno.EISCONN):return
    if result not in (errno.EINPROGRESS,errno.EALREADY,errno.EWOULDBLOCK):raise OSError(result,os.strerror(result))
    remaining=deadline-time.monotonic()
    if remaining<=0:raise TimeoutError('connect deadline')
    _,w,_=select.select([], [sock], [], remaining)
    if not w:raise TimeoutError('connect deadline')
    error=sock.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR)
    if error:raise OSError(error,os.strerror(error))


def read_exact(sock,size,deadline):
    sock.setblocking(False)
    result=bytearray()
    while len(result)<size:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('read deadline')
        r,_,_=select.select([sock], [], [], remaining)
        if not r:raise TimeoutError('read deadline')
        try:chunk=sock.recv(size-len(result))
        except BlockingIOError:continue
        if not chunk:raise EOFError('stream closed')
        result.extend(chunk)
    return bytes(result)


def send_all(sock,data,deadline):
    sock.setblocking(False)
    view=memoryview(data)
    while view:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('send deadline')
        _,w,_=select.select([], [sock], [], remaining)
        if not w:raise TimeoutError('send deadline')
        try:n=sock.send(view)
        except BlockingIOError:continue
        if n==0:raise EOFError('send closed')
        view=view[n:]
