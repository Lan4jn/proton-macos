import json
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT=pathlib.Path(__file__).resolve().parents[2]
PRODUCER_C=ROOT/'sources/p1-a-copy-round2/guest_producer.c'
ZIG='/opt/homebrew/bin/zig'

class GuestCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.bin_path = pathlib.Path(cls.tmp_dir.name)/'local_producer'
        cmd = ['clang', '-O2', str(PRODUCER_C), '-o', str(cls.bin_path)]
        subprocess.run(cmd, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def test_c_source_compiles_static_arm64_elf(self):
        with tempfile.TemporaryDirectory() as d:
            out_elf = pathlib.Path(d)/'producer_elf'
            cmd = [ZIG, 'cc', '-target', 'aarch64-linux-musl', '-O2', '-static', str(PRODUCER_C), '-o', str(out_elf)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            header = out_elf.read_bytes()[:20]
            self.assertTrue(header.startswith(b'\x7fELF\x02\x01\x01'))
            machine = struct.unpack('<H', header[18:20])[0]
            self.assertEqual(machine, 183)

    def _run_fake_host(self, handler):
        with tempfile.TemporaryDirectory() as d:
            sock_path = str(pathlib.Path(d)/'s')
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(sock_path); srv.listen(1)
            p = subprocess.Popen([str(self.bin_path), sock_path])
            conn, _ = srv.accept()
            def exact(n):
                data = b''
                while len(data) < n:
                    chunk = conn.recv(n - len(data))
                    if not chunk: raise EOFError()
                    data += chunk
                return data
            def recv_pkt():
                tot = struct.unpack('!I', exact(4))[0]
                jl = struct.unpack('!I', exact(4))[0]
                return json.loads(exact(jl)), exact(tot - 4 - jl)
            def send_raw(raw_str):
                conn.sendall(struct.pack('!II', len(raw_str) + 4, len(raw_str)) + raw_str.encode())
            try:
                handler(recv_pkt, send_raw, conn)
            finally:
                p.wait(timeout=5)
                conn.close()
                srv.close()
            return p.returncode

    def test_real_recorded_b605_acks_flow_succeeds(self):
        # 注入真实 b605 实测录制的完整 ACK（含 host_age_ms decimal float、capture_domain 等真实字段）
        def handler(recv_pkt, send_raw, conn):
            h, _ = recv_pkt()
            self.assertEqual(h['type'], 'CREATE')
            send_raw('{"type":"ACK","sid":1,"ack_for":"CREATE","gen":1,"v":1,"stage":"CONFIGURED"}')
            h, p = recv_pkt()
            self.assertEqual(h['type'], 'FRAME')
            crc = h['crc32']
            # 真实 b605 RECEIVED ACK 录制
            send_raw(f'{{"seq":1,"gen":1,"v":1,"type":"ACK","crc32":{crc},"slot":0,"sid":1,"ack_for":"FRAME","host_ns":62619015545291,"stage":"RECEIVED","ready_depth":1}}')
            # 真实 b605 CONSUMED ACK 录制（含 float: "host_age_ms":29.560625 与完整真实未知字段）
            send_raw(f'{{"gen":1,"crc32":{crc},"disposition":"displayed","ack_for":"FRAME","host_ns":62619045104000,"host_age_ms":29.560625,"stage":"CONSUMED","seq":1,"capture_match":1,"slot":0,"capture_domain":"NSView cacheDisplay normalized RGBA8 opaque sRGB; not screen","sid":1,"type":"ACK","capture_crc32":{crc},"v":1}}')
            h, _ = recv_pkt()
            self.assertEqual(h['type'], 'CLOSE')
            send_raw('{"v":1,"type":"ACK","ack_for":"CLOSE","stage":"CLOSED"}')
        rc = self._run_fake_host(handler)
        self.assertEqual(rc, 0)

    def test_trailing_garbage_rejected(self):
        # 变异测试：JSON 闭合后有尾随垃圾字符，必须被解析器拒绝
        def handler(recv_pkt, send_raw, conn):
            recv_pkt()
            send_raw('{"type":"ACK","sid":1,"ack_for":"CREATE","gen":1,"v":1,"stage":"CONFIGURED"} GARBAGE')
        rc = self._run_fake_host(handler)
        self.assertNotEqual(rc, 0)

    def test_missing_closing_brace_rejected(self):
        # 变异测试：JSON 缺少右大括号，必须被解析器拒绝
        def handler(recv_pkt, send_raw, conn):
            recv_pkt()
            send_raw('{"type":"ACK","sid":1,"ack_for":"CREATE","gen":1,"v":1,"stage":"CONFIGURED"')
        rc = self._run_fake_host(handler)
        self.assertNotEqual(rc, 0)

    def test_unknown_duplicate_key_rejected(self):
        # 变异测试：未知字段出现重复 key "unknown":1, "unknown":2，必须被严格拒绝
        def handler(recv_pkt, send_raw, conn):
            recv_pkt()
            send_raw('{"type":"ACK","sid":1,"ack_for":"CREATE","gen":1,"v":1,"stage":"CONFIGURED","unknown":1,"unknown":2}')
        rc = self._run_fake_host(handler)
        self.assertNotEqual(rc, 0)

    def test_bad_crc_in_consumed_fails(self):
        def handler(recv_pkt, send_raw, conn):
            recv_pkt()
            send_raw('{"v":1,"type":"ACK","ack_for":"CREATE","stage":"CONFIGURED","sid":1,"gen":1}')
            h, p = recv_pkt()
            crc = h['crc32']
            send_raw(f'{{"v":1,"type":"ACK","ack_for":"FRAME","stage":"RECEIVED","sid":1,"gen":1,"seq":1,"slot":0,"crc32":{crc}}}')
            send_raw(f'{{"v":1,"type":"ACK","ack_for":"FRAME","stage":"CONSUMED","sid":1,"gen":1,"seq":1,"slot":0,"crc32":{crc + 1},"disposition":"displayed"}}')
        rc = self._run_fake_host(handler)
        self.assertNotEqual(rc, 0)

    def test_bad_slot_pairing_fails(self):
        def handler(recv_pkt, send_raw, conn):
            recv_pkt()
            send_raw('{"v":1,"type":"ACK","ack_for":"CREATE","stage":"CONFIGURED","sid":1,"gen":1}')
            h, p = recv_pkt()
            crc = h['crc32']
            send_raw(f'{{"v":1,"type":"ACK","ack_for":"FRAME","stage":"RECEIVED","sid":1,"gen":1,"seq":1,"slot":0,"crc32":{crc}}}')
            send_raw(f'{{"v":1,"type":"ACK","ack_for":"FRAME","stage":"CONSUMED","sid":1,"gen":1,"seq":1,"slot":1,"crc32":{crc},"disposition":"displayed"}}')
        rc = self._run_fake_host(handler)
        self.assertNotEqual(rc, 0)

    def test_bad_gen_rejected(self):
        # 跨代负测：host 在 frame 阶段返回错误的 gen=2
        def handler(recv_pkt, send_raw, conn):
            recv_pkt()
            send_raw('{"v":1,"type":"ACK","ack_for":"CREATE","stage":"CONFIGURED","sid":1,"gen":1}')
            h, p = recv_pkt()
            crc = h['crc32']
            send_raw(f'{{"v":1,"type":"ACK","ack_for":"FRAME","stage":"RECEIVED","sid":1,"gen":2,"seq":1,"slot":0,"crc32":{crc}}}')
        rc = self._run_fake_host(handler)
        self.assertNotEqual(rc, 0)

    def test_no_ack_deadline_timeout_fails(self):
        def handler(recv_pkt, send_raw, conn):
            recv_pkt()
            time.sleep(4.5)
        start = time.monotonic()
        rc = self._run_fake_host(handler)
        self.assertNotEqual(rc, 0)
        self.assertLess(time.monotonic() - start, 8.0)

if __name__=='__main__':unittest.main()
