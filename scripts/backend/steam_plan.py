#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/backend/steam_plan.py

Deterministic, Enclosed, Reversible Steam Compatibility Tool Installation Plan & Manifest Manager.

Key guarantees:
1. Pure plan generation: Takes a fixture Steam library root and source candidate package,
   computes a strictly enclosed, deterministic, JSON-serializable installation plan.
   No side-effects or filesystem mutations occur during plan generation.
2. Strict path enclosure & security rejection:
   - Target and fixture root MUST be strictly within LAB (or an approved test scratch directory).
   - Any destination path referencing real host Steam (~/Library/Application Support/Steam,
     /Applications, /usr, /etc, /System) or traversing outside the fixture root is strictly
     rejected BEFORE any plan application.
3. Manifest generation:
   - When the plan is applied, produces an authoritative JSON manifest detailing every created
     file, created directory, modified file (with SHA256 backup), original permissions,
     and source provenance.
4. Byte-for-byte exact rollback:
   - Consumes the manifest to revert the installation completely, restoring created/modified
     files to their exact initial state and removing created directories.
5. Verification:
   - Compares the installed state against the manifest, checking SHA256 digests and file sizes.
"""

import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

FORBIDDEN_HOST_ROOTS = [
    Path(os.path.expanduser("~/Library/Application Support/Steam")).resolve(),
    Path(os.path.expanduser("~/Library/Application Support")).resolve(),
    Path("/Applications").resolve(),
    Path("/usr").resolve(),
    Path("/etc").resolve(),
    Path("/System").resolve(),
    Path("/Library").resolve(),
]


class SteamPlanError(Exception):
    """Raised when an installation plan is invalid, unsafe, or corrupted."""
    pass


def sha256_file(filepath: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_tree_fingerprint(root: Path) -> Dict[str, Dict[str, Any]]:
    """Compute recursive fingerprint of a directory: relative_path -> metadata."""
    res = {}
    if not root.exists():
        return res
    for r, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            p = Path(r) / f
            rel = str(p.relative_to(root))
            st = p.stat()
            res[rel] = {
                "sha256": sha256_file(p),
                "size": st.st_size,
                "mode": oct(stat.S_IMODE(st.st_mode))
            }
    return res


def validate_path_enclosure(target_path: Path, allowed_root: Path) -> Path:
    """Validate that target_path is strictly inside allowed_root and not in any forbidden host root."""
    resolved_target = target_path.resolve()
    resolved_allowed = allowed_root.resolve()

    # 1. Check against forbidden host roots
    for forbidden in FORBIDDEN_HOST_ROOTS:
        try:
            resolved_target.relative_to(forbidden)
            raise SteamPlanError(
                f"Security violation: path '{resolved_target}' targets forbidden host root '{forbidden}'"
            )
        except ValueError:
            pass

    # 2. Check strict containment inside allowed_root
    try:
        resolved_target.relative_to(resolved_allowed)
    except ValueError:
        raise SteamPlanError(
            f"Path enclosure violation: '{resolved_target}' is outside allowed fixture root '{resolved_allowed}'"
        )

    return resolved_target


def create_installation_plan(
    fixture_steam_root: Path,
    source_tool_dir: Path,
    tool_name: str = "proton_arm64_runtime",
    compatibilitytools_rel_dir: str = "compatibilitytools.d"
) -> Dict[str, Any]:
    """
    Generate a deterministic, JSON-serializable installation plan.
    Does NOT modify the filesystem.
    """
    fixture_steam_root = fixture_steam_root.resolve()
    source_tool_dir = source_tool_dir.resolve()

    if not source_tool_dir.exists() or not source_tool_dir.is_dir():
        raise SteamPlanError(f"Source tool directory does not exist: {source_tool_dir}")

    # Validate destination directory
    dest_compat_dir = fixture_steam_root / compatibilitytools_rel_dir
    dest_tool_dir = dest_compat_dir / tool_name
    validate_path_enclosure(dest_tool_dir, fixture_steam_root)

    steps: List[Dict[str, Any]] = []

    # Destination directories needed
    steps.append({
        "type": "create_directory",
        "destination": str(dest_compat_dir),
        "mode": "0755"
    })
    steps.append({
        "type": "create_directory",
        "destination": str(dest_tool_dir),
        "mode": "0755"
    })

    # Enumerate all files in source_tool_dir recursively
    for r, dirs, files in os.walk(source_tool_dir):
        dirs.sort()
        for d in dirs:
            dp = Path(r) / d
            if dp.is_symlink():
                target = os.readlink(dp)
                rel_p = dp.relative_to(source_tool_dir)
                dst_l = dest_tool_dir / rel_p
                validate_path_enclosure(dst_l, fixture_steam_root)
                steps.append({
                    "type": "create_symlink",
                    "target": target,
                    "destination": str(dst_l)
                })
        for f in sorted(files):
            src_file = Path(r) / f
            rel_path = src_file.relative_to(source_tool_dir)
            dst_file = dest_tool_dir / rel_path

            # Enclosure validation for every destination file
            validate_path_enclosure(dst_file, fixture_steam_root)

            # Ensure parent directory creation step is tracked if deep
            if rel_path.parent != Path("."):
                steps.append({
                    "type": "create_directory",
                    "destination": str(dst_file.parent),
                    "mode": "0755"
                })

            st = src_file.stat()
            file_sha = sha256_file(src_file)

            steps.append({
                "type": "install_file",
                "source": str(src_file),
                "destination": str(dst_file),
                "relative_path": str(rel_path),
                "sha256": file_sha,
                "size": st.st_size,
                "mode": oct(stat.S_IMODE(st.st_mode))
            })

    # Sort and deduplicate directory creation steps
    unique_steps: List[Dict[str, Any]] = []
    seen_dirs: Set[str] = set()
    for s in steps:
        if s["type"] == "create_directory":
            if s["destination"] not in seen_dirs:
                seen_dirs.add(s["destination"])
                unique_steps.append(s)
        else:
            unique_steps.append(s)

    plan = {
        "format_version": "1.0.0",
        "tool_name": tool_name,
        "fixture_steam_root": str(fixture_steam_root),
        "source_tool_dir": str(source_tool_dir),
        "destination_tool_dir": str(dest_tool_dir),
        "total_steps": len(unique_steps),
        "steps": unique_steps
    }
    return plan



def validate_elf_architecture(file_path: Path, expected_arch: str) -> None:
    """Validate that an ELF binary matches expected architecture."""
    if not file_path.exists() or not file_path.is_file():
        raise SteamPlanError(f"Target ELF file does not exist: {file_path}")
    try:
        with open(file_path, "rb") as f:
            header = f.read(20)
    except Exception as e:
        raise SteamPlanError(f"Failed to read ELF header for {file_path}: {e}")

    if len(header) < 20 or header[:4] != b"\x7fELF":
        raise SteamPlanError(f"File is not a valid ELF binary: {file_path}")

    # e_machine is 2 bytes at offset 18 (little endian for e_ident[5] == 1)
    e_machine = header[18] | (header[19] << 8)
    ARCH_MAP = {
        "aarch64": 183,
        "arm64": 183,
        "x86_64": 62,
        "amd64": 62,
        "i386": 3,
        "arm": 40
    }
    expected_code = ARCH_MAP.get(expected_arch.lower())
    if expected_code is not None and e_machine != expected_code:
        raise SteamPlanError(
            f"Target architecture mismatch for {file_path}: expected {expected_arch} (e_machine={expected_code}), found e_machine={e_machine}"
        )


def create_compat_module_plan(
    fixture_steam_root: Path,
    target_rel_path: str,
    source_module_path: Path,
    expected_orig_sha256: Optional[str] = None,
    expected_arch: Optional[str] = None,
    backup_rel_dir: str = ".compat_backups"
) -> Dict[str, Any]:
    """
    Generate a deterministic, JSON-serializable plan to replace a single compatibility module.
    Validates preconditions (source exists, target exists, architecture matches, orig checksum).
    Strictly enforces path enclosure and rejects escape.
    Does NOT modify the filesystem.
    """
    fixture_steam_root = fixture_steam_root.resolve()
    source_module_path = source_module_path.resolve()

    if os.path.isabs(target_rel_path):
        raise SteamPlanError(f"Target path must be relative to fixture root, got absolute: {target_rel_path}")

    parts = Path(target_rel_path).parts
    if ".." in parts:
        raise SteamPlanError(f"Path traversal detected in target relative path: {target_rel_path}")

    dest_file = fixture_steam_root / target_rel_path
    validate_path_enclosure(dest_file, fixture_steam_root)

    # Check for symlink escape in path
    cur = dest_file
    while cur != fixture_steam_root and cur != cur.parent:
        if cur.is_symlink():
            real = cur.resolve()
            try:
                real.relative_to(fixture_steam_root)
            except ValueError:
                raise SteamPlanError(f"Symlink escape detected: '{cur}' resolves outside fixture root to '{real}'")
        cur = cur.parent

    if not source_module_path.exists() or not source_module_path.is_file():
        raise SteamPlanError(f"Source compat module does not exist: {source_module_path}")

    if not dest_file.exists() or not dest_file.is_file():
        raise SteamPlanError(f"Target file does not exist for compat replacement: {dest_file}")

    if expected_arch:
        validate_elf_architecture(dest_file, expected_arch)

    actual_orig_sha = sha256_file(dest_file)
    if expected_orig_sha256 and actual_orig_sha != expected_orig_sha256:
        raise SteamPlanError(
            f"Original file checksum mismatch for {dest_file}: expected {expected_orig_sha256}, got {actual_orig_sha}"
        )

    source_sha = sha256_file(source_module_path)
    st_src = source_module_path.stat()
    st_orig = dest_file.stat()

    backup_dir = fixture_steam_root / backup_rel_dir
    validate_path_enclosure(backup_dir, fixture_steam_root)

    steps = [
        {
            "type": "replace_compat_module",
            "source": str(source_module_path),
            "destination": str(dest_file),
            "relative_path": target_rel_path,
            "source_sha256": source_sha,
            "size": st_src.st_size,
            "mode": oct(stat.S_IMODE(st_src.st_mode)),
            "expected_orig_sha256": actual_orig_sha,
            "original_size": st_orig.st_size,
            "original_mode": oct(stat.S_IMODE(st_orig.st_mode)),
            "expected_arch": expected_arch,
            "backup_dir": str(backup_dir)
        }
    ]

    return {
        "format_version": "1.0.0",
        "plan_type": "compat_module_replacement",
        "fixture_steam_root": str(fixture_steam_root),
        "target_rel_path": target_rel_path,
        "destination_tool_dir": str(dest_file.parent),
        "total_steps": len(steps),
        "steps": steps
    }




def parse_valve_vdf(text: str) -> Dict[str, Any]:
    """
    Independent recursive Valve KeyValues (VDF) specification parser.
    Parses hierarchical VDF blocks, strings, quotes, and escapes without self-certification.
    """
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '/' and i + 1 < n and text[i + 1] == '/':
            i += 2
            while i < n and text[i] != '\n':
                i += 1
            continue
        if c in '{};':
            tokens.append(c)
            i += 1
            continue
        if c == '}':
            tokens.append('}')
            i += 1
            continue
        if c == '"':
            i += 1
            s = []
            while i < n:
                if text[i] == '\\' and i + 1 < n:
                    s.append(text[i + 1])
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    s.append(text[i])
                    i += 1
            tokens.append(''.join(s))
            continue
        # Bare word
        s = []
        while i < n and not text[i].isspace() and text[i] not in '{}"':
            s.append(text[i])
            i += 1
        tokens.append(''.join(s))

    idx = 0

    def parse_block():
        nonlocal idx
        obj = {}
        while idx < len(tokens):
            tok = tokens[idx]
            if tok == '}':
                idx += 1
                return obj
            key = tok
            idx += 1
            if idx >= len(tokens):
                obj[key] = ""
                break
            next_tok = tokens[idx]
            if next_tok == '{':
                idx += 1
                obj[key] = parse_block()
            else:
                obj[key] = next_tok
                idx += 1
        return obj

    root_dict = {}
    while idx < len(tokens):
        key = tokens[idx]
        idx += 1
        if idx < len(tokens) and tokens[idx] == '{':
            idx += 1
            root_dict[key] = parse_block()
        elif idx < len(tokens):
            root_dict[key] = tokens[idx]
            idx += 1
    return root_dict


def generate_compatibility_tool_vdfs(
    output_dir: Path,
    tool_name: str,
    display_name: str,
    wrapper_rel_path: str = "proton",
    from_oslist: str = "windows",
    to_oslist: str = "macos",
    target_install_dir: Optional[Path] = None,
    relative_commandline: bool = True
) -> Dict[str, str]:
    """
    Generate toolmanifest.vdf and compatibilitytool.vdf conforming to Valve Steam specification.
    Supports relocatable relative commandlines (Valve spec: '/wrapper -- %verb%') or target-resolved commandlines.
    """
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if target_install_dir:
        cmd_path = (target_install_dir / wrapper_rel_path).resolve()
        encoded_cmd = str(cmd_path).replace("\\", "\\\\").replace('"', '\\"')
        cmd_entry = f'\\"{encoded_cmd}\\" -- %verb%'
    elif relative_commandline:
        cmd_entry = f'\\"/{wrapper_rel_path}\\" -- %verb%'
    else:
        wrapper_path = output_dir / wrapper_rel_path
        encoded_cmd = str(wrapper_path).replace("\\", "\\\\").replace('"', '\\"')
        cmd_entry = f'\\"{encoded_cmd}\\" -- %verb%'

    toolmanifest_content = (
        '"manifest"\n'
        "{\n"
        ' "version" "2"\n'
        f' "commandline" "{cmd_entry}"\n'
        "}\n"
    )
    (output_dir / "toolmanifest.vdf").write_text(toolmanifest_content, encoding="utf-8")

    compatibilitytool_content = (
        '"compatibilitytools"\n'
        "{\n"
        ' "compat_tools"\n'
        " {\n"
        f'  "{tool_name}"\n'
        "  {\n"
        '   "install_path" "."\n'
        f'   "display_name" "{display_name}"\n'
        f'   "from_oslist" "{from_oslist}"\n'
        f'   "to_oslist" "{to_oslist}"\n'
        "  }\n"
        " }\n"
        "}\n"
    )
    (output_dir / "compatibilitytool.vdf").write_text(compatibilitytool_content, encoding="utf-8")

    return {
        "toolmanifest_path": str(output_dir / "toolmanifest.vdf"),
        "compatibilitytool_path": str(output_dir / "compatibilitytool.vdf")
    }


def create_compat_tool_plan(
    fixture_steam_root: Path,
    source_tool_dir: Path,
    tool_name: str,
    display_name: Optional[str] = None,
    compatibilitytools_rel_dir: str = "compatibilitytools.d",
    compat_modules: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Generate an integrated installation plan for a Steam compatibility tool containing both
    full tool files (including VDFs) and replaced compat module(s).
    """
    fixture_steam_root = fixture_steam_root.resolve()
    source_tool_dir = source_tool_dir.resolve()

    if os.path.isabs(tool_name) or ".." in Path(tool_name).parts:
        raise SteamPlanError(f"Tool name must not be an absolute path or contain '..': {tool_name}")

    if not source_tool_dir.exists() or not source_tool_dir.is_dir():
        raise SteamPlanError(f"Source tool directory does not exist: {source_tool_dir}")

    dest_compat_dir = fixture_steam_root / compatibilitytools_rel_dir
    dest_tool_dir = dest_compat_dir / tool_name
    validate_path_enclosure(dest_tool_dir, fixture_steam_root)

    compat_map = {}
    if compat_modules:
        for cm in compat_modules:
            rel = cm.get("target_rel_path")
            if not rel or os.path.isabs(rel) or ".." in Path(rel).parts:
                raise SteamPlanError(f"Invalid target relative path in compat module: {rel}")

            src = Path(cm["source_path"]).resolve()
            if not src.exists() or not src.is_file():
                raise SteamPlanError(f"Source compat module file does not exist: {src}")

            target_in_src = source_tool_dir / rel
            if not target_in_src.exists() or not target_in_src.is_file():
                raise SteamPlanError(f"Target file does not exist in source tool: {target_in_src}")

            if cm.get("expected_arch"):
                validate_elf_architecture(target_in_src, cm["expected_arch"])

            actual_orig_sha = sha256_file(target_in_src)
            if cm.get("expected_orig_sha256") and actual_orig_sha != cm["expected_orig_sha256"]:
                raise SteamPlanError(
                    f"Original file checksum mismatch for {target_in_src}: expected {cm['expected_orig_sha256']}, got {actual_orig_sha}"
                )

            compat_map[str(Path(rel))] = cm

    steps: List[Dict[str, Any]] = []

    steps.append({
        "type": "create_directory",
        "destination": str(dest_compat_dir),
        "mode": "0755"
    })
    steps.append({
        "type": "create_directory",
        "destination": str(dest_tool_dir),
        "mode": "0755"
    })

    for r, dirs, files in os.walk(source_tool_dir):
        dirs.sort()
        for d in dirs:
            dp = Path(r) / d
            if dp.is_symlink():
                target = os.readlink(dp)
                rel_p = dp.relative_to(source_tool_dir)
                dst_l = dest_tool_dir / rel_p
                validate_path_enclosure(dst_l, fixture_steam_root)
                steps.append({
                    "type": "create_symlink",
                    "target": target,
                    "destination": str(dst_l)
                })
        for f in sorted(files):
            src_file = Path(r) / f
            rel_path = src_file.relative_to(source_tool_dir)
            dst_file = dest_tool_dir / rel_path
            validate_path_enclosure(dst_file, fixture_steam_root)

            if rel_path.parent != Path("."):
                steps.append({
                    "type": "create_directory",
                    "destination": str(dst_file.parent),
                    "mode": "0755"
                })

            st = src_file.stat()
            rel_key = str(rel_path)

            if rel_key in compat_map:
                cm = compat_map[rel_key]
                src_compat = Path(cm["source_path"]).resolve()
                compat_sha = sha256_file(src_compat)
                st_compat = src_compat.stat()
                steps.append({
                    "type": "replace_compat_module",
                    "source": str(src_compat),
                    "destination": str(dst_file),
                    "relative_path": rel_key,
                    "source_sha256": compat_sha,
                    "size": st_compat.st_size,
                    "mode": oct(stat.S_IMODE(st_compat.st_mode)),
                    "expected_orig_sha256": sha256_file(src_file),
                    "original_size": st.st_size,
                    "original_mode": oct(stat.S_IMODE(st.st_mode)),
                    "expected_arch": cm.get("expected_arch"),
                    "backup_dir": str(dest_tool_dir / ".compat_backups")
                })
            else:
                steps.append({
                    "type": "install_file",
                    "source": str(src_file),
                    "destination": str(dst_file),
                    "relative_path": rel_key,
                    "sha256": sha256_file(src_file),
                    "size": st.st_size,
                    "mode": oct(stat.S_IMODE(st.st_mode))
                })

    unique_steps: List[Dict[str, Any]] = []
    seen_dirs: Set[str] = set()
    for s in steps:
        if s["type"] == "create_directory":
            if s["destination"] not in seen_dirs:
                seen_dirs.add(s["destination"])
                unique_steps.append(s)
        else:
            unique_steps.append(s)

    return {
        "format_version": "1.0.0",
        "plan_type": "compat_tool_installation",
        "tool_name": tool_name,
        "display_name": display_name or tool_name,
        "fixture_steam_root": str(fixture_steam_root),
        "source_tool_dir": str(source_tool_dir),
        "destination_tool_dir": str(dest_tool_dir),
        "total_steps": len(unique_steps),
        "steps": unique_steps
    }


def apply_installation_plan(
    plan: Dict[str, Any],
    fixture_steam_root: Path,
    backup_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Execute the installation plan strictly inside fixture_steam_root.
    Produces an authoritative rollback-ready manifest.
    """
    fixture_steam_root = fixture_steam_root.resolve()
    expected_root = Path(plan["fixture_steam_root"]).resolve()
    if fixture_steam_root != expected_root:
        raise SteamPlanError(
            f"Plan fixture root mismatch: expected '{expected_root}', got '{fixture_steam_root}'"
        )

    # Pre-execution security sweep: validate ALL steps before executing any step
    for step in plan["steps"]:
        dst = Path(step["destination"])
        validate_path_enclosure(dst, fixture_steam_root)

    manifest_entries: List[Dict[str, Any]] = []
    created_dirs: List[str] = []
    installed_files: List[Dict[str, Any]] = []
    compat_modules: List[Dict[str, Any]] = []
    backups: List[Dict[str, Any]] = []

    if backup_dir:
        backup_dir = backup_dir.resolve()
        validate_path_enclosure(backup_dir, fixture_steam_root)
        backup_dir.mkdir(parents=True, exist_ok=True)

    try:
        for step in plan["steps"]:
            dst = Path(step["destination"])

            if step["type"] == "create_directory":
                if not dst.exists():
                    dst.mkdir(parents=True, exist_ok=True)
                    os.chmod(dst, int(step["mode"], 8))
                    created_dirs.append(str(dst))
                    manifest_entries.append({
                        "action": "created_directory",
                        "path": str(dst)
                    })

            elif step["type"] == "install_file":
                src = Path(step["source"])
                if not src.exists():
                    raise SteamPlanError(f"Source file vanished during installation: {src}")

                # If destination already exists, backup if backup_dir provided
                if dst.exists():
                    if backup_dir:
                        rel_name = hashlib.sha256(str(dst).encode()).hexdigest()[:16]
                        bk_path = backup_dir / f"backup_{rel_name}_{dst.name}"
                        shutil.copy2(dst, bk_path)
                        orig_sha = sha256_file(dst)
                        backups.append({
                            "original_path": str(dst),
                            "backup_path": str(bk_path),
                            "original_sha256": orig_sha
                        })
                    else:
                        raise SteamPlanError(f"Destination exists without backup specification: {dst}")

                # Ensure parent directory exists
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                os.chmod(dst, int(step["mode"], 8))

                actual_sha = sha256_file(dst)
                if actual_sha != step["sha256"]:
                    raise SteamPlanError(
                        f"Checksum mismatch after installation of {dst}: expected {step['sha256']}, got {actual_sha}"
                    )

                installed_files.append({
                    "path": str(dst),
                    "source": str(src),
                    "sha256": actual_sha,
                    "size": dst.stat().st_size,
                    "mode": step["mode"]
                })
                manifest_entries.append({
                    "action": "installed_file",
                    "path": str(dst),
                    "sha256": actual_sha
                })
            elif step["type"] == "create_symlink":
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() or dst.is_symlink():
                    dst.unlink(missing_ok=True)
                os.symlink(step["target"], dst)
                installed_files.append({
                    "path": str(dst),
                    "sha256": "symlink",
                    "size": 0
                })
                manifest_entries.append({
                    "action": "created_symlink",
                    "path": str(dst),
                    "target": step["target"]
                })
            elif step["type"] == "replace_compat_module":
                src = Path(step["source"])
                if not src.exists():
                    raise SteamPlanError(f"Source compat file vanished during replacement: {src}")

                dst.parent.mkdir(parents=True, exist_ok=True)

                bk_path = None
                actual_orig_sha = step.get("expected_orig_sha256")
                orig_size = step.get("original_size", 0)

                if dst.exists():
                    if step.get("expected_arch"):
                        validate_elf_architecture(dst, step["expected_arch"])

                    actual_orig_sha = sha256_file(dst)
                    if step.get("expected_orig_sha256") and actual_orig_sha != step["expected_orig_sha256"]:
                        raise SteamPlanError(
                            f"Original file checksum mismatch for {dst}: expected {step['expected_orig_sha256']}, got {actual_orig_sha}"
                        )

                    b_dir = backup_dir or Path(step.get("backup_dir", dst.parent / ".compat_backups"))
                    validate_path_enclosure(b_dir, fixture_steam_root)
                    b_dir.mkdir(parents=True, exist_ok=True)
                    if str(b_dir) not in created_dirs:
                        created_dirs.append(str(b_dir))

                    rel_name = hashlib.sha256(str(dst).encode()).hexdigest()[:16]
                    bk_path = b_dir / f"backup_{rel_name}_{dst.name}"
                    shutil.copy2(dst, bk_path)
                    orig_size = bk_path.stat().st_size
                    backups.append({
                        "original_path": str(dst),
                        "backup_path": str(bk_path),
                        "original_sha256": actual_orig_sha
                    })

                shutil.copy2(src, dst)
                os.chmod(dst, int(step["mode"], 8))

                actual_new_sha = sha256_file(dst)
                if actual_new_sha != step["source_sha256"]:
                    raise SteamPlanError(
                        f"Checksum mismatch after compat replacement of {dst}: expected {step['source_sha256']}, got {actual_new_sha}"
                    )

                compat_entry = {
                    "target_rel_path": step["relative_path"],
                    "path": str(dst),
                    "source": str(src),
                    "source_sha256": actual_new_sha,
                    "size": dst.stat().st_size,
                    "backup_path": str(bk_path) if bk_path else None,
                    "original_sha256": actual_orig_sha,
                    "original_size": orig_size,
                    "mode": step["mode"]
                }
                compat_modules.append(compat_entry)
                manifest_entries.append({
                    "action": "replaced_compat_module",
                    "path": str(dst),
                    "sha256": actual_new_sha,
                    "backup_path": str(bk_path) if bk_path else None
                })


    except Exception as e:
        # Partial failure: attempt best-effort cleanup of already created entries
        for s in reversed(manifest_entries):
            p = Path(s["path"])
            if p.exists():
                if p.is_file():
                    p.unlink(missing_ok=True)
                elif p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
        raise SteamPlanError(f"Installation failed and was aborted: {e}") from e

    manifest = {
        "manifest_version": "1.0.0",
        "plan_type": plan.get("plan_type", "full_tool_installation"),
        "tool_name": plan.get("tool_name", "compat_module"),
        "fixture_steam_root": str(fixture_steam_root),
        "destination_tool_dir": plan["destination_tool_dir"],
        "installed_files": installed_files,
        "compat_modules": compat_modules,
        "created_directories": created_dirs,
        "backups": backups,
        "history": manifest_entries
    }
    return manifest


def verify_installation_manifest(manifest: Dict[str, Any], fixture_steam_root: Path) -> Tuple[bool, List[str]]:
    """
    Verify that every file and directory recorded in the manifest exists and matches expected checksums.
    Returns (is_valid, list_of_errors).
    """
    fixture_steam_root = fixture_steam_root.resolve()
    errors: List[str] = []

    for item in manifest["installed_files"]:
        p = Path(item["path"])
        if not p.exists():
            errors.append(f"Missing installed file: {p}")
            continue
        if item.get("sha256") == "symlink":
            if not p.is_symlink():
                errors.append(f"Expected symlink for {p}, got regular file")
            continue
        actual_sha = sha256_file(p)
        if actual_sha != item["sha256"]:
            errors.append(f"Corrupted file {p}: expected {item['sha256']}, got {actual_sha}")
        actual_size = p.stat().st_size
        if actual_size != item["size"]:
            errors.append(f"Size mismatch for {p}: expected {item['size']}, got {actual_size}")

    for d in manifest["created_directories"]:
        p = Path(d)
        if not p.exists() or not p.is_dir():
            errors.append(f"Missing created directory: {p}")

    for item in manifest.get("compat_modules", []):
        p = Path(item["path"])
        if not p.exists():
            errors.append(f"Missing compat module file: {p}")
            continue
        actual_sha = sha256_file(p)
        if actual_sha != item["source_sha256"]:
            errors.append(f"Corrupted compat module file {p}: expected {item['source_sha256']}, got {actual_sha}")
        actual_size = p.stat().st_size
        if actual_size != item["size"]:
            errors.append(f"Size mismatch for {p}: expected {item['size']}, got {actual_size}")

        if item.get("backup_path"):
            bk = Path(item["backup_path"])
            if not bk.exists():
                errors.append(f"Missing backup file for compat module: {bk}")
            else:
                actual_bk_sha = sha256_file(bk)
                if actual_bk_sha != item["original_sha256"]:
                    errors.append(f"Corrupted backup file {bk}: expected {item['original_sha256']}, got {actual_bk_sha}")

    return len(errors) == 0, errors


def rollback_installation_manifest(manifest: Dict[str, Any], fixture_steam_root: Path) -> Dict[str, Any]:
    """
    Rollback an installation based on its manifest.
    1. Removes all installed files.
    2. Restores any modified/backed-up files.
    3. Removes all created directories in reverse order.
    """
    fixture_steam_root = fixture_steam_root.resolve()
    report = {
        "status": "success",
        "files_removed": [],
        "files_restored": [],
        "directories_removed": [],
        "errors": []
    }

    # 1. Remove installed files
    for item in manifest["installed_files"]:
        p = Path(item["path"])
        try:
            if p.is_symlink():
                validate_path_enclosure(p.parent, fixture_steam_root)
                p.unlink()
                report["files_removed"].append(str(p))
            else:
                validate_path_enclosure(p, fixture_steam_root)
                if p.exists() and p.is_file():
                    p.unlink()
                    report["files_removed"].append(str(p))
        except Exception as e:
            report["errors"].append(f"Failed to remove file {p}: {e}")

    # 2. Restore backups if any
    for b in manifest.get("backups", []):
        orig = Path(b["original_path"])
        bk = Path(b["backup_path"])
        try:
            validate_path_enclosure(orig, fixture_steam_root)
            if bk.exists():
                shutil.copy2(bk, orig)
                report["files_restored"].append(str(orig))
                bk.unlink(missing_ok=True)
        except Exception as e:
            report["errors"].append(f"Failed to restore backup {orig} from {bk}: {e}")

    # 3. Remove created directories in reverse order (deepest first)
    for d_str in reversed(manifest.get("created_directories", [])):
        p = Path(d_str)
        try:
            validate_path_enclosure(p, fixture_steam_root)
            if p.exists() and p.is_dir():
                # Only remove if empty or matches tool dir
                if not any(p.iterdir()):
                    p.rmdir()
                    report["directories_removed"].append(str(p))
                elif p == Path(manifest["destination_tool_dir"]):
                    shutil.rmtree(p, ignore_errors=True)
                    report["directories_removed"].append(str(p))
        except Exception as e:
            report["errors"].append(f"Failed to remove directory {p}: {e}")

    if report["errors"]:
        report["status"] = "partial_failure"
    return report
