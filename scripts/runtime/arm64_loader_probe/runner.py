import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import struct
import sys

LAB = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(LAB))
from scripts.backend.process import run_isolated

FIX = LAB / 'fixtures/runtime/arm64-loader-probe'
LOG = LAB / 'logs/arm64-loader-probe'
RUNTIME = LAB / 'sources/elfuse-socket-derived/build/elfuse'
ROOT = LAB / 'fixtures/runtime/arch-case'
BUNDLE = LAB / 'fixtures/runtime/proton-derived'
EXPECTED_RUNTIME = '06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d'
STAGES = [(37, 'ARM64_KERNEL32_OK', 35), (38, 'ARM64_DPI_RETURNED=', 60), (39, 'ARM64_VULKAN_LOAD_RETURNED', 60)]

def classify(result, stdout, expected_exit, marker):
    if result.get('timed_out'):
        return 'TIMEOUT'
    if result.get('cleanup_errors'):
        return 'CLEANUP_FAILED'
    if result.get('exit') != expected_exit or result.get('target_exit') != expected_exit:
        return 'TARGET_FAILED'
    return 'STAGE_PASSED' if marker in stdout else 'MARKER_MISSING'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    LOG.mkdir(parents=True, exist_ok=True)
    if (LOG / 'stage_results.json').exists():
        raise RuntimeError('Existing execution ledger: do not implicitly rerun')
    if sha(RUNTIME) != EXPECTED_RUNTIME:
        raise RuntimeError('Runtime hash mismatch')
    relay = LAB / '.s'
    st = relay.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise RuntimeError('Relay must already be an owned real 0700 directory')
    pfx = FIX / 'pfx'
    dlls = ['kernel32', 'kernelbase', 'ntdll', 'user32', 'ucrtbase', 'win32u', 'vulkan-1']
    dll_receipt = {}
    for name in dlls:
        path = pfx / 'drive_c/windows/system32' / (name + '.dll')
        if not path.is_file():
            raise RuntimeError('Invalid DLL: ' + str(path))
        dll_receipt[name] = {'resolved': str(path.resolve()), 'sha256': sha(path)}
    probes = []
    for mode in range(3):
        src = FIX / ('probe-%d.exe' % mode)
        raw = src.read_bytes()
        pe = struct.unpack_from('<I', raw, 0x3c)[0]
        if raw[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', raw, pe+4)[0] != 0xaa64:
            raise RuntimeError('Not native ARM64 PE')
        dst = pfx / 'drive_c' / src.name
        if dst.exists():
            raise RuntimeError('Probe target already exists: ' + str(dst))
        dst.write_bytes(raw)
        probes.append({'path': str(dst), 'sha256': sha(dst)})
    wine = BUNDLE / 'files/bin-arm64/wine'
    paths = [LAB/'fixtures/runtime/lavapipe-derived/usr/lib', BUNDLE/'files/lib/wine/aarch64-unix', BUNDLE/'files/lib', ROOT/'usr/lib']
    guest_env = {'WINEPREFIX': str(pfx), 'WINEESYNC': '0', 'WINEFSYNC': '0', 'PROTON_NO_ESYNC': '1', 'PROTON_NO_FSYNC': '1', 'PROTON_NO_NTSYNC': '1', 'PROTON_USE_ARM64': '1', 'WINESERVER': str(BUNDLE/'files/bin-arm64/wineserver'), 'WINELOADER': str(wine), 'WINEDEBUG': '+timestamp,+loaddll,+process,+seh'}
    ledger = {'runtime_sha256': sha(RUNTIME), 'probes': probes, 'dlls': dll_receipt, 'guest_env': guest_env, 'ld_library_path': ':'.join(map(str, paths)), 'native_env': {'ELFUSE_ABSOCK_BASE': str(relay)}, 'stages': []}
    ledger_path = LOG / 'stage_results.json'
    ledger_path.write_text(json.dumps(ledger, indent=2)+'\n')
    for mode, (exit_code, marker, timeout) in enumerate(STAGES):
        target = 'C:\\probe-%d.exe' % mode
        script = 'unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES; export LD_LIBRARY_PATH=%s; exec %s %s' % (shlex.quote(ledger['ld_library_path']), shlex.quote(str(wine)), shlex.quote(target))
        argv = [str(RUNTIME), '--user', '%d:%d' % (os.getuid(), os.getgid()), '--sysroot', str(ROOT), '--timeout', str(timeout)]
        for key, value in guest_env.items():
            argv += ['--env', key+'='+value]
        argv += [str(ROOT/'usr/bin/sh'), '-c', script]
        result = run_isolated(argv, LOG, timeout=timeout+10, extra_env=ledger['native_env'])
        stdout = Path(result['stdout']).read_text(errors='replace')
        verdict = classify(result, stdout, exit_code, marker)
        ledger['stages'].append({'mode': mode, 'verdict': verdict, 'result': result, 'stdout': stdout})
        ledger_path.write_text(json.dumps(ledger, indent=2)+'\n')
        print(json.dumps({'mode': mode, 'verdict': verdict, 'exit': result['exit'], 'target_exit': result.get('target_exit'), 'timed_out': result['timed_out'], 'run_dir': result['run_dir'], 'stdout': stdout}), flush=True)
        if verdict != 'STAGE_PASSED':
            ledger['not_run_modes'] = list(range(mode+1, 3))
            ledger_path.write_text(json.dumps(ledger, indent=2)+'\n')
            return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
