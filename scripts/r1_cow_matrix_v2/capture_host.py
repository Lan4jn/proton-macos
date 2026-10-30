"""Host-only evidence capture. Guest execution deliberately has no entry point."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
CASES = 'shared private lanes fixed protect thread fork-private fork-shared remap'.split()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    run = ROOT / 'logs/r1-cow-matrix-v2' / (time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'sources/r1-cow-matrix-v2/probe.c'
    binary = ROOT / 'sources/r1-cow-matrix-v2/probe-host'
    env = dict(os.environ)
    env.pop('ELFUSE_DIAG_SESSION_SHARED', None)
    records = []
    for lane in sorted({4096, os.sysconf('SC_PAGE_SIZE')}):
        for case in CASES:
            cmd = [str(binary), case, str(lane)]
            prefix = run / f'{case}-{lane}'
            start = time.monotonic()
            try:
                p = subprocess.run(cmd, cwd=run, env=env, capture_output=True, timeout=8)
                out, err, code, timeout = p.stdout, p.stderr, p.returncode, False
            except subprocess.TimeoutExpired as e:
                out, err, code, timeout = e.stdout or b'', e.stderr or b'', None, True
            prefix.with_suffix('.stdout').write_bytes(out)
            prefix.with_suffix('.stderr').write_bytes(err)
            try: observation = json.loads(out)
            except (ValueError, UnicodeError): observation = None
            records.append(dict(command=cmd, cwd=str(run), case=case, lane=lane, timeout_seconds=8,
                target_exit=code, timed_out=timeout, elapsed_seconds=time.monotonic()-start,
                observation=observation, stdout=str(prefix.with_suffix('.stdout').relative_to(ROOT)),
                stderr=str(prefix.with_suffix('.stderr').relative_to(ROOT)),
                stdout_sha256=hashlib.sha256(out).hexdigest(), stderr_sha256=hashlib.sha256(err).hexdigest()))
    receipt = dict(schema=1, kind='HOST_POSIX_ONLY', gate_present=False, guest=dict(status='NOT_RUN', reason='P0_REVIEW_PENDING'),
        source_sha256=sha(source), binary_sha256=sha(binary), host_page_size=os.sysconf('SC_PAGE_SIZE'), cases=records,
        writecopy='MAP_PRIVATE mechanism proxy only')
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(run.relative_to(ROOT))
    return 1 if any(r['timed_out'] or r['target_exit'] not in (0,77) for r in records) else 0

if __name__ == '__main__': raise SystemExit(main())
