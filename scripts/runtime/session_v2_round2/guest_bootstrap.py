"""P0 bootstrap for guest observer: whitelisted runtimes, probe ELF, and root manifest."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

LAB = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
P0 = LAB / 'scripts/runtime/session_v2/run.py'
P0_SHA = '3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b'

RUNTIMES = {
    'original': {
        'path': LAB / 'sources/elfuse-once-panorama2-derived/build/elfuse',
        'sha256': '8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda',
    },
    'derived': {
        'path': LAB / 'sources/elfuse-inproc-present-derived/build/elfuse',
        'sha256': '3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926',
    },
}

PROBE_ELF = {
    'path': LAB / 'sources/p0-session-round2/session_probe',
    'sha256': 'f2446b87c79d66a283d808d3d68f90621ec9cb0601e97198988721d1ab15fa1b',
}

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def make_root_manifest(root):
    manifest = {}
    for p in root.rglob('*'):
        if p.is_file():
            manifest[str(p.relative_to(root))] = sha256_file(p)
        elif p.is_dir():
            manifest[str(p.relative_to(root))] = 'directory'
    return manifest

def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('--fake', '--fake-outer', '--real-original', '--real-derived'):
        raise SystemExit('Usage: guest_bootstrap.py <--fake|--fake-outer|--real-original|--real-derived> <run-id>')
    mode, run_id = sys.argv[1:]

    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise SystemExit(f'Invalid run-id: {run_id}')

    if sha256_file(P0) != P0_SHA:
        raise SystemExit('P0 SHA mismatch')

    spec = importlib.util.spec_from_file_location('p0', P0)
    p0 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(p0)
    p0.LOGS = LAB / 'logs/session-v2-round2'

    observer = HERE / 'guest_observer.py'

    if mode in ('--fake', '--fake-outer'):
        root = LAB / 'sources/p0-session-round2' / ('guest-fake-' + run_id)
        assert root.resolve().parent == (LAB / 'sources/p0-session-round2').resolve(), 'root escape'
        (root / 'tmp').mkdir(parents=True, exist_ok=False)
        manifest = make_root_manifest(root)
        (root / 'root_manifest.json').write_text(json.dumps(manifest, indent=2))

        fake = HERE / 'fake_runtime.py'
        args = [
            '--run-id', run_id,
            '--timeout', '20',
            '--outer-timeout', '30',
            '--module', 'runtime=' + str(fake),
            '--module', 'observer=' + str(observer),
            '--',
            sys.executable, '-I', str(observer),
            '--root', str(root),
            '--runtime', str(fake),
            '--fake',
        ]
        if mode == '--fake-outer':
            args[args.index('30')] = '3'
            args.insert(0, '--fixture-short-outer')
            args.append('--stall')
    else:
        # Real runtime execution: gated by strict guest lock check
        lock_token = os.environ.get('GUEST_LOCK_TOKEN')
        if not lock_token:
            raise RuntimeError('guest execution locked; requires GUEST_LOCK_TOKEN')

        role = 'original' if mode == '--real-original' else 'derived'
        rt_info = RUNTIMES[role]
        if sha256_file(rt_info['path']) != rt_info['sha256']:
            raise RuntimeError(f'runtime {role} SHA mismatch')
        if sha256_file(PROBE_ELF['path']) != PROBE_ELF['sha256']:
            raise RuntimeError('probe ELF SHA mismatch')

        root = LAB / 'sources/p0-session-round2' / ('guest-fixture-' + run_id)
        assert root.resolve().parent == (LAB / 'sources/p0-session-round2').resolve(), 'root escape'
        root.mkdir(parents=True, exist_ok=False)
        (root / 'bin').mkdir(parents=True, exist_ok=False)
        (root / 'tmp').mkdir(parents=True, exist_ok=False)
        installed_probe = root / 'bin/probe'
        shutil.copyfile(PROBE_ELF['path'], installed_probe)
        installed_probe.chmod(0o755)

        manifest = make_root_manifest(root)
        (root / 'root_manifest.json').write_text(json.dumps(manifest, indent=2))

        args = [
            '--run-id', run_id,
            '--timeout', '20',
            '--outer-timeout', '30',
            '--module', 'runtime=' + str(rt_info['path']),
            '--module', 'probe=' + str(installed_probe),
            '--module', 'observer=' + str(observer),
            '--',
            sys.executable, '-I', str(observer),
            '--root', str(root),
            '--runtime', str(rt_info['path']),
        ]

    sys.argv = [str(P0)] + args
    return p0.main()

if __name__ == '__main__':
    sys.exit(main())
