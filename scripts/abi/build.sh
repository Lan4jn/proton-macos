#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
F="$ROOT/fixtures/abi";L=/opt/homebrew/opt/lld@21/bin/ld.lld
mkdir -p "$F/bin"
for n in shared futex signal; do
 clang --target=aarch64-linux-gnu -ffreestanding -fno-stack-protector -fno-builtin -O1 -c "$F/$n.c" -o "$F/bin/$n.o"
 "$L" -e _start "$F/bin/$n.o" -o "$F/bin/$n"
done
clang --target=aarch64-linux-gnu -c "$F/start.S" -o "$F/bin/start.o"
for n in dynamic_hello spawn_missing; do
 clang --target=aarch64-linux-gnu -ffreestanding -fno-stack-protector -fno-builtin -O1 -c "$F/$n.c" -o "$F/bin/$n.o"
 "$L" -e _start --dynamic-linker /lib/ld-linux-aarch64.so.1 --allow-shlib-undefined "$F/bin/start.o" "$F/bin/$n.o" "$ROOT/fixtures/runtime/sysroot/lib/libc.so.6" -o "$F/bin/$n"
done
