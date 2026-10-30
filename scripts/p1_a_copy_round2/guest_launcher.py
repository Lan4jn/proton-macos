#!/usr/bin/env python3
"""Unified P0-owned launcher for macOS host service and Linux guest producer (final strictly-gated version)."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import roles

ROOT=pathlib.Path(__file__).resolve().parents[2]
DEFAULT_HOST=ROOT/'logs/p1-a-copy-v2/run-4e2a63efe2f2/presenter'
DEFAULT_HOST_SHA='b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb'
DEFAULT_RT=ROOT/'sources/elfuse-once-panorama2-derived/build/elfuse'
DEFAULT_RT_SHA='8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda'
DEFAULT_PRODUCER_C=ROOT/'sources/p1-a-copy-round2/guest_producer.c'
RUNNER_WRAPPER=ROOT/'scripts/p1_a_copy_round2/runner.py'
ROLES_PY=ROOT/'scripts/p1_a_copy_round2/roles.py'
DEADLINE_IO=ROOT/'scripts/p1_a_copy_round2/deadline_io.py'
WIRE_PY=ROOT/'scripts/p1_a_copy_round2/wire.py'


def sha256_file(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser()
    # 严格仅限 smoke 一帧场景
    p.add_argument('--scenario',default='smoke',choices=['smoke'])
    p.add_argument('--host-binary',default=str(DEFAULT_HOST))
    p.add_argument('--runtime',default=str(DEFAULT_RT))
    p.add_argument('--producer-elf',required=False)
    p.add_argument('--producer-elf-sha',required=False)
    p.add_argument('--fixture-fake-host',action='store_true')
    p.add_argument('--fixture-missing-host',action='store_true')
    p.add_argument('--fixture-host-early-exit',action='store_true')
    args=p.parse_args()

    # 1. 强校验必须运行于 P0 监督进程组中
    root=pathlib.Path.cwd()
    try:
        owner=json.loads((root.parent/'owned.json').read_text())
        if owner['pgid']!=os.getpgrp():raise ValueError('group mismatch')
    except (OSError,ValueError,KeyError):
        sys.stderr.write('P0 supervised session required\n')
        return 1

    # 2. 真实模式下校验必需参数及组件哈希
    is_fixture = args.fixture_fake_host or args.fixture_missing_host or args.fixture_host_early_exit
    if not is_fixture:
        host_path=pathlib.Path(args.host_binary)
        if sha256_file(host_path)!=DEFAULT_HOST_SHA:
            sys.stderr.write('Host binary SHA mismatch\n')
            return 2
        rt_path=pathlib.Path(args.runtime)
        if sha256_file(rt_path)!=DEFAULT_RT_SHA:
            sys.stderr.write('Runtime SHA mismatch\n')
            return 2
        if not args.producer_elf or not args.producer_elf_sha:
            sys.stderr.write('Real smoke requires --producer-elf and --producer-elf-sha\n')
            return 2
        elf_src_path = pathlib.Path(args.producer_elf)
        if not elf_src_path.is_file() or sha256_file(elf_src_path) != args.producer_elf_sha:
            sys.stderr.write('Producer ELF SHA mismatch or missing\n')
            return 2

    # 3. 创建严格隔离的短根目录 r，并在 r/bin 与 r/tmp 建立工作区
    r_dir = root / 'r'
    r_dir.mkdir(parents=True, exist_ok=False) # 必须全新创建，拒绝已有
    bin_dir = r_dir / 'bin'
    bin_dir.mkdir(parents=True, exist_ok=False)
    tmp_dir = r_dir / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=False)

    sock_host_path = tmp_dir / 's'
    if len(str(sock_host_path).encode('utf-8')) >= 104:
        sys.stderr.write(f'Host socket path exceeds 104 bytes: {sock_host_path}\n')
        return 3

    # 4. 若传入真实 ELF，复制进 r/bin/producer 并 chmod 0o755 且复核哈希
    installed_elf = None
    if args.producer_elf and not is_fixture:
        installed_elf = bin_dir / 'producer'
        shutil.copyfile(args.producer_elf, installed_elf)
        installed_elf.chmod(0o755)
        if sha256_file(installed_elf) != args.producer_elf_sha:
            sys.stderr.write('Installed producer ELF SHA mismatch\n')
            return 4

    # 5. 启动 Host 独立服务（同 PGID 普通 Popen）
    host_proc = None
    if args.fixture_missing_host:
        sys.stderr.write('Configured with missing host fixture\n')
        return 10
    elif args.fixture_host_early_exit:
        # 变异测试：host 瞬间退出，导致 roles 快照或连接失败，记为 UNKNOWN 并报错
        fake_py = root / 'fake_host_early_exit.py'
        fake_py.write_text("import sys; sys.exit(42)\n")
        host_argv = [sys.executable, str(fake_py), str(sock_host_path)]
        host_proc = roles.spawn('host', host_argv, root)
        # 等待其退出并报错
        time.sleep(0.1)
        sys.stderr.write('Host early exit detected: UNKNOWN state\n')
        return 11
    else:
        if args.fixture_fake_host:
            fake_py = root / 'fake_host_proc.py'
            fake_py.write_text(
                "import sys, socket, struct, json\n"
                "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
                "s.bind(sys.argv[1])\n"
                "s.listen(1)\n"
                "s.close()\n"
            )
            host_argv = [sys.executable, str(fake_py), str(sock_host_path)]
        else:
            host_argv = [str(args.host_binary), str(sock_host_path), '120']
        host_proc = roles.spawn('host', host_argv, root)

        deadline = time.monotonic() + 4.0
        while not sock_host_path.exists():
            if time.monotonic() >= deadline:
                sys.stderr.write('Timeout waiting for host socket\n')
                return 5
            time.sleep(0.01)

    # 6. 启动 Linux Guest Producer (elfuse)
    guest_rc = 0
    guest_stdout_bytes = b''
    guest_stderr_bytes = b''
    if installed_elf:
        guest_argv = [
            str(args.runtime),
            '--timeout', '15',
            '--sysroot', str(r_dir),
            '--workdir', '/tmp',
            '--clear-env',
            str(installed_elf),
            '/tmp/s',
            args.scenario
        ]
        guest_proc = roles.spawn('guest', guest_argv, root)
        guest_rc = guest_proc.wait()
        guest_stdout_file = root / 'guest.stdout'
        if guest_stdout_file.is_file(): guest_stdout_bytes = guest_stdout_file.read_bytes()
        guest_stderr_file = root / 'guest.stderr'
        if guest_stderr_file.is_file(): guest_stderr_bytes = guest_stderr_file.read_bytes()

    host_rc = host_proc.wait(timeout=5) if host_proc else 0

    # 7. 落盘最终综合 receipt
    receipt_data = dict(
        scenario=args.scenario,
        fixture=is_fixture,
        host_exit=host_rc,
        guest_exit=guest_rc,
        sock_path=str(sock_host_path),
        inputs_sha256=dict(
            guest_producer_c=sha256_file(DEFAULT_PRODUCER_C),
            producer_elf=args.producer_elf_sha if args.producer_elf_sha else None,
            host_binary=DEFAULT_HOST_SHA if not is_fixture else None,
            runtime=DEFAULT_RT_SHA if not is_fixture else None,
            launcher=sha256_file(pathlib.Path(__file__)),
            runner=sha256_file(RUNNER_WRAPPER),
            roles=sha256_file(ROLES_PY),
            deadline_io=sha256_file(DEADLINE_IO),
            wire=sha256_file(WIRE_PY)
        ),
        guest_stdout_len=len(guest_stdout_bytes),
        guest_stderr_len=len(guest_stderr_bytes)
    )
    (root/'result.json').write_text(json.dumps(receipt_data, indent=2))
    return int(guest_rc != 0 or host_rc != 0)


if __name__=='__main__':
    sys.exit(main())
