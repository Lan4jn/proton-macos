import json, socket, struct, sys

server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
server.bind(sys.argv[1]);server.listen(1)
sock,_=server.accept()
def exact(n):
    data=b''
    while len(data)<n:
        part=sock.recv(n-len(data))
        if not part:raise EOFError()
        data+=part
    return data
def recv():
    total=struct.unpack('!I',exact(4))[0];jl=struct.unpack('!I',exact(4))[0]
    h=json.loads(exact(jl));return h,exact(total-4-jl)
def send(h):
    raw=json.dumps(h).encode();sock.sendall(struct.pack('!II',len(raw)+4,len(raw))+raw)
h,_=recv();send(dict(v=1,type='ACK',ack_for='CREATE',stage='CONFIGURED',sid=1,gen=1))
while True:
    h,data=recv()
    if h['type']=='CLOSE':
        send(dict(v=1,type='ACK',ack_for='CLOSE',stage='CLOSED'));break
    a=dict(v=1,type='ACK',ack_for='FRAME',sid=1,gen=1,seq=h['seq'],slot=0,crc32=h['crc32'])
    send(dict(a,stage='RECEIVED'));send(dict(a,stage='CONSUMED',disposition='displayed',capture_match=True))
sock.close();server.close()
