#!/bin/sh
set -eu
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
LAB="$(CDPATH= cd -- "$DIR/../.." && pwd)"
python3 -I "$DIR/generate.py"
/opt/homebrew/Cellar/llvm@21/21.1.8/bin/llvm-lib /def:"$DIR/kernel32.def" /machine:x64 /out:"$DIR/kernel32-x64.lib"
/usr/bin/clang -target x86_64-windows -c -O2 -ffreestanding -fno-builtin -I "$LAB/sources/wine-v3-vulkan-build/vulkan_headers/include" -I "$DIR/shaders" "$DIR/vk_throughput_x64.c" -o "$DIR/vk_throughput_x64.obj"
/opt/homebrew/Cellar/lld@21/21.1.8_1/bin/lld-link /entry:main /subsystem:console /nodefaultlib "$DIR/kernel32-x64.lib" "$DIR/vk_throughput_x64.obj" /out:"$DIR/vk_throughput_x64.exe"
file "$DIR/vk_throughput_x64.exe"
shasum -a 256 "$DIR/vk_throughput_x64.exe"
