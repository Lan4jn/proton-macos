#!/usr/bin/env python3
import json,shlex,subprocess,sys
from pathlib import Path
LAB=Path(__file__).resolve().parents[3]
source=LAB/'sources/wine-ro-section-adapt/wine'
build=LAB/'sources/wine-pin-adea/target_pristine_build'
entries=json.loads((build/'compile_commands.json').read_text())
cmd=shlex.split(next(e['command'] for e in entries if e['file'].endswith('/ntdll/unix/virtual.c')))
cmd=[x.replace(str(LAB/'sources/wine-pin-adea/pristine/wine-adea6cbac9d00bb22910145354d00c463fcf3afc'),str(source)) for x in cmd]
cmd.remove('-c');idx=cmd.index('-o');cmd[idx+1]=str(LAB/'sources/wine-ro-section-adapt'/sys.argv[1])
cmd=[str(LAB/'scripts/runtime/ro_section/production_unit.c') if x==str(source/'dlls/ntdll/unix/virtual.c') else x for x in cmd]
cmd+=['-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-O0']
print(shlex.join(cmd),flush=True)
r=subprocess.run(cmd,cwd=build)
sys.exit(r.returncode)
