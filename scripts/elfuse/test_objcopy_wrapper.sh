#!/usr/bin/env bash
set -euo pipefail

OBJCOPY="/Users/mewcapoo/Projects/proton-macos-lab/tools/elfuse/bin/objcopy"
SHIM_O="/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse/build/shim.o"
OUT_BIN="/Users/mewcapoo/Projects/proton-macos-lab/tools/elfuse/test_extracted.bin"
DD_BIN="/Users/mewcapoo/Projects/proton-macos-lab/tools/elfuse/test_dd.bin"

# 1. Parse otool offset and size
line_size=$(otool -l "$SHIM_O" | awk '/sectname __text/{found=1} found && /size/{print $2; exit}')
line_off=$(otool -l "$SHIM_O" | awk '/sectname __text/{found=1} found && /offset/{print $2; exit}')
dec_size=$(printf "%d" "$line_size")
dec_off=$(printf "%d" "$line_off")

echo "otool: sectname __text offset=$dec_off (hex $line_off) size=$dec_size (hex $line_size)"

# 2. Extract using tools/elfuse/bin/objcopy
"$OBJCOPY" -O binary "$SHIM_O" "$OUT_BIN"
wrapper_size=$(stat -f "%z" "$OUT_BIN")
echo "wrapper output size=$wrapper_size"

if [ "$dec_size" -ne "$wrapper_size" ]; then
    echo "ERROR: Size mismatch! otool=$dec_size vs wrapper=$wrapper_size"
    exit 1
fi

# 3. Direct dd comparison
dd if="$SHIM_O" of="$DD_BIN" bs=1 skip="$dec_off" count="$dec_size" 2>/dev/null
if cmp -s "$OUT_BIN" "$DD_BIN"; then
    echo "SUCCESS: wrapper extraction byte-for-byte matches dd otool offset!"
else
    echo "ERROR: byte content mismatch between wrapper and dd!"
    exit 1
fi

# 4. Negative test: corrupted file fails explicitly
printf "corrupted" > /tmp/test_bad_macho.o
if "$OBJCOPY" -O binary /tmp/test_bad_macho.o /tmp/bad.bin 2>/dev/null; then
    echo "ERROR: Corrupted file was expected to fail!"
    exit 1
else
    echo "SUCCESS: Negative test properly rejected bad input."
fi

rm -f "$OUT_BIN" "$DD_BIN" /tmp/test_bad_macho.o /tmp/bad.bin
