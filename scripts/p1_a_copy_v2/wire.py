"""frame/ACK v1 stream framing, bounded before allocating body."""
import json
import struct

MAX_PACKET = 16 * 1024 * 1024


def pack(header, payload=b''):
    meta = json.dumps(header, separators=(',', ':')).encode()
    length = 4 + len(meta) + len(payload)
    if not 4 <= length <= MAX_PACKET:
        raise ValueError('packet length')
    return struct.pack('!II', length, len(meta)) + meta + payload


def exact(sock, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise EOFError('truncated or closed stream')
        chunks.extend(chunk)
    return bytes(chunks)


def receive(sock):
    length, = struct.unpack('!I', exact(sock, 4))
    if not 4 <= length <= MAX_PACKET:
        raise ValueError('packet length')
    meta_len, = struct.unpack('!I', exact(sock, 4))
    if not 2 <= meta_len <= min(length - 4, 65536):
        raise ValueError('JSON length')
    header = json.loads(exact(sock, meta_len))
    if not isinstance(header, dict):
        raise ValueError('JSON object required')
    return header, exact(sock, length - 4 - meta_len)
