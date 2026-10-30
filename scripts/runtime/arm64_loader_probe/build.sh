#!/bin/sh
set -eu
LAB=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
SRC="$LAB/fixtures/runtime/arm64-loader-probe"
OUT=${1:?Pass a fresh lab-local output directory; frozen outputs are not overwritten}
case "$OUT" in "$LAB"/*) ;; *) echo 'Output must be an absolute lab-local path' >&2; exit 2 ;; esac
[ ! -e "$OUT" ] || { echo 'Output already exists' >&2; exit 2; }
mkdir -p "$OUT"
/opt/homebrew/opt/llvm@22/bin/llvm-dlltool -m arm64 -d "$SRC/kernel32.def" -l "$OUT/kernel32-arm64.lib"
for mode in 0 1 2; do
    clang -target aarch64-pc-windows-msvc -fno-stack-protector -O2 -DMODE="$mode" -c "$SRC/probe.c" -o "$OUT/probe-$mode.obj"
    /opt/homebrew/opt/lld@21/bin/lld-link /machine:arm64 /entry:mainCRTStartup /subsystem:console /nodefaultlib "$OUT/probe-$mode.obj" "$OUT/kernel32-arm64.lib" "/out:$OUT/probe-$mode.exe"
done
file "$OUT"/*.exe
shasum -a 256 "$OUT"/*.exe
