"""P0 bootstrap launcher: ensures P0 runs in main thread of dedicated process."""
import hashlib
import importlib.util
from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[3]
P0 = LAB / 'scripts/runtime/session_v2/run.py'
P0_SHA = '3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b'

def main():
    if hashlib.sha256(P0.read_bytes()).hexdigest() != P0_SHA:
        raise SystemExit('P0 SHA mismatch')
    spec = importlib.util.spec_from_file_location('p0', P0)
    p0 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(p0)
    p0.LOGS = LAB / 'logs/session-v2-round2'
    sys.argv = [str(P0)] + sys.argv[1:]
    return p0.main()

if __name__ == '__main__':
    sys.exit(main())
