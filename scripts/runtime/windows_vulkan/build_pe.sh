#!/usr/bin/env bash
# scripts/runtime/windows_vulkan/build_pe.sh
#
# Compiles minimal Windows x64 console PE for Vulkan device enumeration.
# Targets x86_64-pc-windows-msvc using host clang + lld-link.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
SRC_DIR="${LAB_ROOT}/fixtures/runtime/windows-vulkan"

DLLTOOL=""
for p in /opt/homebrew/Cellar/llvm@21/*/bin/llvm-dlltool /opt/homebrew/Cellar/llvm@22/*/bin/llvm-dlltool /opt/homebrew/opt/llvm/bin/llvm-dlltool llvm-dlltool; do
    if [[ -x "$p" ]] || which "$p" >/dev/null 2>&1; then
        DLLTOOL="$p"
        break
    fi
done

LLDLINK=""
for p in /opt/homebrew/Cellar/lld@21/*/bin/lld-link /opt/homebrew/Cellar/lld@22/*/bin/lld-link /opt/homebrew/opt/lld/bin/lld-link lld-link; do
    if [[ -x "$p" ]] || which "$p" >/dev/null 2>&1; then
        LLDLINK="$p"
        break
    fi
done

if [[ -z "${DLLTOOL}" || -z "${LLDLINK}" ]]; then
    echo "[ERROR] Could not find llvm-dlltool or lld-link on host!" >&2
    exit 1
fi

echo "[INFO] Using DLLTOOL: ${DLLTOOL}"
echo "[INFO] Using LLDLINK: ${LLDLINK}"

cd "${SRC_DIR}"

echo "[INFO] Generating kernel32-x64.lib from kernel32.def..."
"${DLLTOOL}" -m i386:x86-64 -d kernel32.def -l kernel32-x64.lib

echo "[INFO] Compiling vk_enum_x64.c via clang..."
clang -target x86_64-pc-windows-msvc \
      -O2 -c vk_enum_x64.c -o vk_enum_x64.obj

echo "[INFO] Linking vk_enum_x64.exe via lld-link..."
"${LLDLINK}" /entry:mainCRTStartup \
            /subsystem:console \
            /nodefaultlib \
            vk_enum_x64.obj \
            kernel32-x64.lib \
            /out:vk_enum_x64.exe

echo "[INFO] Verifying generated executable..."
file vk_enum_x64.exe
shasum -a 256 vk_enum_x64.exe
echo "[SUCCESS] Built ${SRC_DIR}/vk_enum_x64.exe"
