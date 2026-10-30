"""Length framed v1 with one deadline across each packet."""
import json
import struct
from deadline_io import send_all,read_exact

LIMIT=16*1024*1024

def send_packet(sock,header,payload,deadline):
    encoded=json.dumps(header,separators=(',',':')).encode('utf8')
    total=4+len(encoded)+len(payload)
    if total>LIMIT or len(encoded)>65536:raise ValueError('packet too large')
    send_all(sock,struct.pack('!II',total,len(encoded))+encoded,deadline)
    if payload:send_all(sock,payload,deadline)

def receive_packet(sock,deadline):
    total=struct.unpack('!I',read_exact(sock,4,deadline))[0]
    if total<4 or total>LIMIT:raise ValueError('length')
    jsonlen=struct.unpack('!I',read_exact(sock,4,deadline))[0]
    if jsonlen<2 or jsonlen>min(65536,total-4):raise ValueError('JSON length')
    obj=json.loads(read_exact(sock,jsonlen,deadline))
    if not isinstance(obj,dict):raise ValueError('JSON object')
    return obj,read_exact(sock,total-4-jsonlen,deadline)
