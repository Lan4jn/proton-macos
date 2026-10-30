"""Default is plan-only. --execute is required for a Wine/Proton subprocess."""
import argparse
import json
from pathlib import Path
from scripts.backend.bundle import build_plan, prepare_tool
from scripts.backend.process import LAB, run_isolated


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', type=Path, default=LAB / 'artifacts/public-proton/bundle.json')
    p.add_argument('--sysroot', type=Path, default=LAB / 'fixtures/runtime/sysroot')
    p.add_argument('--prefix', type=Path, default=LAB / 'fixtures/runtime/backend-compat/pfx')
    p.add_argument('--runtime-bundle', type=Path)
    p.add_argument('--linux-python', type=Path)
    p.add_argument('--elfuse', type=Path, help='Explicit path to elfuse binary (default: sources/elfuse/build/elfuse)')
    p.add_argument('--absock-base', type=Path, default=None, help='Explicit lab-isolated absock relay base directory (requires socket-derived runtime)')
    p.add_argument('--engine', choices=['proton', 'wine'], default='proton')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--timeout', type=float, default=100)
    p.add_argument('--prepare', type=Path)
    p.add_argument('--target', type=Path)
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    a = p.parse_args()
    if a.prepare:
        if not a.target:
            p.error('--prepare requires an explicit --target; installation is never performed')
        print(json.dumps(prepare_tool(a.prepare, a.target), indent=2))
        return 0
    args = a.arguments[1:] if a.arguments[:1] == ['--'] else a.arguments
    plan = build_plan(
        a.manifest,
        a.sysroot,
        a.prefix,
        args,
        a.engine,
        a.linux_python,
        a.runtime_bundle,
        elfuse_path=a.elfuse,
        absock_base=a.absock_base,
    )
    if plan['status'] != 'PLAN_READY':
        print(json.dumps(plan, indent=2))
        return 20
    if not a.execute:
        print(json.dumps(plan, indent=2))
        return 0
    a.prefix.mkdir(parents=True, exist_ok=True)
    result = run_isolated(plan['argv'], LAB / 'logs/backend', a.timeout, plan['env'])
    result['provenance'] = plan['provenance']
    result['engine'] = a.engine
    result['runtime_descriptor'] = plan.get('runtime_descriptor')
    print(json.dumps(result, indent=2))
    if result['timed_out']:
        return 124
    return result['exit'] if result['exit'] >= 0 else 128 - result['exit']


if __name__ == '__main__':
    raise SystemExit(main())
