"""Bounded, read-only subset for elfuse's local GDB RSP stub."""
import re
import time


class RSP:
    def __init__(self, sock, deadline):
        self.sock = sock
        self.deadline = deadline

    def byte(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError('RSP capture deadline')
        self.sock.settimeout(min(2, left))
        data = self.sock.recv(1)
        if not data:
            raise EOFError('RSP EOF')
        return data

    def receive(self):
        for _ in range(128):
            if self.byte() == b'$':
                break
        else:
            raise ValueError('RSP framing prefix exceeded')
        payload = bytearray()
        for _ in range(4097):
            c = self.byte()
            if c == b'#':
                break
            payload.extend(c)
        else:
            raise ValueError('RSP packet exceeds 4096 bytes')
        if len(payload) > 4096:
            raise ValueError('RSP packet exceeds 4096 bytes')
        checksum = self.byte() + self.byte()
        if int(checksum, 16) != sum(payload) % 256:
            raise ValueError('RSP checksum mismatch')
        if b'}' in payload or b'*' in payload:
            raise ValueError('RSP escaped/RLE packet unsupported')
        self.sock.sendall(b'+')
        return payload.decode('ascii')

    def query(self, command):
        if not re.fullmatch(r'(?:qfThreadInfo|qsThreadInfo|Hg[0-9a-f]{1,16}|p[0-9a-f]{1,2}|D)', command):
            raise ValueError('Command outside read-only capture subset')
        data = command.encode('ascii')
        self.sock.sendall(b'$' + data + b'#' + ('%02x' % (sum(data) % 256)).encode())
        return self.receive()

    def capture(self):
        self.sock.sendall(b'\x03')
        stop = self.receive()
        if not stop.startswith(('T', 'S')):
            raise ValueError('Expected stopped target response: '+stop)
        thread_list = self.query('qfThreadInfo')
        if not re.fullmatch(r'm[0-9a-f]+(?:,[0-9a-f]+)*', thread_list):
            raise ValueError('Invalid or empty thread response')
        tids = thread_list[1:].split(',')
        result = {'stop': stop, 'thread_list': tids, 'threads': [], 'truncated': len(tids)>16}
        for tid in tids[:16]:
            selected = self.query('Hg'+tid)
            if selected != 'OK':
                result['threads'].append({'tid':tid, 'selection_error':selected})
                continue
            values = {'tid':tid, 'registers':{}}
            for label, number in [('pc','20'), ('sp','1f'), ('fp','1d'), ('lr','1e'), ('x8','8')]:
                raw = self.query('p'+number)
                values['registers'][label] = {'raw':raw}
                if re.fullmatch('[0-9a-fA-F]{16}', raw):
                    values['registers'][label]['value'] = hex(int.from_bytes(bytes.fromhex(raw),'little'))
            result['threads'].append(values)
        result['detach'] = self.query('D')
        return result
