"""Approved one-round original matrix and derived fork-private supplement.

Each invocation uses new roots/run IDs. Not a default regression entry point:
coordinate the runtime execution lock and reapproval before another invocation.
"""
from pathlib import Path
import hashlib
import json
import shutil
import struct
import subprocess
import time
import uuid

LAB = Path(__file__).resolve().parents[2]

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    stamp = time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6]
    out = LAB / 'logs/r1-cow-matrix-v2' / ('review-guest-' + stamp)
    out.mkdir()
    elf = LAB / 'sources/r1-cow-matrix-v2/probe-linux-aarch64'
    runner = LAB / 'scripts/runtime/session_v2/run.py'
    b = elf.read_bytes()
    assert sha(elf) == '93dc86f9bb2bf568c1c140c883bf738ab4359cd97610a12485ac7c7b7f95046b'
    phoff = struct.unpack_from('<Q', b, 32)[0]
    size, count = struct.unpack_from('<HH', b, 54)
    types = [struct.unpack_from('<I', b, phoff+i*size)[0] for i in range(count)]
    assert 2 not in types and 3 not in types
    groups = [
        ('original', 'sources/elfuse-once-panorama2-derived/build/elfuse', '8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda', 'shared private lanes fixed protect thread fork-private fork-shared remap'.split()),
        ('derived-supplement', 'sources/elfuse-inproc-present-derived/build/elfuse', '3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926', ['fork-private']),
    ]
    summary = dict(elf_sha256=sha(elf), runner_sha256=sha(runner), gate_present=False,
                   budgets=dict(runtime=5, supervisor=20, outer=30), PT_INTERP=False, PT_DYNAMIC=False,
                   fork_protocol='pipe child readback then _exit; no setsid/exec', cases=[])
    for role, runtime_path, expected_hash, cases in groups:
        rt = LAB / runtime_path
        assert sha(rt) == expected_hash
        stop = False
        for case in cases:
            row = dict(role=role, case=case, runtime_sha256=expected_hash)
            summary['cases'].append(row)
            if stop:
                row.update(status='NOT_RUN', reason='COMMON_RUNTIME_FAILURE')
                continue
            root = LAB / 'sources/r1-cow-matrix-v2/guest-fixtures' / stamp / role / case / 'root'
            (root/'bin').mkdir(parents=True); (root/'tmp').mkdir()
            probe = root/'bin/probe'
            shutil.copyfile(elf, probe); probe.chmod(0o755)
            assert probe.is_relative_to(root)
            runid = 'r1-' + stamp + '-' + role + '-' + case
            argv = ['python3', '-I', str(runner), '--run-id', runid, '--timeout', '20', '--outer-timeout', '30',
                    '--module', 'runtime='+str(rt), '--module', 'probe='+str(probe), '--module', 'runner='+str(runner),
                    '--', str(rt), '--sysroot', str(root), '--timeout', '5', '--workdir', '/tmp', '--clear-env', str(probe), case, '4096']
            p = subprocess.run(argv, capture_output=True, timeout=40)
            (out/(role+'-'+case+'.stdout')).write_bytes(p.stdout)
            (out/(role+'-'+case+'.stderr')).write_bytes(p.stderr)
            rp = LAB / 'logs/session-v2' / runid / 'receipt.json'
            receipt = json.loads(rp.read_text())
            raw = (rp.parent/'stdout.log').read_text(errors='replace')
            try: obs = json.loads(raw)
            except ValueError: obs = None
            row.update(command=argv, runner_exit=p.returncode, session_receipt=str(rp.relative_to(LAB)),
                session_receipt_sha256=sha(rp), fixture=str(root.relative_to(LAB)), fixture_probe_sha256=sha(probe),
                target_exit=receipt['target_exit'], inner_timed_out=receipt['inner_timed_out'],
                outer_timed_out=receipt['outer_timed_out'], observation=obs, cleanup=receipt['cleanup'])
            stop = (obs is None or receipt['target_exit'] not in [0, 1, 2, 77] or receipt['inner_timed_out'] or
                    receipt['outer_timed_out'] or not receipt['cleanup']['complete'])
            (out/'receipt.json').write_text(json.dumps(summary, indent=2)+'\n')
            print(role, case, receipt['target_exit'], obs, flush=True)
    (out/'receipt.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(out.relative_to(LAB))

if __name__ == '__main__': main()
