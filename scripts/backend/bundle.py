"""Explicit package provenance, execution plans, and offline Steam preparation."""
import hashlib
import json
import os
import shlex
import stat
import struct
import sys
from pathlib import Path
from scripts.backend.process import LAB

CPU_TYPE_ARM64 = 0x0100000c
MH_EXECUTE = 2

KNOWN_ELFUSE_BASELINES = {
    'dd5dae9ebe3c993ee16320f100d0ad552e5bdd60f31c3c5a9b325fdfd80a72e7': {
        'flavor': 'original',
        'source_baseline': 'ORIGINAL_UPSTREAM_CLEAN',
        'commit': '8612033dab8dc60728f604a4ea0441895fc16d39',
        'patches': [],
        'description': 'Original upstream pinned elfuse (clean commit 8612033dab8dc60728f604a4ea0441895fc16d39)',
    },
    '0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7': {
        'flavor': 'derived',
        'source_baseline': 'FEX_LAYOUT_ONLY_DERIVED',
        'commit': '8612033dab8dc60728f604a4ea0441895fc16d39',
        'patches': ['layout_shift', 'futex_wait_wake'],
        'description': 'Derived elfuse with layout-only shift and futex patch',
    },
    'ff3904318354d6dc4b8e17482fd83cd512b3156227d296e0c0e7c97ff6dcb21f': {
        'flavor': 'derived',
        'source_baseline': 'FUTEX_PATCHED_DERIVED',
        'commit': '8612033dab8dc60728f604a4ea0441895fc16d39',
        'patches': ['futex_wait_wake'],
        'description': 'Derived elfuse with shared futex patch',
    },
    '06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d': {
        'flavor': 'derived',
        'source_baseline': 'ABSOCK_CUSTOM_BASE_DERIVED',
        'commit': '8612033dab8dc60728f604a4ea0441895fc16d39',
        'patches': ['layout_shift', 'futex_wait_wake', 'preempt_lifecycle_stop_join', 'absock_custom_base'],
        'description': 'Derived elfuse with lifecycle stop/join and explicit lab-only absock base relay',
        'capabilities': {'supports_absock_base': True},
    },
}


def local(path):
    p = Path(path).resolve()
    if not p.is_relative_to(LAB):
        raise ValueError('Expected a lab-local path')
    return p


def validate_absock_base(base_path) -> str:
    """Validate that absock_base conforms to elfuse and lab security policy:
    1. Base must be inside LAB.
    2. Checked before resolving symlinks to reject leaf symlinks (including trailing slashes).
    3. Path must exist, be a directory, owned by current UID, mode 0700 (user-only).
    4. Length limits: UTF-8 encoded length must be non-empty, < 60 bytes, and base + 18 <= 72.
    Returns the canonical absolute path as string.
    """
    if not base_path:
        raise ValueError('absock_base cannot be empty')

    # Convert to string and strip trailing slash to check raw leaf link first
    raw_str = os.fspath(base_path)
    if not raw_str or raw_str.strip() == '' or raw_str == '.':
        raise ValueError('absock_base cannot be empty or dot')

    clean_raw = raw_str.rstrip('/')
    if not clean_raw:
        clean_raw = '/'

    raw_p = Path(clean_raw)
    # Strictly reject relative paths: must be an explicit absolute path
    if not raw_p.is_absolute():
        raise ValueError(f'absock_base must be an absolute path (got relative: {raw_str})')

    # Check symlink before resolve() so symlinks are not masked
    try:
        raw_st = os.lstat(raw_p)
    except OSError as e:
        raise ValueError(f'absock_base directory lookup failed: {e}')

    if stat.S_ISLNK(raw_st.st_mode):
        raise ValueError(f'absock_base cannot be a symlink: {raw_str}')

    resolved_p = raw_p.resolve()
    if not resolved_p.is_relative_to(LAB):
        raise ValueError(f'absock_base must remain inside lab: {resolved_p}')

    if not resolved_p.is_dir():
        raise ValueError(f'absock_base must be a directory: {resolved_p}')

    st = resolved_p.stat()
    if st.st_uid != os.getuid():
        raise ValueError(f'absock_base must be owned by current user ({os.getuid()}): {resolved_p}')

    # Check strict 0700 (no group or other permissions, owner has rwx)
    mode_bits = stat.S_IMODE(st.st_mode)
    if mode_bits != 0o700:
        raise ValueError(f'absock_base mode must be strictly 0700 (got {oct(mode_bits)}): {resolved_p}')

    canonical_str = str(resolved_p)
    encoded = os.fsencode(canonical_str)
    raw_len = len(encoded)

    if raw_len == 0 or raw_len >= 60:
        raise ValueError(f'absock_base byte length must be < 60 bytes (got {raw_len}): {canonical_str}')

    # C format is snprintf(out, out_sz, "%s/n%016llx", clean_base, namespace_id); budget <= 72
    if raw_len + 18 > 72:
        raise ValueError(f'absock_base formatted length exceeds 72 bytes budget ({raw_len + 18} > 72): {canonical_str}')

    return canonical_str


def get_elfuse_descriptor(elfuse_path=None):
    if elfuse_path is None:
        p = local(LAB / 'sources/elfuse/build/elfuse')
    else:
        p = local(elfuse_path)

    if not p.is_file():
        raise ValueError(f'elfuse binary missing: {p}')
    if not os.access(str(p), os.X_OK):
        raise ValueError(f'elfuse binary is not executable: {p}')

    raw = p.read_bytes()
    file_size = len(raw)
    if file_size < 32:
        raise ValueError(f'Mach-O file too short (< 32 bytes): {p}')

    magic_bytes = raw[:4]
    if magic_bytes in (b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'):
        raise ValueError(f'FAT universal binary is not supported; arm64 thin Mach-O required: {p}')

    try:
        magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack('<IIIIIIII', raw[:32])
    except struct.error:
        raise ValueError(f'Failed to unpack Mach-O 64-bit header: {p}')

    if magic != 0xfeedfacf:
        raise ValueError(f'Invalid Mach-O 64-bit magic {hex(magic)}: {p}')
    if cputype != CPU_TYPE_ARM64:
        raise ValueError(f'Invalid cputype {hex(cputype)}: expected ARM64 (0x0100000c) for elfuse: {p}')
    if filetype != MH_EXECUTE:
        raise ValueError(f'Invalid filetype {filetype}: expected MH_EXECUTE (2) for elfuse: {p}')
    if ncmds < 1 or sizeofcmds < 1 or file_size < 32 + sizeofcmds:
        raise ValueError(f'Mach-O load commands bounds violation (ncmds={ncmds}, sizeofcmds={sizeofcmds}, size={file_size}): {p}')

    sha256 = hashlib.sha256(raw).hexdigest()

    # Determine baseline strictly from cryptographically verified SHA-256
    known = KNOWN_ELFUSE_BASELINES.get(sha256)
    if known:
        flavor = known['flavor']
        source_baseline = known['source_baseline']
        commit = known['commit']
        patches = known['patches']
        desc = known['description']
    else:
        flavor = 'derived'
        source_baseline = 'CUSTOM_UNVERIFIED_DERIVED'
        commit = 'UNKNOWN'
        patches = ['unknown']
        desc = 'Unverified or custom lab-derived elfuse binary'

    capabilities = dict(known.get('capabilities', {})) if known else {}

    return {
        'path': str(p),
        'sha256': sha256,
        'flavor': flavor,
        'source_baseline': source_baseline,
        'commit': commit,
        'patches': patches,
        'description': desc,
        'capabilities': capabilities,
        'execution_evidence': 'NOT_CHECKED',
    }


def verify_bundle(manifest_path, runtime_bundle=None):
    manifest = local(manifest_path)
    data = json.loads(manifest.read_text())
    root = local(runtime_bundle or data['bundle'])
    required = [
        'files/bin-arm64/wine',
        'files/bin-arm64/wineserver',
        'files/lib/wine/aarch64-unix/ntdll.so',
        'files/lib/wine/aarch64-unix/libarm64ecfex.so',
    ]
    for name in required:
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Missing or escaped critical file: ' + name)
        expected = data.get('critical_files', {}).get(name)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if not expected or actual != expected:
            raise ValueError('Digest mismatch: ' + name)
        if path.read_bytes()[:4] != b'\x7fELF':
            raise ValueError('Expected Linux ELF: ' + name)
    data = dict(data, status='CHECKSUM_VERIFIED', runtime_bundle=str(root))
    return data


def build_plan(manifest, sysroot, prefix, arguments, engine='proton', linux_python=None, runtime_bundle=None, elfuse_path=None, absock_base=None):
    prefix = local(prefix)
    root = local(sysroot)
    if engine not in ('wine', 'proton'):
        raise ValueError('Unknown engine')
    try:
        info = verify_bundle(manifest, runtime_bundle)
    except (OSError, ValueError, KeyError) as e:
        return {'status': 'BLOCKED', 'reason': str(e), 'execution_performed': False}
    try:
        descriptor = get_elfuse_descriptor(elfuse_path)
    except (OSError, ValueError) as e:
        return {'status': 'BLOCKED', 'reason': str(e), 'execution_performed': False}

    # Hash-based capability gating for absock_base:
    # If absock_base is explicitly specified, descriptor MUST have capability supports_absock_base
    validated_absock_base = None
    if absock_base is not None:
        if not descriptor.get('capabilities', {}).get('supports_absock_base'):
            return {
                'status': 'BLOCKED',
                'reason': f"Runtime {descriptor.get('source_baseline')} does not have supports_absock_base capability; explicit absock_base requires socket-derived elfuse (06a2fceb...)",
                'execution_performed': False,
            }
        try:
            validated_absock_base = validate_absock_base(absock_base)
        except (ValueError, OSError) as e:
            return {'status': 'BLOCKED', 'reason': f'Invalid absock_base: {e}', 'execution_performed': False}

    elfuse = Path(descriptor['path'])
    bundle = Path(info['runtime_bundle'])
    if not (root / 'lib/ld-linux-aarch64.so.1').is_file():
        return {'status': 'BLOCKED', 'reason': 'Linux interpreter missing', 'execution_performed': False}
    argv = [str(elfuse), '--user', f'{os.getuid()}:{os.getgid()}', '--sysroot', str(root), '--timeout', '90']
    env = {
        'WINEPREFIX': str(prefix),
        'WINEESYNC': '0',
        'WINEFSYNC': '0',
        'WINEDEBUG': '-all',
        'PROTON_NO_ESYNC': '1',
        'PROTON_NO_FSYNC': '1',
        'PROTON_NO_NTSYNC': '1',
        'WINESERVER': str(bundle / 'files/bin-arm64/wineserver'),
        'WINELOADER': str(bundle / 'files/bin-arm64/wine'),
    }
    if validated_absock_base:
        env['ELFUSE_ABSOCK_BASE'] = validated_absock_base

    warnings = [
        'Publisher checksums verified; Valve signature was not independently verified.',
        'A command plan is not evidence of successful Windows execution.',
    ]
    if descriptor['flavor'] == 'derived':
        warnings.append(f"Using derived elfuse runtime ({descriptor['source_baseline']}); verify against independent run logs.")
    if validated_absock_base:
        warnings.append(f"Using explicit lab-isolated absock base ({validated_absock_base}); host /tmp relay bypassed.")

    if engine == 'wine':
        argv += [str(bundle / 'files/bin-arm64/wine')] + list(arguments)
        warnings.append('Direct Wine component diagnostic, not the full Proton Python launcher.')
        if not (bundle / 'files/bin/wineserver').exists():
            warnings.append('Compiled Wine server search path has no files/bin/wineserver; use a separately documented derived layout.')
    else:
        if not linux_python:
            return {
                'status': 'BLOCKED',
                'reason': 'Full Proton requires a Linux ARM64 Python interpreter and its Linux dependencies; host macOS Python is not substituted.',
                'execution_performed': False,
            }
        python = local(linux_python)
        if not python.is_file() or python.read_bytes()[:4] != b'\x7fELF':
            return {'status': 'BLOCKED', 'reason': 'Linux Python ELF missing', 'execution_performed': False}
        if not (bundle / 'proton').is_file():
            return {'status': 'BLOCKED', 'reason': 'Proton launcher missing', 'execution_performed': False}
        argv += [str(python), str(bundle / 'proton')] + list(arguments)
        env.update({
            'STEAM_COMPAT_DATA_PATH': str(prefix.parent),
            'STEAM_COMPAT_CLIENT_INSTALL_PATH': str(LAB / 'fixtures/runtime/steam-stub'),
        })
        warnings.append('No native macOS Steamworks bridge is provided by this launcher.')
    return {
        'status': 'PLAN_READY',
        'argv': argv,
        'env': env,
        'engine': engine,
        'warnings': warnings,
        'provenance': info.get('provenance'),
        'runtime_descriptor': descriptor,
        'absock_base': validated_absock_base,
        'execution_performed': False,
    }


def prepare_tool(output, target):
    out = local(output)
    out.mkdir(parents=True, exist_ok=False)
    target = Path(target).absolute()
    wrapper = out / 'probe-wrapper.sh'
    probe_logs = out / 'probe-logs'
    probe_logs.mkdir(mode=0o700)
    command = ' '.join(shlex.quote(str(x)) for x in [sys.executable, LAB / 'scripts/steam/probe.py', '--log-dir', probe_logs])
    wrapper_content = '#!/bin/sh\nif [ "$1" = "--" ]; then\n  shift\nfi\nexec ' + command + ' -- "$@"\n'
    wrapper.write_text(wrapper_content)
    wrapper.chmod(0o700)
    encoded = str(wrapper).replace('\\', '\\\\').replace('"', '\\"')
    (out / 'toolmanifest.vdf').write_text('"manifest"\n{\n "version" "2"\n "commandline" "\\"' + encoded + '\\" -- %verb%"\n}\n')
    (out / 'compatibilitytool.vdf').write_text('"compatibilitytools"\n{\n "compat_tools"\n {\n  "proton-macos-lab-probe"\n  {\n   "install_path" "."\n   "display_name" "Proton macOS Lab (probe only)"\n   "from_oslist" "windows"\n   "to_oslist" "macos"\n  }\n }\n}\n')
    result = {
        'candidate': str(out),
        'target': str(target / 'proton-macos-lab-probe'),
        'applied': False,
        'purpose': 'Steam discovery probe only; does not execute a game.',
        'backup': 'Before any future install, preserve an existing target directory under a unique backup name.',
        'rollback': 'Remove only the installed probe directory after identity verification, then restore the backup. No such operation has run.',
    }
    (out / 'install-plan.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
