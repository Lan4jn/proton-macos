#!/usr/bin/env python3
"""
scripts/runtime/vulkan_queue/test_pattern_classifier.py

Unit test for the 0x1234ABCD pattern verification classifier (pure function).
Verifies that:
- Clean 64 * 0x1234ABCD buffer passes as PATTERN_MATCH_OK
- Corrupted words at start, middle, end, or all-zero are classified as PATTERN_MISMATCH with exact index
- Size discrepancies are classified as SIZE_MISMATCH
"""

import struct
import sys

def verify_pattern(raw_bytes: bytes, expected_pattern: int = 0x1234ABCD, expected_bytes: int = 256):
    if len(raw_bytes) != expected_bytes:
        return False, "SIZE_MISMATCH", {
            "expected_len": expected_bytes,
            "actual_len": len(raw_bytes),
        }

    word_count = expected_bytes // 4
    words = struct.unpack(f"<{word_count}I", raw_bytes)
    mismatches = []
    for i, w in enumerate(words):
        if w != expected_pattern:
            mismatches.append({
                "word_index": i,
                "byte_offset": i * 4,
                "expected": hex(expected_pattern),
                "actual": hex(w),
            })
            if len(mismatches) >= 5:  # limit reports
                break

    if mismatches:
        return False, "PATTERN_MISMATCH", {
            "mismatch_count": len(mismatches),
            "first_mismatch": mismatches[0],
            "total_words": word_count,
        }

    return True, "PATTERN_MATCH_OK", {
        "total_words": word_count,
        "pattern": hex(expected_pattern),
    }

def run_tests():
    pattern = 0x1234ABCD
    expected_bytes = 256
    word_count = 64

    # 1. Clean buffer
    clean_buf = struct.pack(f"<{word_count}I", *([pattern] * word_count))
    ok, reason, details = verify_pattern(clean_buf, pattern, expected_bytes)
    assert ok is True and reason == "PATTERN_MATCH_OK", f"Clean test failed: {reason}"
    assert details["total_words"] == 64

    # 2. Corrupt word 0 (start)
    corrupt_start = struct.pack(f"<{word_count}I", 0, *([pattern] * (word_count - 1)))
    ok, reason, details = verify_pattern(corrupt_start, pattern, expected_bytes)
    assert ok is False and reason == "PATTERN_MISMATCH", "Corrupt start failed"
    assert details["first_mismatch"]["word_index"] == 0
    assert details["first_mismatch"]["actual"] == "0x0"

    # 3. Corrupt word 32 (middle)
    words = [pattern] * word_count
    words[32] = 0xDEADBEEF
    corrupt_mid = struct.pack(f"<{word_count}I", *words)
    ok, reason, details = verify_pattern(corrupt_mid, pattern, expected_bytes)
    assert ok is False and reason == "PATTERN_MISMATCH", "Corrupt middle failed"
    assert details["first_mismatch"]["word_index"] == 32
    assert details["first_mismatch"]["actual"] == "0xdeadbeef"

    # 4. Corrupt word 63 (end)
    words = [pattern] * word_count
    words[63] = 0xCAFEBABE
    corrupt_end = struct.pack(f"<{word_count}I", *words)
    ok, reason, details = verify_pattern(corrupt_end, pattern, expected_bytes)
    assert ok is False and reason == "PATTERN_MISMATCH", "Corrupt end failed"
    assert details["first_mismatch"]["word_index"] == 63
    assert details["first_mismatch"]["actual"] == "0xcafebabe"

    # 5. All zeros (uninitialized buffer)
    zero_buf = b"\x00" * expected_bytes
    ok, reason, details = verify_pattern(zero_buf, pattern, expected_bytes)
    assert ok is False and reason == "PATTERN_MISMATCH", "Zero buf failed"
    assert details["first_mismatch"]["word_index"] == 0

    # 6. Size mismatch
    short_buf = clean_buf[:128]
    ok, reason, details = verify_pattern(short_buf, pattern, expected_bytes)
    assert ok is False and reason == "SIZE_MISMATCH", "Short buf failed"

    print("ALL 6 PATTERN CLASSIFIER UNIT TESTS PASSED (NEGATIVE + POSITIVE)")

if __name__ == "__main__":
    run_tests()
