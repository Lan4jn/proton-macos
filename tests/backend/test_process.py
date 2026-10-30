import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.backend.process import run_isolated

ROOT = Path(__file__).resolve().parents[2]

class ProcessTests(unittest.TestCase):
    def run_case(self, code, timeout=2):
        base = ROOT/'logs/backend/tests'
        base.mkdir(parents=True, exist_ok=True)
        return run_isolated([sys.executable, '-c', code], base, timeout=timeout)

    def test_exit_and_output(self):
        r = self.run_case("print('中文 with spaces');raise SystemExit(7)")
        self.assertEqual(r['exit'], 7)
        self.assertIn('中文 with spaces', Path(r['stdout']).read_text())

    def test_environment_isolation(self):
        os.environ['PROTON_LAB_SECRET_TEST'] = 'secret'
        try:
            r = self.run_case("import os,json;print(json.dumps(dict(os.environ)))")
        finally:
            del os.environ['PROTON_LAB_SECRET_TEST']
        text = Path(r['stdout']).read_text()
        self.assertNotIn('PROTON_LAB_SECRET_TEST', text)
        self.assertIn(str(ROOT), text)

    def test_timeout(self):
        r = self.run_case('import time;time.sleep(5)', timeout=0.1)
        self.assertTrue(r['timed_out'])
        self.assertEqual(r['exit'], 124)
        self.assertIsNone(r['target_exit'])

    def test_unique_logs(self):
        a=self.run_case('print(1)');b=self.run_case('print(2)')
        self.assertNotEqual(a['run_dir'], b['run_dir'])
        self.assertEqual(Path(a['stdout']).read_text().strip(), '1')

    def test_outside_lab_denied(self):
        with self.assertRaises(ValueError):
            run_isolated([sys.executable,'-c','pass'], Path('/tmp'),timeout=1)

    def test_child_survives_root_exit_cleaned_up(self):
        """Root exits cleanly with exit code 0, but leaves background descendant.
        Runner must preserve exit 0 AND clean up the descendant process without leaking."""
        code = (
            "import subprocess, sys, time\n"
            "p = subprocess.Popen(['sleep', '40'])\n"
            "with open('descendant.pid', 'w') as f: f.write(str(p.pid))\n"
            "sys.exit(0)\n"
        )
        r = self.run_case(code, timeout=3)
        self.assertEqual(r['exit'], 0)
        descendant_pid_file = Path(r['run_dir']) / 'home' / 'descendant.pid'
        if not descendant_pid_file.exists():
            descendant_pid_file = ROOT / 'descendant.pid'
        # Check if descendant pid was written
        # Either in cwd or run_dir
        # Let's verify descendant process is terminated
        # Give a brief moment for OS reaping
        time.sleep(0.2)
        # Verify no orphan sleep 40 remains
        import subprocess as sp
        check = sp.run(['pgrep', '-f', 'sleep 40'], capture_output=True, text=True)
        self.assertEqual(check.stdout.strip(), '', f"Leaked orphan process: {check.stdout}")

    def test_unrelated_control_process_survives(self):
        """Verify an unrelated control process belonging to current user is NOT killed."""
        import subprocess as sp, time
        control = sp.Popen(['sleep', '25'])
        try:
            r = self.run_case("print('isolated running');raise SystemExit(0)", timeout=2)
            self.assertEqual(r['exit'], 0)
            time.sleep(0.1)
            self.assertIsNone(control.poll(), "Unrelated control process was killed!")
        finally:
            control.terminate()
            control.wait()

    def test_no_signal_to_reaped_pid(self):
        """Directly observe and assert the timing of killpg vs process reaping:
        Assert every killpg is invoked while the supervisor is STILL ALIVE and holding its identity,
        and that NO signal is ever sent after the supervisor is reaped."""
        events = []
        real_killpg = os.killpg

        def observed_killpg(pid, sig):
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
            events.append(('killpg', pid, sig, alive))
            return real_killpg(pid, sig)

        with patch('scripts.backend.process.os.killpg', side_effect=observed_killpg):
            r = self.run_case("import sys; sys.exit(0)", timeout=2)

        self.assertEqual(r['exit'], 0)
        self.assertIn('supervisor_exit', r)
        self.assertTrue(len(events) > 0, "killpg should be called during process group cleanup")
        for ev, pid, sig, alive in events:
            self.assertEqual(ev, 'killpg')
            self.assertTrue(alive, f"killpg was called on a PID that was already dead/reaped! Event: {ev}, {pid}")

    def test_accurate_nonzero_exit_code(self):
        """Verify command exiting with specific code returns exact code."""
        r = self.run_case("import sys; sys.exit(42)", timeout=2)
        self.assertEqual(r['exit'], 42)
        self.assertIn('supervisor_exit', r)

    def test_supervisor_spawn_error_recorded(self):
        """Verify that an invalid/nonexistent executable is caught and recorded in cleanup_errors and result.json."""
        base = ROOT / 'logs/backend/tests'
        base.mkdir(parents=True, exist_ok=True)
        r = run_isolated(['/nonexistent/executable_that_fails_to_spawn'], base, timeout=2)
        self.assertNotEqual(r['exit'], 0)
        self.assertTrue(any('Supervisor spawn error' in e for e in r['cleanup_errors']))
        # Verify result.json contains the recorded cleanup_errors
        res_json = json.loads(Path(r['run_dir'], 'result.json').read_text())
        self.assertTrue(any('Supervisor spawn error' in e for e in res_json['cleanup_errors']))

    def test_child_ignoring_term_cleaned_up_on_normal_root_exit(self):
        """Root exits 0, but descendant explicitly ignores SIGTERM.
        Runner must preserve exit 0, target_exit 0, AND clean up the descendant via SIGKILL."""
        marker = ROOT / f"logs/backend/tests/gc_marker_{os.getpid()}_{time.time_ns()}.pid"
        if marker.exists():
            marker.unlink()
        code = (
            "import subprocess, sys, time\n"
            "from pathlib import Path\n"
            f"gc_code = 'import os, signal, time; from pathlib import Path; signal.signal(signal.SIGTERM, signal.SIG_IGN); Path(\"{marker}\").write_text(str(os.getpid())); time.sleep(45)'\n"
            "subprocess.Popen([sys.executable, '-c', gc_code])\n"
            f"for _ in range(50):\n"
            f"    if Path(\"{marker}\").exists():\n"
            f"        break\n"
            f"    time.sleep(0.05)\n"
            "sys.exit(0)\n"
        )
        try:
            r = self.run_case(code, timeout=3)
            self.assertEqual(r['exit'], 0)
            self.assertEqual(r['target_exit'], 0)
            self.assertFalse(r['timed_out'])
            self.assertTrue(marker.exists(), "Descendant did not write marker")
            gc_pid = int(marker.read_text().strip())
            time.sleep(0.1)
            gc_alive = True
            try:
                os.kill(gc_pid, 0)
            except OSError:
                gc_alive = False
            self.assertFalse(gc_alive, f"Descendant process {gc_pid} ignoring SIGTERM survived cleanup!")
        finally:
            if marker.exists():
                try:
                    pid = int(marker.read_text().strip())
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                marker.unlink(missing_ok=True)

    def test_target_ignoring_term_on_timeout(self):
        """Target ignores SIGTERM, writes ready marker with its PID, and sleeps.
        Runner must trigger timeout, report timed_out=True, exit=124, target_exit=None (not fake -15),
        and ensure target PID is terminated by SIGKILL and no longer alive."""
        marker = ROOT / f"logs/backend/tests/target_timeout_{os.getpid()}_{time.time_ns()}.pid"
        if marker.exists():
            marker.unlink()
        code = (
            "import os, signal, time\n"
            "from pathlib import Path\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"Path('{marker}').write_text(str(os.getpid()))\n"
            "time.sleep(30)\n"
        )
        try:
            r = self.run_case(code, timeout=1.2)
            self.assertTrue(r['timed_out'])
            self.assertEqual(r['exit'], 124)
            self.assertIsNone(r['target_exit'])
            self.assertTrue(marker.exists(), "Target did not write marker before timeout")
            target_pid = int(marker.read_text().strip())
            time.sleep(0.1)
            target_alive = True
            try:
                os.kill(target_pid, 0)
            except OSError:
                target_alive = False
            self.assertFalse(target_alive, f"Target process {target_pid} ignoring SIGTERM survived cleanup!")
        finally:
            if marker.exists():
                try:
                    pid = int(marker.read_text().strip())
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                marker.unlink(missing_ok=True)

    def test_supervisor_launch_oserror_persisted(self):
        """Mock failure on supervisor Popen launch.
        Runner must record launch error in cleanup_errors and result.json,
        preserve target_exit as None, and return non-zero exit."""
        base = ROOT / 'logs/backend/tests'
        base.mkdir(parents=True, exist_ok=True)
        with patch('scripts.backend.process.subprocess.Popen', side_effect=OSError("Mock launch failure")):
            r = run_isolated([sys.executable, '-c', 'pass'], base, timeout=2)
        self.assertNotEqual(r['exit'], 0)
        self.assertIsNone(r['target_exit'])
        self.assertTrue(any('Supervisor launch failed' in e for e in r['cleanup_errors']))
        res_json = json.loads(Path(r['run_dir'], 'result.json').read_text())
        self.assertTrue(any('Supervisor launch failed' in e for e in res_json['cleanup_errors']))

    def test_cleanup_wait_timeout_persisted(self):
        """Mock TimeoutExpired during supervisor cleanup wait.
        Runner must not lose result.json, record wait timeout error, and return non-zero exit."""
        base = ROOT / 'logs/backend/tests'
        base.mkdir(parents=True, exist_ok=True)
        real_popen = subprocess.Popen

        class MockProcWrapper:
            def __init__(self, real_p):
                self._p = real_p
                self._timed_out_once = False
            @property
            def pid(self):
                return self._p.pid
            @property
            def returncode(self):
                return self._p.returncode
            def poll(self):
                return self._p.poll()
            def kill(self):
                return self._p.kill()
            def wait(self, timeout=None):
                if timeout == 1.0 and not self._timed_out_once:
                    self._timed_out_once = True
                    raise subprocess.TimeoutExpired(cmd='supervisor', timeout=1.0)
                return self._p.wait(timeout=timeout)

        created_procs = []

        def mock_popen(*args, **kwargs):
            p = MockProcWrapper(real_popen(*args, **kwargs))
            created_procs.append(p)
            return p

        with patch('scripts.backend.process.subprocess.Popen', side_effect=mock_popen):
            r = run_isolated([sys.executable, '-c', 'pass'], base, timeout=2)

        # Ensure the mock wrapped process is cleanly reaped to prevent ResourceWarning
        # Do not swallow arbitrary exceptions: handle TimeoutExpired via kill+wait, ignore only ProcessLookupError
        for p in created_procs:
            try:
                p._p.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    p._p.kill()
                    p._p.wait(timeout=1.0)
                except ProcessLookupError:
                    pass
            except ProcessLookupError:
                pass
            self.assertIsNotNone(p._p.returncode, f"Mocked process {p.pid} was not cleanly reaped!")

        self.assertNotEqual(r['exit'], 0)
        self.assertTrue(any('Supervisor wait timed out during cleanup' in e for e in r['cleanup_errors']))
        res_json = json.loads(Path(r['run_dir'], 'result.json').read_text())
        self.assertTrue(any('Supervisor wait timed out during cleanup' in e for e in res_json['cleanup_errors']))

    def test_child_restores_default_sigterm_handler(self):
        """Verify that target child process starts with SIG_DFL for SIGTERM and never inherits SIG_IGN."""
        code = (
            "import signal\n"
            "h = signal.getsignal(signal.SIGTERM)\n"
            "assert h == signal.SIG_DFL, f'Unexpected handler: {h}'\n"
            "print('SIG_DFL_RESTORED')\n"
        )
        r = self.run_case(code, timeout=2)
        self.assertEqual(r['exit'], 0)
        self.assertEqual(r['target_exit'], 0)
        self.assertIn('SIG_DFL_RESTORED', Path(r['stdout']).read_text())

if __name__ == '__main__':
    unittest.main()
