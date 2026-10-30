import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/p1_a_copy_v2'))

class Governance(unittest.TestCase):
    def test_unique_directory_and_owned_cleanup_preserves_sentinel(self):
        spec = importlib.util.find_spec('session')
        self.assertIsNotNone(spec, 'owned session governance must exist before host launch')
        import session
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            run = session.new_run(root, 'first')
            with self.assertRaises(FileExistsError):
                session.new_run(root, 'first')
            sentinel = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
            try:
                owner = session.OwnedSession(run)
                child = owner.start([sys.executable, '-c', 'import time;time.sleep(60)'], 'child')
                records = owner.cleanup()
                self.assertFalse(records[0]['alive_after'])
                self.assertTrue(records[0]['p0_cleanup']['complete'])
                self.assertIsNone(sentinel.poll())
            finally:
                sentinel.terminate()
                sentinel.wait(timeout=3)

    def test_spawn_identity_failure_never_executes_target(self):
        import session
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            owner=session.OwnedSession(root)
            marker=root/'must-not-exist'
            code='import pathlib;pathlib.Path('+repr(str(marker))+').write_text("bad")'
            with patch.object(session.p0,'snapshot',side_effect=OSError('identity unavailable')):
                with self.assertRaises(OSError):
                    owner.start([sys.executable,'-c',code],'child')
            self.assertEqual(len(owner.children),1)
            records=owner.cleanup()
            self.assertFalse(marker.exists())
            self.assertIsNone(owner.children[0]['owner'])
            self.assertEqual(records[0]['p0_cleanup']['signals'],[])
            self.assertIsNotNone(owner.children[0]['worker'].returncode)

    def test_p0_signal_denied_is_recorded_without_retry(self):
        import session
        from unittest.mock import Mock,patch
        with tempfile.TemporaryDirectory() as d:
            row=dict(pid=12345,ppid=1,pgid=12345,state='S',identity='fixture-start')
            worker=Mock();worker.wait.return_value=None
            with patch.object(session.p0,'snapshot',return_value=[row]), patch.object(session.p0.os,'killpg',side_effect=PermissionError(1,'fixture denied')) as signal_call:
                report=session.p0.cleanup(pathlib.Path(d),row,worker)
            self.assertEqual(signal_call.call_count,1)
            self.assertFalse(report['complete'])
            self.assertIn('PermissionError',report['error'])

    def test_leader_exit_does_not_leak_owned_group_child(self):
        import session
        import time
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            owner=session.OwnedSession(root)
            # Descendant self-expires even if the regression fails.
            code='import subprocess,sys; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(2)"]); print(p.pid,flush=True)'
            leader=owner.start([sys.executable,'-c',code],'parent')
            leader.wait(timeout=3)
            child_pid=int((root/'parent.stdout').read_text().strip())
            try:
                records=owner.cleanup()
                live=subprocess.run(['ps','-p',str(child_pid),'-o','stat='],capture_output=True,text=True)
                self.assertTrue(not live.stdout.strip() or live.stdout.strip().startswith('Z'),live.stdout)
                self.assertIn(child_pid,records[0]['group_members_before'])
            finally:
                time.sleep(2.1) if leader.returncode is None else None

class Wire(unittest.TestCase):
    def test_fragmented_roundtrip_and_oversize_before_allocation(self):
        self.assertIsNotNone(importlib.util.find_spec('wire'), 'wire framing is missing')
        import wire
        import socket
        import struct
        import threading
        a, b = socket.socketpair()
        try:
            packet = wire.pack({'v': 1, 'type': 'FRAME'}, b'rgba')
            def send():
                for byte in packet:
                    a.sendall(bytes([byte]))
            thread = threading.Thread(target=send)
            thread.start()
            self.assertEqual(wire.receive(b), ({'v': 1, 'type': 'FRAME'}, b'rgba'))
            thread.join()
            a.sendall(struct.pack('!I', 16777217))
            with self.assertRaises(ValueError):
                wire.receive(b)
        finally:
            a.close()
            b.close()

class HeaderNegative(unittest.TestCase):
    def test_header_only_rejection_does_not_send_declared_payload(self):
        import probe
        import socket
        self.assertTrue(hasattr(probe,'send_header_only'),'header-only negative sender missing')
        a,b=socket.socketpair()
        try:
            meta,data=probe.frame(1)
            meta['gen']=2
            probe.send_header_only(a,meta,data)
            b.settimeout(.1)
            received=b.recv(65536)
            self.assertEqual(len(received),len(probe.pack(meta,data))-len(data))
        finally:a.close();b.close()

    def test_broken_pipe_requires_observed_error_not_automatic_pass(self):
        import probe
        self.assertTrue(hasattr(probe,'expect_rejection'),'BrokenPipe classification missing')
        class Channel:
            def wait(self,predicate):raise AssertionError('no ERROR observed')
        def broken_sender():raise BrokenPipeError(32,'fixture closed')
        with self.assertRaisesRegex(AssertionError,'no ERROR'):
            probe.expect_rejection(Channel(),broken_sender)

class Busy(unittest.TestCase):
    def test_native_busy_returns_after_requested_interval(self):
        import ctypes
        import time
        source=ROOT/'sources/p1-a-copy-v2/busy.c'
        self.assertTrue(source.is_file(),'native pure-compute producer hook missing')
        with tempfile.TemporaryDirectory() as d:
            lib=pathlib.Path(d)/'busy.dylib'
            subprocess.run(['clang','-O2','-dynamiclib',str(source),'-o',str(lib)],check=True)
            busy=ctypes.CDLL(str(lib));busy.busy_ns.argtypes=[ctypes.c_uint64];busy.busy_ns.restype=ctypes.c_uint64
            begin=time.monotonic()
            self.assertGreater(busy.busy_ns(30_000_000),0)
            self.assertGreaterEqual(time.monotonic()-begin,.03)

class AppKit(unittest.TestCase):
    def test_actual_payload_reaches_view_and_protocol_negatives(self):
        path = ROOT / 'scripts/p1_a_copy_v2/probe.py'
        self.assertTrue(path.is_file(), 'AppKit black-box probe must exist')
        result = subprocess.run([sys.executable, str(path), '--suite', 'smoke'],
                                cwd=str(ROOT), timeout=90)
        self.assertEqual(result.returncode, 0)

if __name__ == '__main__':
    unittest.main()
