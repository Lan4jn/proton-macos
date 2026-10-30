import hashlib
import json
from pathlib import Path
import shlex
import struct
import sys

LAB = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(LAB))
from scripts.backend.process import run_isolated
from scripts.backend.bundle import validate_absock_base

FIX = LAB / 'fixtures/runtime/arm64-vulkan-probe'
LOG = LAB / 'logs/arm64-vulkan-probe'

def classify(result, stdout):
    if result.get('timed_out'):
        return 'TIMEOUT'
    if result.get('cleanup_errors'):
        return 'CLEANUP_FAILED'
    if result.get('exit') != 0 or result.get('target_exit') != 0:
        return 'TARGET_FAILED'
    markers = ['[WIN_ARM64_VK] SUCCESS: VkInstance created at ', '[WIN_ARM64_VK] SUCCESS: Verified CPU lavapipe/llvmpipe device.', '[WIN_ARM64_VK] FINAL_STATUS: WIN_ARM64_VULKAN_OK']
    return 'ARM64_WINDOWS_VULKAN_CPU_ENUM_PASSED' if all(x in stdout for x in markers) else 'INCOMPLETE'

def main():
    record = LOG / 'execution.json'
    if record.exists():
        raise RuntimeError('Existing run ledger; implicit reruns prohibited')
    prior = json.loads((LAB/'logs/arm64-loader-probe/stage_results.json').read_text())
    if len(prior['stages']) != 3 or any(s['verdict'] != 'STAGE_PASSED' for s in prior['stages']):
        raise RuntimeError('Native stage gate not passed')
    relay = validate_absock_base(str(LAB/'.s'))
    runtime = LAB/'sources/elfuse-socket-derived/build/elfuse'
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if digest(runtime) != prior['runtime_sha256']:
        raise RuntimeError('Runtime mismatch')
    icd = LAB/'fixtures/runtime/lavapipe-derived/usr/share/vulkan/icd.d/lvp_icd.json'
    if digest(icd) != '2dc30fc23e5114a7dfaa43a68c5d8bde77dc3173e9bf0bc9d74e48a4117f2231':
        raise RuntimeError('ICD mismatch')
    exe = FIX/'vk_enum_arm64.exe'
    raw = exe.read_bytes(); pe = struct.unpack_from('<I', raw, 0x3c)[0]
    if raw[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', raw, pe+4)[0] != 0xaa64:
        raise RuntimeError('Expected native ARM64 PE')
    target = FIX/'pfx/drive_c/vk_enum_arm64.exe'
    if target.exists():
        raise RuntimeError('Target already exists')
    target.write_bytes(raw)
    for name, item in prior['dlls'].items():
        dll = FIX/'pfx/drive_c/windows/system32'/(name+'.dll')
        if not dll.is_file() or digest(dll) != item['sha256']:
            raise RuntimeError('Prefix DLL mismatch: '+name)
    env = dict(prior['guest_env'])
    env['WINEPREFIX'] = str(FIX/'pfx')
    env['WINEDEBUG'] = '+timestamp,+loaddll,+process,+vulkan,+seh'
    env['VK_ICD_FILENAMES'] = str(icd)
    bundle = LAB/'fixtures/runtime/proton-derived'
    root = LAB/'fixtures/runtime/arch-case'
    script = 'unset LD_PRELOAD DISPLAY XAUTHORITY WINEDLLOVERRIDES; export LD_LIBRARY_PATH=%s; exec %s %s' % (shlex.quote(prior['ld_library_path']), shlex.quote(str(bundle/'files/bin-arm64/wine')), shlex.quote('C:\\vk_enum_arm64.exe'))
    argv = [str(runtime), '--user', '501:20', '--sysroot', str(root), '--timeout', '60']
    import os
    argv[2] = '%d:%d' % (os.getuid(), os.getgid())
    for key,value in env.items(): argv += ['--env', key+'='+value]
    argv += [str(root/'usr/bin/sh'), '-c', script]
    receipt = {'argv': argv, 'guest_env': env, 'runtime_sha256': digest(runtime), 'target_sha256': digest(exe), 'icd_sha256': digest(icd), 'native_env': {'ELFUSE_ABSOCK_BASE': relay}, 'status': 'STARTED'}
    record.write_text(json.dumps(receipt, indent=2)+'\n')
    result = run_isolated(argv, LOG, timeout=70, extra_env=receipt['native_env'])
    stdout = Path(result['stdout']).read_text(errors='replace')
    receipt.update(result=result, stdout=stdout, status=classify(result, stdout))
    record.write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({'status': receipt['status'], 'result':result, 'stdout': stdout}, indent=2))
    return 0 if receipt['status']=='ARM64_WINDOWS_VULKAN_CPU_ENUM_PASSED' else 1

if __name__ == '__main__': raise SystemExit(main())
