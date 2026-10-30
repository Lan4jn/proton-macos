#!/bin/sh
set -eu
cd "$(dirname "$0")"
LLVM=/opt/homebrew/Cellar/llvm@21/21.1.8/bin
LAB=/Users/mewcapoo/Projects/proton-macos-lab
RT="$LAB/sources/elfuse-once-panorama2-derived/build/elfuse"
for stage in vert frag; do
 "$RT" --user 501:20 --sysroot "$LAB/fixtures/runtime/arch-case" --timeout 15 "$LAB/fixtures/runtime/arch-case/usr/bin/spirv-val" --target-env vulkan1.0 "$PWD/shaders/triangle.$stage.spv"
done
"$LLVM/llvm-dlltool" -m i386:x86-64 -d kernel32.def -l kernel32-x64.lib
clang -target x86_64-pc-windows-msvc -c -O2 -fno-builtin -I "$LAB/sources/wine-v3-vulkan-build/vulkan_headers/include" -I shaders vk_offscreen_x64.c -o vk_offscreen_x64.obj
/opt/homebrew/Cellar/lld@21/21.1.8_1/bin/lld-link /machine:x64 /entry:main /subsystem:console kernel32-x64.lib vk_offscreen_x64.obj /out:vk_offscreen_x64.exe
file vk_offscreen_x64.exe
shasum -a 256 vk_offscreen_x64.exe shaders/*.spv
