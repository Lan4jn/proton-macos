#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/backend/steam_handoff.py

Offline Steam-shaped runtime candidate handoff and execution bridge.
Generates Steam compatibility tool candidate files (wrapper, manifest, install-plan)
without modifying host Steam directories or user configuration.

Key guarantees:
1. Default plan-only: preparing a tool generates a candidate that defaults to plan-only
   inspection; requires explicit execute_runtime=True / --execute-runtime to enable subprocess runs.
2. Argument safety: shell wrapper preserves spaces, Unicode, percent signs, and leading dashes
   without shell metacharacter expansion ($USER, *.*, ;, etc.).
3. Environment isolation: fixed lab prefix and sysroot cannot be overridden by caller environment
   variables (WINEPREFIX, LD_PRELOAD, DYLD_*).
4. Steam verb gating: only recognized Steam verbs (run, runinprefix, waitforexitandrun) are accepted.
   Unknown verbs are rejected with clear stderr and non-zero exit code.
5. True Linux Python execution: passes true Linux ARM64 Python interpreter under elfuse to Proton;
   does not substitute host macOS Python for Proton script logic.
6. Target installation is never applied (applied=false).
"""

import argparse
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.bundle import build_plan, get_elfuse_descriptor, local
from scripts.backend.process import run_isolated

KNOWN_STEAM_VERBS = {"run", "runinprefix", "waitforexitandrun"}

DEFAULT_ELFUSE = LAB / "sources/elfuse-crash-derived/build/elfuse-candidate"
DEFAULT_SYSROOT = LAB / "fixtures/runtime/arch-case"
DEFAULT_LINUX_PYTHON = LAB / "fixtures/runtime/arch-case/usr/bin/python3"
DEFAULT_PREFIX = LAB / "fixtures/runtime/steam-shaped/compat/pfx"
DEFAULT_MANIFEST = LAB / "artifacts/public-proton/bundle.json"
DEFAULT_BUNDLE = LAB / "fixtures/runtime/proton-derived"
DEFAULT_LOGS = LAB / "logs/steam-handoff"


def validate_guest_env(guest_env: Any) -> Dict[str, str]:
    """
    Validate guest environment dictionary passed to elfuse via --env KEY=VALUE.
    Strict constraints:
    - Must be a dictionary (or None).
    - Keys must be non-empty strings, no '=' and no NUL bytes.
    - Values must be strings, no NUL bytes.
    """
    if guest_env is None:
        return {}
    if not isinstance(guest_env, dict):
        raise TypeError(f"guest_env must be a dict, got {type(guest_env).__name__}")
    clean_env = {}
    for k, v in guest_env.items():
        if not isinstance(k, str):
            raise TypeError(f"guest_env key must be str, got {type(k).__name__}: {k!r}")
        if not k:
            raise ValueError("guest_env key cannot be empty")
        if "=" in k:
            raise ValueError(f"guest_env key cannot contain '=': {k!r}")
        if "\0" in k:
            raise ValueError(f"guest_env key cannot contain NUL byte: {k!r}")
        if not isinstance(v, str):
            raise TypeError(f"guest_env value for {k!r} must be str, got {type(v).__name__}: {v!r}")
        if "\0" in v:
            raise ValueError(f"guest_env value for {k!r} cannot contain NUL byte: {v!r}")
        clean_env[k] = v
    return clean_env


def prepare_runtime_tool(
    output_dir: Union[str, Path],
    target_dir: Union[str, Path],
    execute_runtime: bool = False,
    elfuse_path: Optional[Union[str, Path]] = None,
    sysroot: Optional[Union[str, Path]] = None,
    prefix: Optional[Union[str, Path]] = None,
    linux_python: Optional[Union[str, Path]] = None,
    manifest: Optional[Union[str, Path]] = None,
    runtime_bundle: Optional[Union[str, Path]] = None,
    logs_dir: Optional[Union[str, Path]] = None,
    absock_base: Optional[Union[str, Path]] = None,
    guest_env: Optional[Dict[str, str]] = None,
    diagnostic_env: Optional[Dict[str, str]] = None,
    timeout: float = 110.0,
) -> Dict:
    """
    Prepare an offline Steam-shaped compatibility tool candidate.
    Generates wrapper, toolmanifest.vdf, compatibilitytool.vdf, and install-plan.json.
    Does NOT install to host Steam directories (applied: false).
    """
    out = local(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = Path(target_dir).absolute()

    elfuse_p = local(elfuse_path or DEFAULT_ELFUSE)
    sysroot_p = local(sysroot or DEFAULT_SYSROOT)
    prefix_p = local(prefix or DEFAULT_PREFIX)
    linux_py_p = local(linux_python or DEFAULT_LINUX_PYTHON)
    manifest_p = local(manifest or DEFAULT_MANIFEST)
    if runtime_bundle == "$DIR" or runtime_bundle == out or (runtime_bundle and Path(runtime_bundle).resolve() == out.resolve()):
        bundle_val = "$DIR"
    else:
        bundle_val = str(local(runtime_bundle or DEFAULT_BUNDLE))
    logs_p = local(logs_dir or DEFAULT_LOGS)
    logs_p.mkdir(parents=True, exist_ok=True)

    # Validate descriptor of elfuse candidate
    descriptor = get_elfuse_descriptor(elfuse_p)

    # If absock_base is specified, perform strict hash capability check and path validation
    validated_absock_base = None
    if absock_base is not None:
        if not descriptor.get("capabilities", {}).get("supports_absock_base"):
            raise ValueError(
                f"Runtime {descriptor.get('source_baseline')} does not have supports_absock_base capability; "
                f"explicit absock_base requires socket-derived elfuse (06a2fceb...)"
            )
        from scripts.backend.bundle import validate_absock_base
        validated_absock_base = validate_absock_base(absock_base)

    # 1. Write internal config for the wrapper
    validated_guest_env = validate_guest_env(guest_env)

    config_data = {
        "execute_runtime": execute_runtime,
        "elfuse_path": str(elfuse_p),
        "elfuse_sha256": descriptor["sha256"],
        "elfuse_commit": descriptor.get("commit"),
        "sysroot": str(sysroot_p),
        "prefix": str(prefix_p),
        "linux_python": str(linux_py_p),
        "manifest": str(manifest_p),
        "runtime_bundle": bundle_val,
        "logs_dir": str(logs_p),
        "absock_base": validated_absock_base,
        "guest_env": validated_guest_env,
        "diagnostic_env": diagnostic_env or {},
        "timeout": timeout,
    }
    config_file = out / "config.json"
    config_file.write_text(json.dumps(config_data, indent=2) + "\n")

    # 2. Write wrapper script
    script_path = (LAB / "scripts/backend/steam_handoff.py").resolve()
    py_cmd = shlex.quote(str(sys.executable))
    script_cmd = shlex.quote(str(script_path))
    cfg_cmd = shlex.quote(str(config_file.resolve()))

    wrapper = out / "proton-wrapper.sh"
    wrapper_content = (
        "#!/bin/sh\n"
        'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        "unset LD_PRELOAD LD_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH\n"
        'if [ "$1" = "--" ]; then\n'
        "  shift\n"
        "fi\n"
        'if [ -f "$DIR/config.json" ]; then\n'
        '  CFG_PATH="$DIR/config.json"\n'
        "else\n"
        f"  CFG_PATH={cfg_cmd}\n"
        "fi\n"
        f'exec {py_cmd} {script_cmd} --config "$CFG_PATH" -- "$@"\n'
    )
    wrapper.write_text(wrapper_content)
    wrapper.chmod(0o700)

    # 3. Write toolmanifest.vdf
    encoded_wrapper = str(wrapper).replace("\\", "\\\\").replace('"', '\\"')
    manifest_content = (
        '"manifest"\n'
        "{\n"
        ' "version" "2"\n'
        f' "commandline" "\\"{encoded_wrapper}\\" -- %verb%"\n'
        "}\n"
    )
    (out / "toolmanifest.vdf").write_text(manifest_content)

    # 4. Write compatibilitytool.vdf
    compat_content = (
        '"compatibilitytools"\n'
        "{\n"
        ' "compat_tools"\n'
        " {\n"
        '  "proton-macos-lab-runtime"\n'
        "  {\n"
        '   "install_path" "."\n'
        '   "display_name" "Proton macOS Lab (ARM64 Runtime Execution)"\n'
        '   "from_oslist" "windows"\n'
        '   "to_oslist" "macos"\n'
        "  }\n"
        " }\n"
        "}\n"
    )
    (out / "compatibilitytool.vdf").write_text(compat_content)

    # 5. Write install-plan.json
    result = {
        "candidate": str(out),
        "target": str(target / "proton-macos-lab-runtime"),
        "applied": False,
        "execute_runtime": execute_runtime,
        "purpose": "Offline Steam-shaped runtime candidate handoff",
        "elfuse_candidate": str(elfuse_p),
        "elfuse_sha256": descriptor["sha256"],
        "sysroot": str(sysroot_p),
        "linux_python": str(linux_py_p),
        "compat_prefix": str(prefix_p),
        "backup": "Before any future install, preserve an existing target directory under a unique backup name.",
        "rollback": "Remove only the installed candidate directory after identity verification, then restore backup. No install has run.",
    }
    (out / "install-plan.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def execute_from_config(config_path: Path, args: List[str], timeout: float = 110.0) -> int:
    """
    Handle wrapper invocation: validates verb, builds plan, and either outputs plan (plan-only)
    or runs isolated execution (if execute_runtime=True).
    """
    if not args:
        sys.stderr.write("Error: Expected Steam-shaped invocation arguments: <verb> <target> [args...]\n")
        return 2

    verb = args[0]
    if verb not in KNOWN_STEAM_VERBS:
        sys.stderr.write(
            f"Error: Unknown or unsupported Steam verb '{verb}'. Supported verbs: {sorted(KNOWN_STEAM_VERBS)}\n"
        )
        return 2

    target_and_args = args[1:]

    cfg = json.loads(Path(config_path).read_text())

    # Verify that the current elfuse binary matches the frozen sha256 recorded in config
    try:
        current_desc = get_elfuse_descriptor(cfg.get("elfuse_path"))
    except Exception as e:
        blocked_res = {
            "status": "BLOCKED",
            "reason": f"Failed to inspect elfuse candidate: {e}",
            "execution_performed": False,
        }
        print(json.dumps(blocked_res, indent=2))
        return 20

    expected_sha = cfg.get("elfuse_sha256")
    actual_sha = current_desc.get("sha256")
    if expected_sha and actual_sha != expected_sha:
        blocked_res = {
            "status": "BLOCKED",
            "reason": f"Frozen elfuse hash mismatch: expected {expected_sha}, observed {actual_sha}",
            "execution_performed": False,
        }
        print(json.dumps(blocked_res, indent=2))
        return 20

    cfg_dir = Path(config_path).resolve().parent
    bundle_val = cfg.get("runtime_bundle")
    if bundle_val:
        bundle_str = str(bundle_val)
        if bundle_str == "$DIR" or bundle_str.startswith("$DIR/"):
            resolved_bundle = (cfg_dir / bundle_str[4:].lstrip("/")).resolve()
        else:
            p = Path(bundle_val)
            resolved_bundle = p.resolve() if p.is_absolute() else (cfg_dir / p).resolve()
    else:
        resolved_bundle = cfg_dir

    # Build plan using fixed lab configuration (immune to caller environment override)
    plan = build_plan(
        manifest=cfg["manifest"],
        sysroot=cfg["sysroot"],
        prefix=cfg["prefix"],
        arguments=[verb] + target_and_args,
        engine="proton",
        linux_python=cfg["linux_python"],
        runtime_bundle=resolved_bundle,
        elfuse_path=cfg["elfuse_path"],
        absock_base=cfg.get("absock_base"),
    )

    if plan["status"] != "PLAN_READY":
        print(json.dumps(plan, indent=2))
        return 20

    argv = list(plan["argv"])
    validated_guest = validate_guest_env(cfg.get("guest_env"))
    if validated_guest:
        py_str = str(cfg.get("linux_python", ""))
        try:
            insert_idx = argv.index(py_str)
        except ValueError:
            blocked_res = {
                "status": "BLOCKED",
                "reason": f"Target guest interpreter '{py_str}' not found in plan argv",
                "execution_performed": False,
            }
            print(json.dumps(blocked_res, indent=2))
            return 20
        env_args = []
        for k, v in validated_guest.items():
            env_args.extend(["--env", f"{k}={v}"])
        argv = argv[:insert_idx] + env_args + argv[insert_idx:]
    plan["argv"] = argv

    # Default plan-only mode
    if not cfg.get("execute_runtime", False):
        print(json.dumps(plan, indent=2))
        return 0

    # Explicit execute mode
    prefix_p = Path(cfg["prefix"])
    prefix_p.mkdir(parents=True, exist_ok=True)
    logs_p = Path(cfg.get("logs_dir", LAB / "logs/steam-handoff"))
    logs_p.mkdir(parents=True, exist_ok=True)

    # Inject required Proton ARM64 runtime flags
    env = dict(plan["env"])
    env["PROTON_USE_ARM64"] = "1"
    env["WINEESYNC"] = "0"
    env["WINEFSYNC"] = "0"
    env["PROTON_NO_ESYNC"] = "1"
    env["PROTON_NO_FSYNC"] = "1"
    env["PROTON_NO_NTSYNC"] = "1"

    if cfg.get("diagnostic_env"):
        env.update(cfg["diagnostic_env"])
    timeout_val = float(cfg.get("timeout", timeout))

    result = run_isolated(plan["argv"], logs_p, timeout=timeout_val, extra_env=env)
    result["provenance"] = plan["provenance"]
    result["runtime_descriptor"] = plan.get("runtime_descriptor")
    result["verb"] = verb
    result["target_and_args"] = target_and_args
    print(json.dumps(result, indent=2))

    if result.get("timed_out"):
        return 124
    target_rc = result.get("target_exit")
    if target_rc is not None:
        return target_rc
    return result.get("exit", 1)


def main():
    p = argparse.ArgumentParser(description="Offline Steam-shaped runtime handoff generator and runner.")
    p.add_argument("--prepare", type=Path, help="Directory to output Steam-shaped tool candidate files")
    p.add_argument("--target", type=Path, help="Mock target directory for compatibilitytools.d")
    p.add_argument("--execute-runtime", action="store_true", help="Explicitly enable execution mode in generated candidate")
    p.add_argument("--elfuse", type=Path, help="Explicit path to elfuse binary")
    p.add_argument("--absock-base", type=Path, default=None, help="Explicit lab-isolated absock relay base directory")
    p.add_argument("--config", type=Path, help="Internal: config file for wrapper execution")
    p.add_argument("--timeout", type=float, default=110.0, help="Execution timeout in seconds")
    p.add_argument("arguments", nargs=argparse.REMAINDER)
    a = p.parse_args()

    if a.prepare:
        if not a.target:
            p.error("--prepare requires --target (mock Steam compatibilitytools.d target path)")
        res = prepare_runtime_tool(
            output_dir=a.prepare,
            target_dir=a.target,
            execute_runtime=a.execute_runtime,
            elfuse_path=a.elfuse,
            absock_base=a.absock_base,
        )
        print(json.dumps(res, indent=2))
        return 0

    if a.config:
        args = a.arguments[1:] if a.arguments[:1] == ["--"] else a.arguments
        return execute_from_config(a.config, args, timeout=a.timeout)

    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
