import socket
import threading
import time
import unittest
from rsp import RSP


class RSPTests(unittest.TestCase):
    def setUp(self):
        self.a,self.b = socket.socketpair()
        self.r = RSP(self.a, time.monotonic()+2)
    def tearDown(self):
        self.a.close(); self.b.close()
    def send(self, body):
        self.b.sendall(body)
    def test_valid_split_frame(self):
        parts = [b'+$',b'O',b'K#9a']
        t = threading.Thread(target=lambda: [self.send(p) for p in parts])
        t.start()
        try: self.assertEqual(self.r.receive(),'OK')
        finally: t.join()
        self.assertEqual(self.b.recv(1),b'+')
    def test_bad_checksum(self):
        self.send(b'$OK#00')
        with self.assertRaises(ValueError): self.r.receive()
    def test_eof(self):
        self.b.shutdown(socket.SHUT_WR)
        with self.assertRaises(EOFError): self.r.receive()
    def test_prefix_bound(self):
        self.send(b'+'*128)
        with self.assertRaises(ValueError): self.r.receive()
    def test_size_bound(self):
        self.send(b'$'+b'a'*4097)
        with self.assertRaises(ValueError): self.r.receive()
    def test_disallow_mutations(self):
        for cmd in ['M1000,4:deadbeef','P0=00','k','c','qRcmd,1234','Hg-1']:
            with self.subTest(cmd=cmd),self.assertRaises(ValueError): self.r.query(cmd)
    def test_deadline(self):
        self.r.deadline = time.monotonic()-1
        with self.assertRaises(TimeoutError): self.r.receive()

if __name__ == '__main__': unittest.main()
