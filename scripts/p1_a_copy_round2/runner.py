#!/usr/bin/env python3
"""Round2 log-root adapter for frozen P0 parent/worker supervision."""
import hashlib
import importlib.util
import pathlib
import sys
sys.dont_write_bytecode=True

ROOT=pathlib.Path(__file__).resolve().parents[2]
P0=ROOT/'scripts/runtime/session_v2/run.py'
SHA='3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b'
if hashlib.sha256(P0.read_bytes()).hexdigest()!=SHA:
    raise SystemExit('frozen P0 SHA changed; re-review required')
spec=importlib.util.spec_from_file_location('p0_frozen',P0)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.LOGS=ROOT/'logs/p1-a-copy-round2'
if __name__=='__main__':sys.exit(module.main())
