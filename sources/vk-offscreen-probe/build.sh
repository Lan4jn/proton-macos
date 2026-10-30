#!/bin/sh
set -e
PROBE_DIR="$(cd "$(dirname "$0")" && pwd)"
LAB_DIR="$(cd "$PROBE_DIR/../.." && pwd)"

echo "=== 1. Assembling & Validating Shaders ==="
"$LAB_DIR/sources/elfuse-once-panorama2-derived/build/elfuse"   --user 501:20 --sysroot "$LAB_DIR/fixtures/runtime/arch-case"   "$LAB_DIR/fixtures/runtime/arch-case/usr/bin/spirv-as" --target-env vulkan1.0   "$PROBE_DIR/shaders/triangle.vert.spvasm" -o "$PROBE_DIR/shaders/triangle.vert.spv"

"$LAB_DIR/sources/elfuse-once-panorama2-derived/build/elfuse"   --user 501:20 --sysroot "$LAB_DIR/fixtures/runtime/arch-case"   "$LAB_DIR/fixtures/runtime/arch-case/usr/bin/spirv-val" --target-env vulkan1.0   "$PROBE_DIR/shaders/triangle.vert.spv"

"$LAB_DIR/sources/elfuse-once-panorama2-derived/build/elfuse"   --user 501:20 --sysroot "$LAB_DIR/fixtures/runtime/arch-case"   "$LAB_DIR/fixtures/runtime/arch-case/usr/bin/spirv-as" --target-env vulkan1.0   "$PROBE_DIR/shaders/triangle.frag.spvasm" -o "$PROBE_DIR/shaders/triangle.frag.spv"

"$LAB_DIR/sources/elfuse-once-panorama2-derived/build/elfuse"   --user 501:20 --sysroot "$LAB_DIR/fixtures/runtime/arch-case"   "$LAB_DIR/fixtures/runtime/arch-case/usr/bin/spirv-val" --target-env vulkan1.0   "$PROBE_DIR/shaders/triangle.frag.spv"

echo "=== 2. Compiling Windows ARM64 PE ==="
clang -target aarch64-windows -c -O2   -I "$LAB_DIR/sources/wine-v3-vulkan-build/vulkan_headers/include"   -I "$PROBE_DIR/shaders"   "$PROBE_DIR/vk_offscreen_arm64.c" -o "$PROBE_DIR/vk_offscreen_arm64.obj"

/opt/homebrew/Cellar/lld@21/21.1.8_1/bin/lld-link /entry:main /subsystem:console   "$PROBE_DIR/kernel32-arm64.lib"   "$PROBE_DIR/vk_offscreen_arm64.obj"   /out:"$PROBE_DIR/vk_offscreen_arm64.exe"

file "$PROBE_DIR/vk_offscreen_arm64.exe"
shasum -a 256 "$PROBE_DIR/vk_offscreen_arm64.exe"
