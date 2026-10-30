#!/usr/bin/env python3
"""Host-only fork/barrier fixture; never runs guest or calls setsid."""
import os
import pathlib
import time

root = pathlib.Path(os.environ['FIXTURE_ROOT'])
pid = os.fork()
if pid == 0:
    for phase in ('pre', 'post'):
        (root / phase).write_text(os.environ['FIXTURE_TOKEN'])
        deadline = time.monotonic() + 5
        while not (root / (phase + '.ack')).exists():
            if time.monotonic() > deadline: os._exit(71)
            time.sleep(.01)
    os._exit(0)
_, status = os.waitpid(pid, 0)
os._exit(os.waitstatus_to_exitcode(status))
