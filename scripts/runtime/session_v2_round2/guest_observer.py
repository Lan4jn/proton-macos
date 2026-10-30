"""P0-owned guest observer: phase logs are token matched, raw lines retained."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
helper = HERE / 'guest_wrapper.py'
if hashlib.sha256(helper.read_bytes()).hexdigest() != '8f3d09c22ea5fe76627b18ab341904471adafe90c6e338ea1b2d1cd08e4787cb':
    raise SystemExit('helper SHA mismatch')
spec = importlib.util.spec_from_file_location('helper', helper)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

MAX_TAIL_BYTES = 65536

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--runtime', required=True)
    ap.add_argument('--fake', action='store_true')
    ap.add_argument('--stall', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    token = uuid.uuid4().hex
    owner = json.loads((Path(os.environ['HOME']).parent / 'owned.json').read_text())
    result = {
        'status': 'UNKNOWN',
        'guest_evidence': 'SIMULATED' if args.fake else 'REAL',
        'stdout_coverage': 'unknown',
        'runtime_exit': None,
        'snapshots': [],
        'raw_snapshots': [],
        'events': [],
        'error': None,
    }
    proc = None
    try:
        if args.fake:
            command = [sys.executable, '-I', args.runtime, str(root / 'tmp'), token]
        else:
            command = [
                args.runtime,
                '--sysroot', str(root),
                '--timeout', '12',
                '--workdir', '/tmp',
                '--clear-env',
                str(root / 'bin/probe'),
                '/tmp',
                token,
            ]
        result['runtime_command'] = command
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=open(Path.cwd() / 'guest-stderr.log', 'xb'),
        )
        fd = proc.stdout.fileno()
        buf = b''
        with (Path.cwd() / 'guest-raw.log').open('xb') as raw:
            for phase in ('parent', 'pre', 'post', 'child_exit'):
                deadline = time.monotonic() + 4.0
                while True:
                    if b'\n' in buf:
                        line_bytes, buf = buf.split(b'\n', 1)
                        raw.write(line_bytes + b'\n')
                        raw.flush()
                        try:
                            value = json.loads(line_bytes.decode('utf-8', errors='replace'))
                        except ValueError:
                            continue
                        if not isinstance(value, dict) or value.get('token') != token:
                            continue
                        rec = h.parse_phase(line_bytes.decode('utf-8'), phase, token)
                        result['events'].append(rec)
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('phase deadline for ' + phase)
                    ready, _, _ = select.select([fd], [], [], remaining)
                    if not ready:
                        raise TimeoutError('phase deadline for ' + phase)
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        if buf:
                            raw.write(buf)
                            raw.flush()
                        raise EOFError('phase stream EOF before ' + phase)
                    buf += chunk
                    if len(buf) > 65536:
                        raise ValueError('phase stream line too long')

                if phase in ('pre', 'post'):
                    raw_snapshot = h.snapshot()
                    result['raw_snapshots'].append(raw_snapshot)
                    chain = h.inspect(raw_snapshot, owner, os.getpid(), proc.pid)
                    result['snapshots'].append(chain)
                    (Path.cwd() / 'guest-pre.json').write_text(json.dumps(result, indent=2))
                    if args.stall and phase == 'pre':
                        while True:
                            time.sleep(60)
                    (root / 'tmp' / (phase + '.ack')).write_text(token)

            # Drain tail of stdout up to 3s deadline or budget
            if buf:
                raw.write(buf)
                raw.flush()
                buf = b''
            tail_read = 0
            tail_deadline = time.monotonic() + 3.0
            stdout_coverage = 'complete'
            while True:
                remaining = tail_deadline - time.monotonic()
                if remaining <= 0:
                    stdout_coverage = 'partial'
                    break
                ready, _, _ = select.select([fd], [], [], remaining)
                if not ready:
                    stdout_coverage = 'partial'
                    break
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                if tail_read + len(chunk) > MAX_TAIL_BYTES:
                    allowed = MAX_TAIL_BYTES - tail_read
                    raw.write(chunk[:allowed])
                    raw.flush()
                    stdout_coverage = 'partial'
                    break
                raw.write(chunk)
                raw.flush()
                tail_read += len(chunk)
            result['stdout_coverage'] = stdout_coverage

        result['runtime_exit'] = proc.wait(timeout=3)
        if result['runtime_exit'] != 0:
            raise ValueError(f'runtime exit {result["runtime_exit"]}')
        pre, post = result['snapshots']
        if [(r['pid'], r['identity'], r['ppid']) for r in pre] != [(r['pid'], r['identity'], r['ppid']) for r in post]:
            raise ValueError('identity changed')
        if result['events'][2]['result'] != result['events'][2]['pid']:
            raise ValueError('setsid failed')
        result['status'] = 'PASS'
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        (Path.cwd() / 'guest-observer.json').write_text(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__':
    sys.exit(main())
