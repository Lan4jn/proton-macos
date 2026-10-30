"""Fake runtime: emits diagnostic, then stand-in guest phases, then tail bytes."""
import os
from pathlib import Path
import runpy
import sys

print('runtime diagnostic', flush=True)
standin = Path(__file__).with_name('standin.py')
sys.argv = [str(standin), sys.argv[1], sys.argv[2]]

parent_pid = os.getpid()
orig_exit = os._exit

def custom_exit(code):
    if os.getpid() == parent_pid:
        sys.stdout.flush()
        os.write(1, b'tail diagnostic\xff')
    orig_exit(code)

os._exit = custom_exit
runpy.run_path(str(standin), run_name='__main__')
