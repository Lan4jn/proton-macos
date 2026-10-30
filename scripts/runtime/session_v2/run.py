#!/usr/bin/env python3
"""Bounded POSIX session runner. Only the parent writes receipt.json."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time

LAB = Path(__file__).resolve().parents[3]
LOGS = LAB / 'logs/session-v2'
GRACE = .3

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def save(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('x') as f:
        json.dump(value, f, indent=2); f.write('\n')
    tmp.replace(path)

def event(root, writer, kind, **data):
    with (root / (writer + '-events.jsonl')).open('a') as f:
        f.write(json.dumps(dict(monotonic=time.monotonic(), kind=kind, **data)) + '\n')

def snapshot():
    p = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,stat=,lstart='],
                       capture_output=True, text=True, check=True, timeout=3)
    rows = []
    for line in p.stdout.splitlines():
        a = line.split(None, 4)
        if len(a) == 5:
            rows.append(dict(pid=int(a[0]), ppid=int(a[1]), pgid=int(a[2]), state=a[3], identity=a[4]))
    return rows

def worker(root):
    cfg = json.loads((root/'config.json').read_text())
    signal.signal(signal.SIGTERM, lambda *_: None)
    signal.signal(signal.SIGINT, lambda *_: None)
    save(root/'ready.json', dict(pid=os.getpid(), pgid=os.getpgrp()))
    event(root, 'worker', 'ready', pid=os.getpid(), pgid=os.getpgrp())
    readable, _, _ = select.select([sys.stdin], [], [], 2)
    if not readable or sys.stdin.readline() != 'GO\n':
        event(root, 'worker', 'pre_exec_aborted')
        return 70
    result = dict(target_exit=None, target_exit_observed=False, inner_timed_out=False, error=None)
    try:
        with (root/'stdout.log').open('wb') as out, (root/'stderr.log').open('wb') as err:
            p = subprocess.Popen(cfg['command'], cwd=root/'work', env=cfg['environment'],
                                 stdin=subprocess.DEVNULL, stdout=out, stderr=err)
            event(root, 'worker', 'target_started', pid=p.pid, pgid=os.getpgrp())
            try:
                result['target_exit'] = p.wait(timeout=cfg['timeout'])
                result['target_exit_observed'] = True
            except subprocess.TimeoutExpired: result['inner_timed_out'] = True
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    event(root, 'worker', 'result', **result)
    save(root/'worker-result.json', result)
    # Keep the session leader PID reserved until parent finishes group cleanup.
    while True: time.sleep(60)

def cleanup(root, owner, proc):
    report = dict(observed=[], signals=[], complete=False, remaining=[])
    seen = {}
    def members():
        rows = snapshot()
        leader = next((r for r in rows if r['pid'] == owner['pid']), None)
        if leader is None or leader['identity'] != owner['identity'] or leader['pgid'] != owner['pgid']:
            raise RuntimeError('owned session leader identity lost; no signal sent')
        group = [r for r in rows if r['pgid'] == owner['pgid']]
        for r in group: seen[(r['pid'], r['identity'])] = r
        return group
    try:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            rows = members()
            live = [r for r in rows if not r['state'].startswith('Z')]
            if not live: break
            entry = dict(signal=sig.name, pgid=owner['pgid'], enumerated_pids=[r['pid'] for r in live])
            try:
                os.killpg(owner['pgid'], sig)
                entry['result'] = 'sent'
            except ProcessLookupError: entry['result'] = 'already_absent'
            report['signals'].append(entry)
            event(root, 'parent', 'cleanup_signal', **entry)
            deadline = time.monotonic() + GRACE
            while time.monotonic() < deadline:
                if not [r for r in members() if not r['state'].startswith('Z')]: break
                time.sleep(.02)
        report['remaining'] = [r for r in members() if not r['state'].startswith('Z')]
        report['complete'] = not report['remaining']
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
    report['observed'] = list(seen.values())
    # Reap only after all signals; unreaped child reserves PID/PGID identity.
    try: report['worker_exit'] = proc.wait(timeout=2)
    except subprocess.TimeoutExpired: report['complete'] = False
    return report

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--timeout', type=float, default=10)
    ap.add_argument('--outer-timeout', type=float, default=15)
    ap.add_argument('--fixture-short-outer', action='store_true')
    ap.add_argument('--module', action='append', default=[])
    ap.add_argument('--env', action='append', default=[])
    ap.add_argument('command', nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run_id): ap.error('invalid run-id')
    if not command: ap.error('command required')
    if not all(math.isfinite(v) and v > 0 for v in (args.timeout, args.outer_timeout)): ap.error('timeouts must be finite and positive')
    if not args.fixture_short_outer and args.outer_timeout <= args.timeout + 2: ap.error('outer timeout must exceed inner by >2s')
    try:
        mods = {}
        for item in args.module:
            key, value = item.split('=', 1)
            if not key or key in mods: raise ValueError('duplicate or empty module role')
            path = Path(value).resolve(strict=True)
            mods[key] = dict(path=str(path), sha256=digest(path))
        overrides = {}
        for item in args.env:
            key, value = item.split('=', 1)
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key): raise ValueError('invalid environment key')
            if key in ('HOME', 'TMPDIR', 'WINEPREFIX'): raise ValueError('session directory environment is reserved')
            overrides[key] = value
    except (ValueError, OSError) as exc: ap.error(str(exc))
    LOGS.mkdir(parents=True, exist_ok=True)
    root = LOGS/args.run_id
    try: root.mkdir()
    except FileExistsError: ap.error('run directory already exists; refusing overwrite')
    for name in ('prefix', 'work', 'home', 'tmp'): (root/name).mkdir()
    env = dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin', LANG='C', HOME=str(root/'home'),
               TMPDIR=str(root/'tmp'), WINEPREFIX=str(root/'prefix'), **overrides)
    cfg = dict(command=command, timeout=args.timeout, outer_timeout=args.outer_timeout,
               fixture_short_outer=args.fixture_short_outer, environment=env, modules=mods,
               prefix=str(root/'prefix'), cwd=str(root/'work'))
    save(root/'config.json', cfg)
    receipt = dict(schema=1, run_id=args.run_id, config=cfg, modules=mods, target_exit=None,
                   target_exit_observed=False, runner_exit=70, inner_timed_out=False, outer_timed_out=False,
                   error=None, owned=None, cleanup=None)
    caught = []
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, lambda signum, frame: caught.append(signum))
    proc = None
    started = time.monotonic()
    try:
        proc = subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve()), '--worker', str(root)],
                                start_new_session=True, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=(root/'worker-stderr.log').open('xb'))
        owner = next(r for r in snapshot() if r['pid'] == proc.pid)
        if owner['pgid'] != proc.pid: raise RuntimeError('worker session not isolated')
        receipt['owned'] = owner
        save(root/'owned.json', owner)
        event(root, 'parent', 'owned_registered', **owner)
        while not (root/'ready.json').exists():
            if time.monotonic()-started >= args.outer_timeout: raise TimeoutError('worker handshake timeout')
            if caught: raise InterruptedError('interrupted before handshake')
            time.sleep(.01)
        ready = json.loads((root/'ready.json').read_text())
        if ready != dict(pid=owner['pid'], pgid=owner['pgid']): raise RuntimeError('handshake identity mismatch')
        proc.stdin.write(b'GO\n'); proc.stdin.flush(); proc.stdin.close()
        while True:
            if (root/'worker-result.json').exists():
                receipt.update(json.loads((root/'worker-result.json').read_text()))
                receipt['runner_exit'] = 70 if receipt['error'] else 124 if receipt['inner_timed_out'] else int(receipt['target_exit'] != 0)
                break
            current = next((r for r in snapshot() if r['pid'] == owner['pid']), None)
            if current is None or current['identity'] != owner['identity'] or current['state'].startswith('Z'):
                raise RuntimeError('worker exited before result')
            if caught:
                receipt['runner_exit'] = 128+caught[0]; receipt['interrupted_signal'] = caught[0]; break
            if time.monotonic()-started >= args.outer_timeout:
                receipt['outer_timed_out'] = True; receipt['runner_exit'] = 125; break
            time.sleep(.02)
    except Exception as exc:
        receipt['error'] = type(exc).__name__ + ': ' + str(exc)
        if isinstance(exc, TimeoutError): receipt['outer_timed_out'] = True; receipt['runner_exit'] = 125
        elif caught: receipt['runner_exit'] = 128+caught[0]
    finally:
        if proc is not None:
            if proc.stdin is not None and not proc.stdin.closed: proc.stdin.close()
            if receipt['owned'] is not None:
                receipt['cleanup'] = cleanup(root, receipt['owned'], proc)
                if not receipt['cleanup']['complete']: receipt['runner_exit'] = 70
            else:
                startup = dict(pre_exec_aborted=True, observed=[], signals=[], complete=False)
                try:
                    startup['worker_exit'] = proc.wait(timeout=4)
                    startup['complete'] = True
                except subprocess.TimeoutExpired:
                    startup['error'] = 'worker did not self-retire before exec'
                receipt['cleanup'] = startup
        receipt['elapsed_seconds'] = time.monotonic()-started
        receipt['artifacts'] = {p.name: digest(p) for p in root.iterdir() if p.is_file() and p.name != 'receipt.json'}
        save(root/'receipt.json', receipt)
    print(str(root/'receipt.json'))
    return receipt['runner_exit']

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker': sys.exit(worker(Path(sys.argv[2])))
    sys.exit(main())
