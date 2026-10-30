#!/bin/sh
set -eu
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
LLVM=/opt/homebrew/Cellar/llvm@21/21.1.8/bin
"$LLVM/llvm-lib" /def:"$DIR/kernel32.def" /machine:x64 /out:"$DIR/kernel32-x64.lib"
clang -target x86_64-windows -O2 -ffreestanding -fno-builtin -c "$DIR/window_x64.c" -o "$DIR/window_x64.obj"
/opt/homebrew/Cellar/lld@21/21.1.8_1/bin/lld-link /entry:mainCRTStartup /subsystem:console /nodefaultlib /out:"$DIR/window_x64.exe" "$DIR/window_x64.obj" "$DIR/kernel32-x64.lib"
file "$DIR/window_x64.exe"
shasum -a 256 "$DIR/window_x64.exe"
