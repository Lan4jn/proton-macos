#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Candidate VDF Generator for macOS Steam Compatibility Tool Probe

Generates concrete local candidate VDF files using real absolute paths to probe.py
and logs/steam, avoiding placeholder pseudo-variables.
Includes '-- %verb%' in toolmanifest commandline to preserve Steam verb while protecting
game-level arguments from option collisions.
These files are generated strictly for offline inspection and research.
DO NOT COPY TO STEAM WITHOUT EXPLICIT USER APPROVAL.
"""

import os
import sys
from pathlib import Path

# /Users/mewcapoo/Projects/proton-macos-lab
LAB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROBE_PY = (LAB_ROOT / "scripts" / "steam" / "probe.py").resolve()
LOG_DIR = (LAB_ROOT / "logs" / "steam").resolve()
CANDIDATE_DIR = (LAB_ROOT / "scripts" / "steam" / "candidate").resolve()


def format_vdf_arg(arg: str) -> str:
    """
    Format and escape an argument for inclusion in a VDF commandline string.
    If the argument contains spaces, tabs, or quotes, wrap it in escaped quotes (\ \"...\" ).
    """
    if " " in arg or '"' in arg or "\t" in arg:
        escaped = arg.replace('"', '\\"')
        return f'\\"{escaped}\\"'
    return arg


def generate_candidate_vdfs(
    output_dir: Path = None,
    python_exe: Path = None,
    probe_py: Path = None,
    log_dir: Path = None,
) -> dict:
    if output_dir is None:
        output_dir = CANDIDATE_DIR
    if python_exe is None:
        python_exe = Path(sys.executable).resolve()
    if probe_py is None:
        probe_py = PROBE_PY
    if log_dir is None:
        log_dir = LOG_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    compat_vdf_content = (
        '"compatibilitytools"\n'
        "{\n"
        '  "compat_tools"\n'
        "  {\n"
        '    "proton_macos_probe"\n'
        "    {\n"
        '      "install_path" "."\n'
        '      "display_name" "macOS Proton Probe (Offline Research Tool)"\n'
        '      "from_oslist"  "windows"\n'
        '      "to_oslist"    "macos"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )

    cmd_parts = [
        format_vdf_arg(str(python_exe)),
        format_vdf_arg(str(probe_py)),
        "--log-dir",
        format_vdf_arg(str(log_dir)),
        "--",
        "%verb%",
    ]
    commandline_str = " ".join(cmd_parts)

    manifest_vdf_content = (
        '"manifest"\n'
        "{\n"
        f'  "commandline" "{commandline_str}"\n'
        '  "version" "2"\n'
        '  "use_sessions" "1"\n'
        "}\n"
    )

    compat_path = output_dir / "compatibilitytool.vdf"
    manifest_path = output_dir / "toolmanifest.vdf"

    compat_path.write_text(compat_vdf_content, encoding="utf-8")
    manifest_path.write_text(manifest_vdf_content, encoding="utf-8")

    return {
        "compatibilitytool_vdf": str(compat_path),
        "toolmanifest_vdf": str(manifest_path),
        "commandline": commandline_str,
    }


def main():
    paths = generate_candidate_vdfs()
    print("Generated candidate VDF files with concrete absolute paths:")
    for k, v in paths.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
