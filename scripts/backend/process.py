"""Bounded experiment runner. Isolation of paths/env is not an OS sandbox.
Controlled supervisor pattern ensures PID/PGID leader identity is held alive
until process group cleanup is executed, preventing PID reuse hazards and orphan leakage.

Boundary Note:
Guarantees cleanup of all descendants remaining in the supervisor's session/process group.
Processes that explicitly call setsid() detach into independent sessions and cannot be
reached via the group; unrelated control processes of the user are never scanned or signaled.
"""
import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
SUPERVISOR_SCRIPT = LAB / 'scripts/backend/supervisor.py'
SAFE_HOST_KEYS = ('SYSTEMROOT',)


def run_isolated(argv, log_root, timeout=30, extra_env=None, cwd=None):
    root = Path(log_root).resolve()
    if not root.is_relative_to(LAB) or not argv or timeout <= 0:
        raise ValueError('Expected lab-local log directory, nonempty argv and positive timeout')
    root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    for name in ('home', 'tmp', 'xdg-runtime', 'xdg-config', 'xdg-cache'):
        (run / name).mkdir(mode=0o700)
    env = {
        'PATH': '/usr/bin:/bin',
        'LANG': 'C.UTF-8',
        'HOME': str(run / 'home'),
        'TMPDIR': str(run / 'tmp'),
        'XDG_RUNTIME_DIR': str(run / 'xdg-runtime'),
        'XDG_CONFIG_HOME': str(run / 'xdg-config'),
        'XDG_CACHE_HOME': str(run / 'xdg-cache'),
    }
    for k, v in (extra_env or {}).items():
        if k.startswith(('DYLD_', 'LD_')):
            raise ValueError('Host loader injection variables are excluded')
        if k in ('HOME', 'TMPDIR', 'WINEPREFIX') or k.startswith('XDG_'):
            if not Path(v).resolve().is_relative_to(LAB):
                raise ValueError('Environment paths must remain inside lab')
        env[k] = str(v)
    work = Path(cwd or LAB).resolve()
    if not work.is_relative_to(LAB):
        raise ValueError('Working directory must be inside lab')

    started = time.monotonic()
    timed_out = False
    proc = None
    cleanup_errors = []
    target_rc = None
    supervisor_rc = None

    status_file = run / 'supervisor-status.json'
    r_status, w_status = os.pipe()
    r_ctl, w_ctl = os.pipe()

    supervisor_cmd = [
        sys.executable,
        str(SUPERVISOR_SCRIPT),
        str(status_file),
        str(w_status),
        str(r_ctl),
        str(work),
        '--',
    ] + [str(x) for x in argv]

    with (run / 'stdout.log').open('x') as out, (run / 'stderr.log').open('x') as err:
        try:
            try:
                proc = subprocess.Popen(
                    supervisor_cmd,
                    cwd=work,
                    env=env,
                    stdout=out,
                    stderr=err,
                    pass_fds=[w_status, r_ctl],
                    start_new_session=True,
                )
            except Exception as e:
                cleanup_errors.append(f'Supervisor launch failed: {e}')
                target_rc = None

            # Parent closes child's ends of pipes
            if w_status is not None:
                try:
                    os.close(w_status)
                except OSError:
                    pass
                w_status = None
            if r_ctl is not None:
                try:
                    os.close(r_ctl)
                except OSError:
                    pass
                r_ctl = None

            if proc is not None:
                # Wait for supervisor notification with timeout using select on r_status
                rlist, _, _ = select.select([r_status], [], [], timeout)
                if not rlist:
                    timed_out = True
                    # Target timed out: true target_exit is None (unknown/not confirmed before KILL)
                    target_rc = None
                else:
                    try:
                        os.read(r_status, 1024)
                    except OSError as e:
                        cleanup_errors.append(f'Pipe read error: {e}')

                    # Read status file written by supervisor
                    if status_file.exists():
                        try:
                            status_data = json.loads(status_file.read_text())
                            target_rc = status_data.get('target_exit')
                            if status_data.get('error'):
                                cleanup_errors.append(f"Supervisor spawn error: {status_data['error']}")
                        except Exception as e:
                            cleanup_errors.append(f'Failed to read supervisor status: {e}')
                    else:
                        cleanup_errors.append('Supervisor status file missing')

        finally:
            # Close pipe descriptors
            for fd_var, name in ((w_status, 'w_status'), (r_ctl, 'r_ctl'), (r_status, 'r_status')):
                if fd_var is not None:
                    try:
                        os.close(fd_var)
                    except OSError:
                        pass

            # Cleanup process group strictly WHILE supervisor is STILL ALIVE (proc.poll() is None)
            # Never send signals after supervisor has been reaped!
            if proc is not None:
                try:
                    if proc.poll() is None:
                        # 1. Send SIGTERM to process group
                        try:
                            os.killpg(proc.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        except PermissionError as e:
                            cleanup_errors.append(str(e))
                        except OSError as e:
                            cleanup_errors.append(str(e))

                        # Grace period for cooperative processes
                        time.sleep(0.1 if timed_out else 0.05)

                        # 2. Always send SIGKILL to ensure stubborn target and grandchildren are eliminated
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        except PermissionError as e:
                            cleanup_errors.append(str(e))
                        except OSError as e:
                            cleanup_errors.append(str(e))

                        # 3. Reap supervisor with timeout protection
                        try:
                            proc.wait(timeout=1.0)
                        except subprocess.TimeoutExpired:
                            cleanup_errors.append('Supervisor wait timed out during cleanup')
                            try:
                                proc.kill()
                                proc.wait(timeout=1.0)
                            except Exception as e:
                                cleanup_errors.append(f'Force kill failed: {e}')
                        except Exception as e:
                            cleanup_errors.append(f'Supervisor wait error: {e}')
                    else:
                        # Supervisor already exited
                        try:
                            proc.wait(timeout=0.1)
                        except Exception:
                            pass
                except Exception as e:
                    cleanup_errors.append(f'Unexpected cleanup exception: {e}')

                supervisor_rc = proc.returncode

            # Close control pipe write end (notifying supervisor if still listening)
            if w_ctl is not None:
                try:
                    os.close(w_ctl)
                except OSError:
                    pass

    # Overall exit vs true target_exit:
    if timed_out:
        final_exit = 124  # Standard POSIX timeout exit code
    elif target_rc is not None:
        final_exit = target_rc
    else:
        final_exit = supervisor_rc if supervisor_rc is not None else 127

    # Cleanup or launch failure cannot result in overall exit 0
    if final_exit == 0 and cleanup_errors:
        final_exit = 125

    result = {
        'argv': [str(x) for x in argv],
        'exit': final_exit,
        'target_exit': target_rc,
        'supervisor_exit': supervisor_rc,
        'timed_out': timed_out,
        'seconds': round(time.monotonic() - started, 6),
        'run_dir': str(run),
        'cleanup_errors': cleanup_errors,
        'stdout': str(run / 'stdout.log'),
        'stderr': str(run / 'stderr.log'),
    }
    (run / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
