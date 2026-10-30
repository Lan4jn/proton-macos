#!/bin/sh
set -eu
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
LAB="$(CDPATH= cd -- "$DIR/../.." && pwd)"
LLVM=/opt/homebrew/Cellar/llvm@21/21.1.8/bin
LINK=/opt/homebrew/Cellar/lld@21/21.1.8_1/bin
/usr/bin/clang -target aarch64-linux-gnu -O2 -ffreestanding -fno-builtin -nostdlib -c "$DIR/guest.c" -o "$DIR/guest.o"
"$LINK/ld.lld" -static -e _start -o "$DIR/guest" "$DIR/guest.o"
python3 -I "$DIR/build_frame_probe.py"
"$LLVM/llvm-lib" /def:"$DIR/kernel32.def" /machine:arm64 /out:"$DIR/kernel32-arm64.lib"
/usr/bin/clang -target aarch64-windows -O2 -ffreestanding -fno-builtin -I "$LAB/sources/wine-v3-vulkan-build/vulkan_headers/include" -I "$DIR" -c "$DIR/frame_probe_arm64.c" -o "$DIR/frame_probe_arm64.obj"
"$LINK/lld-link" /entry:main /subsystem:console /nodefaultlib /base:0x30000000 /map:"$DIR/frame_probe.map" "$DIR/kernel32-arm64.lib" "$DIR/frame_probe_arm64.obj" /out:"$DIR/frame_probe_arm64.exe"
/usr/bin/clang -dynamiclib -fobjc-arc -O2 -Wall -Wextra -framework AppKit -framework QuartzCore "$DIR/present.m" -o "$DIR/present.dylib"
make -C "$LAB/sources/elfuse-inproc-present-derived" elfuse
file "$DIR/guest" "$DIR/frame_probe_arm64.exe" "$DIR/present.dylib" "$LAB/sources/elfuse-inproc-present-derived/build/elfuse"
shasum -a 256 "$DIR/guest" "$DIR/frame_probe_arm64.exe" "$DIR/present.dylib" "$LAB/sources/elfuse-inproc-present-derived/build/elfuse"
