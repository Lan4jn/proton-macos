#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam Compatibility Tool Probe Adapter (Offline Research Tool)

Records invocation time, sanitized argv, cwd, and strictly whitelisted Steam environment
variables to an exclusively created JSON file without overwriting.
Never executes target games and never accesses the network.

Redaction scope:
Performs best-effort pattern-based redaction for common authorization headers (Authorization,
Cookie, X-Api-Key, etc.), common tokens and keys (including camelCase and percent-encoded keys),
passwords, tickets, and userinfo/query/fragment parameters in URLs. Does not guarantee
complete NLP-based redaction of arbitrary free-form text.
"""

import datetime
import json
import os
import re
import sys
import urllib.parse
import uuid
from pathlib import Path

# Sensitive keyword stems used for argument redaction
SENSITIVE_KEY_STEMS = {
    "token",
    "ticket",
    "cookie",
    "password",
    "passwd",
    "auth",
    "secret",
    "credential",
}

# Standalone flags whose next argument is treated as sensitive credential value
SENSITIVE_VALUE_FLAGS = {
    "--token",
    "-token",
    "--password",
    "-password",
    "--auth",
    "-auth",
    "--auth-ticket",
    "-auth-ticket",
    "--ticket",
    "-ticket",
    "--secret",
    "-secret",
    "--api-key",
    "-api-key",
    "--credential",
    "-credential",
    "--session-ticket",
    "-session-ticket",
}

# Strictly whitelisted Steam runtime environment variables (safe metadata/paths only)
SAFE_STEAM_ENV_WHITELIST = {
    "STEAM_COMPAT_CLIENT_INSTALL_PATH",
    "STEAM_COMPAT_DATA_PATH",
    "STEAM_COMPAT_TOOL_PATHS",
    "STEAM_COMPAT_TOOL_PATH",
    "STEAM_COMPAT_LIBRARY_PATHS",
    "STEAM_COMPAT_MOUNTS",
    "STEAM_COMPAT_APP_ID",
    "STEAM_COMPAT_SESSION_ID",
    "STEAM_COMPAT_CONFIG",
    "STEAM_COMPAT_FLAGS",
    "STEAM_COMPAT_SHADERS_PATH",
    "STEAM_EXTRA_COMPAT_TOOLS_PATHS",
    "SteamAppId",
    "SteamGameId",
    "SteamUser",
    "SteamAppUser",
    "STEAM_RUNTIME",
    "STEAM_RUNTIME_LIBRARY_PATH",
    "STEAM_ZENITY",
    "STEAM_CLIENT_PID",
}


def is_sensitive_key(key_str: str) -> bool:
    """
    Check if a parameter or environment key contains sensitive keyword stems.
    Handles camelCase (e.g., accessToken), kebab-case, snake_case, and percent-encoded keys.
    """
    unquoted = urllib.parse.unquote(key_str)
    cleaned = unquoted.lstrip("-")
    # Convert camelCase to snake_case
    converted = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", cleaned).lower()
    parts = [p for p in re.split(r"[-_.:~+]", converted) if p]

    # Check for direct match in sensitive stems
    if any(p in SENSITIVE_KEY_STEMS for p in parts):
        return True

    # If 'key' appears, check whether it is compound with api, access, secret, priv, etc.
    if "key" in parts:
        sensitive_key_qualifiers = {"api", "access", "secret", "priv", "private", "token"}
        if len(parts) == 1 or any(q in parts for q in sensitive_key_qualifiers):
            return True

    return False


def sanitize_header(header_str: str) -> str:
    """
    Redact sensitive HTTP header values (e.g., Authorization, Cookie, X-Api-Key).
    """
    m = re.match(r"^([a-zA-Z0-9_-]+)\s*:\s*(.*)$", header_str)
    if m:
        hdr_name, hdr_val = m.group(1), m.group(2)
        if is_sensitive_key(hdr_name) or hdr_name.lower() in ("authorization", "proxy-authorization", "cookie"):
            bearer_m = re.match(r"^(Bearer|Basic)\s+(.*)$", hdr_val, re.IGNORECASE)
            if bearer_m:
                return f"{hdr_name}: {bearer_m.group(1)} [REDACTED]"
            return f"{hdr_name}: [REDACTED]"
    return header_str


def sanitize_url(url_str: str) -> str:
    """
    Redact username/password userinfo and sensitive query/fragment parameters in URLs.
    """
    # 1. Redact complete userinfo (both username and password)
    redacted = re.sub(
        r"(https?://)([^@/\s]+)@",
        r"\1[REDACTED]@",
        url_str,
    )

    # 2. Redact sensitive key-value pairs in query strings and URL fragments
    def replace_kv(match):
        prefix = match.group(1)
        key = match.group(2)
        eq = match.group(3)
        val = match.group(4)
        if is_sensitive_key(key):
            return f"{prefix}{key}{eq}[REDACTED]"
        return match.group(0)

    redacted = re.sub(
        r"([?&#;])([a-zA-Z0-9_.~%+-]+)(=)([^&#\s]*)",
        replace_kv,
        redacted,
    )
    return redacted


def sanitize_argv(argv: list) -> list:
    """
    Sanitize command-line arguments:
    - Redacts key=value pairs where key is sensitive
    - Redacts values following sensitive flags (e.g., --password secret, --auth -secret)
    - Redacts HTTP headers passed directly or via -H/--header
    - Redacts URLs containing credentials, userinfo, query, or fragment tokens
    - Preserves Unicode (Chinese) and spaces in non-sensitive arguments completely
    """
    sanitized = []
    i = 0
    while i < len(argv):
        arg = argv[i]

        # Check for -H or --header
        if arg in ("-H", "--header"):
            sanitized.append(arg)
            if i + 1 < len(argv):
                sanitized.append(sanitize_header(argv[i + 1]))
                i += 2
                continue
            i += 1
            continue

        # Check for standalone HTTP headers like "Authorization: Bearer xyz"
        if ":" in arg and not arg.startswith("http://") and not arg.startswith("https://"):
            sanitized_hdr = sanitize_header(arg)
            if sanitized_hdr != arg:
                sanitized.append(sanitized_hdr)
                i += 1
                continue

        # Check for URL
        if arg.startswith("http://") or arg.startswith("https://"):
            sanitized.append(sanitize_url(arg))
            i += 1
            continue

        # Check for key=value arguments
        if "=" in arg:
            key, val = arg.split("=", 1)
            if is_sensitive_key(key):
                sanitized.append(f"{key}=[REDACTED]")
            else:
                if val.startswith("http://") or val.startswith("https://"):
                    sanitized.append(f"{key}={sanitize_url(val)}")
                else:
                    sanitized.append(arg)
            i += 1
            continue

        # Check for standalone sensitive flag followed by credential value
        if arg in SENSITIVE_VALUE_FLAGS or is_sensitive_key(arg):
            sanitized.append(arg)
            if i + 1 < len(argv):
                sanitized.append("[REDACTED]")
                i += 2
                continue
            i += 1
            continue

        # Normal argument (preserves Chinese characters and spaces intact)
        sanitized.append(arg)
        i += 1

    return sanitized


def filter_env(env: dict) -> dict:
    """
    Strictly whitelist Steam environment variables:
    - Only known safe Steam variables are included
    - Excludes full system env (PATH, USER, HOME, etc.)
    - Excludes any sensitive Steam variables (tokens, tickets, cookies, passwords, auth headers)
    """
    filtered = {}
    for key, val in env.items():
        if key in SAFE_STEAM_ENV_WHITELIST:
            if not is_sensitive_key(key):
                filtered[key] = val
    return filtered


def parse_cli_args(args: list):
    """
    Parse command-line arguments to extract --log-dir and remaining argv.
    Supports '--' delimiter: arguments following '--' are treated purely as game argv,
    protecting any game-level '--log-dir' options from being consumed.
    Returns (log_dir, remaining_argv).
    """
    log_dir = None
    remaining = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            # End of probe CLI options; all subsequent arguments belong to the game
            remaining.extend(args[i + 1:])
            break
        elif arg == "--log-dir":
            if i + 1 >= len(args):
                sys.stderr.write("Error: --log-dir requires a directory path argument.\n")
                sys.exit(1)
            log_dir = args[i + 1]
            i += 2
        elif arg.startswith("--log-dir="):
            log_dir = arg.split("=", 1)[1]
            i += 1
        else:
            remaining.append(arg)
            i += 1
    return log_dir, remaining


def write_probe_log(log_dir: str, argv: list, env: dict, cwd: str) -> str:
    """
    Exclusively create a probe JSON log file without overwriting.
    Uses 0600 file permissions for defense-in-depth security.
    Returns the created log file path.
    """
    dir_path = Path(log_dir).resolve()
    if not dir_path.exists():
        sys.stderr.write(f"Error: Log directory does not exist: {log_dir}\n")
        sys.exit(1)
    if not dir_path.is_dir():
        sys.stderr.write(f"Error: Log path is not a directory: {log_dir}\n")
        sys.exit(1)

    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp_str = now.isoformat()
    filename_ts = now.strftime("%Y%m%d-%H%M%S-%f")
    pid = os.getpid()
    rnd = uuid.uuid4().hex[:8]

    filename = f"probe-{filename_ts}-{pid}-{rnd}.json"
    filepath = dir_path / filename

    data = {
        "timestamp": timestamp_str,
        "pid": pid,
        "cwd": cwd,
        "argv": sanitize_argv(argv),
        "env": filter_env(env),
    }

    json_bytes = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    # Exclusive file creation: O_CREAT | O_EXCL prevents overwriting
    # Mode 0o600 restricts read/write permissions to owner only
    try:
        fd = os.open(str(filepath), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as e:
        sys.stderr.write(f"Error: Failed to exclusively create log file {filepath}: {e}\n")
        sys.exit(1)

    try:
        with open(fd, "wb", closefd=True) as f:
            f.write(json_bytes)
    except Exception as e:
        sys.stderr.write(f"Error: Failed to write log data to {filepath}: {e}\n")
        sys.exit(1)

    return str(filepath)


def main():
    raw_args = sys.argv[1:]
    log_dir, remaining_argv = parse_cli_args(raw_args)

    if not log_dir:
        sys.stderr.write("Error: --log-dir is required.\n")
        sys.exit(1)

    created_file = write_probe_log(
        log_dir=log_dir,
        argv=remaining_argv,
        env=dict(os.environ),
        cwd=os.getcwd(),
    )

    sys.stdout.write(f"Probe recorded: {created_file}\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
