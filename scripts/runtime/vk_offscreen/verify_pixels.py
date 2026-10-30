#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/runtime/vk_offscreen/verify_pixels.py

Pixel validation module for Vulkan offscreen triangle rendering (task-135).
Performs multi-point sampling for:
1. Interior triangle pixels (Red: R>=240, G<=15, B<=15, A>=240)
2. Exterior background pixels (Dark Blue: R<=15, G<=15, 115<=B<=140, A>=240)
Also provides negative testing to guarantee that clear-only or corrupted images fail validation.
"""

import sys
import hashlib
from typing import Tuple, Dict, Any, List

FB_WIDTH = 64
FB_HEIGHT = 64
FB_CHANNELS = 4
EXPECTED_SIZE = FB_WIDTH * FB_HEIGHT * FB_CHANNELS  # 16384 bytes

INTERIOR_SAMPLE_POINTS = [
    (32, 38, "Centroid (0.0, 0.2)"),
    (32, 25, "Top Center (0.0, -0.2)"),
    (22, 44, "Lower Left (-0.3, 0.4)"),
    (42, 44, "Lower Right (0.3, 0.4)")
]

EXTERIOR_SAMPLE_POINTS = [
    (5, 5, "Top Left Corner"),
    (58, 5, "Top Right Corner"),
    (5, 58, "Bottom Left Corner"),
    (58, 58, "Bottom Right Corner")
]


def verify_framebuffer(raw_bytes: bytes) -> Tuple[bool, Dict[str, Any]]:
    results = {
        "byte_length": len(raw_bytes),
        "expected_length": EXPECTED_SIZE,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "interior_samples": [],
        "exterior_samples": [],
        "errors": []
    }

    if len(raw_bytes) != EXPECTED_SIZE:
        results["errors"].append(f"Invalid framebuffer byte length: expected {EXPECTED_SIZE}, got {len(raw_bytes)}")
        return False, results

    # Verify interior points (Triangle = Red: 255, 0, 0, 255)
    for x, y, desc in INTERIOR_SAMPLE_POINTS:
        idx = (y * FB_WIDTH + x) * FB_CHANNELS
        r, g, b, a = raw_bytes[idx : idx + 4]
        is_red = (r >= 240 and g <= 15 and b <= 15 and a >= 240)
        sample = {
            "point": [x, y],
            "description": desc,
            "rgba": [r, g, b, a],
            "expected": "Triangle Red (~255, 0, 0, 255)",
            "matched": is_red
        }
        results["interior_samples"].append(sample)
        if not is_red:
            results["errors"].append(f"Interior point {desc} at ({x},{y}) failed: observed RGBA=({r},{g},{b},{a}), expected Red")

    # Verify exterior points (Background = Dark Blue: 0, 0, 128, 255)
    for x, y, desc in EXTERIOR_SAMPLE_POINTS:
        idx = (y * FB_WIDTH + x) * FB_CHANNELS
        r, g, b, a = raw_bytes[idx : idx + 4]
        is_blue = (r <= 15 and g <= 15 and 115 <= b <= 140 and a >= 240)
        sample = {
            "point": [x, y],
            "description": desc,
            "rgba": [r, g, b, a],
            "expected": "Background Dark Blue (~0, 0, 128, 255)",
            "matched": is_blue
        }
        results["exterior_samples"].append(sample)
        if not is_blue:
            results["errors"].append(f"Exterior point {desc} at ({x},{y}) failed: observed RGBA=({r},{g},{b},{a}), expected Dark Blue")

    is_valid = len(results["errors"]) == 0
    return is_valid, results


def run_negative_tests() -> Dict[str, Any]:
    """Execute RED negative tests against artificial clear-only or corrupted framebuffers."""
    neg_results = {"all_passed": True, "cases": []}

    # Negative Case 1: Clear-only buffer (draw skipped, all pixels are dark blue)
    clear_only_bytes = bytearray([0, 0, 128, 255] * (FB_WIDTH * FB_HEIGHT))
    valid1, details1 = verify_framebuffer(bytes(clear_only_bytes))
    caught1 = (not valid1) and any("Interior point" in e for e in details1["errors"])
    neg_results["cases"].append({
        "case": "skip_draw_clear_only_buffer",
        "expected_valid": False,
        "actual_valid": valid1,
        "caught_errors": details1["errors"],
        "test_passed": caught1
    })
    if not caught1:
        neg_results["all_passed"] = False

    # Negative Case 2: Wrong color inside triangle (e.g. green instead of red)
    wrong_color_bytes = bytearray([0, 0, 128, 255] * (FB_WIDTH * FB_HEIGHT))
    for x, y, _ in INTERIOR_SAMPLE_POINTS:
        idx = (y * FB_WIDTH + x) * FB_CHANNELS
        wrong_color_bytes[idx:idx+4] = bytes([0, 255, 0, 255])
    valid2, details2 = verify_framebuffer(bytes(wrong_color_bytes))
    caught2 = (not valid2) and any("Interior point" in e for e in details2["errors"])
    neg_results["cases"].append({
        "case": "wrong_triangle_color_green",
        "expected_valid": False,
        "actual_valid": valid2,
        "caught_errors": details2["errors"],
        "test_passed": caught2
    })
    if not caught2:
        neg_results["all_passed"] = False

    # Negative Case 3: Truncated buffer
    valid3, details3 = verify_framebuffer(b"\x00" * 1024)
    caught3 = (not valid3) and any("length" in e for e in details3["errors"])
    neg_results["cases"].append({
        "case": "truncated_framebuffer",
        "expected_valid": False,
        "actual_valid": valid3,
        "caught_errors": details3["errors"],
        "test_passed": caught3
    })
    if not caught3:
        neg_results["all_passed"] = False

    return neg_results


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as f:
            data = f.read()
        valid, det = verify_framebuffer(data)
        print(f"Validation: {valid}")
        for err in det["errors"]:
            print(f"  Error: {err}")
        sys.exit(0 if valid else 1)
    else:
        neg = run_negative_tests()
        print(f"Negative tests passed: {neg['all_passed']}")
        sys.exit(0 if neg["all_passed"] else 1)
