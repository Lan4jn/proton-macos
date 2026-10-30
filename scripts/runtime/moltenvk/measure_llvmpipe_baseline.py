#!/usr/bin/env python3
import json
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab")

def main():
    baseline_data = {
        "device_architecture": "CPU Software Rasterizer",
        "driver_name": "lavapipe / llvmpipe",
        "llvm_version": "LLVM 23.1.1, 128 bits",
        "vulkan_api_version": "1.4.354",
        "physical_devices_enumerated": 1,
        "device_name": "llvmpipe (LLVM 23.1.1, 128 bits)",
        "device_type": "VK_PHYSICAL_DEVICE_TYPE_CPU (4)",
        "measured_latencies": {
            "total_process_elapsed_seconds": 48.18,
            "wine_prefix_bootstrap_overhead_seconds": 41.99,
            "vulkan_instance_creation_overall_seconds": 6.179,
            "vulkan_instance_creation_components": "Covers dlopen of libvulkan_lvp.so, Mesa core initialization, LLVM compiler subsystem setup, and ICD extension queries (cannot be asserted solely as LLVM JIT compilation).",
            "device_enumeration_and_property_query_ms": "< 1 ms (timestamps 1578617.771 to 1578617.771 at 1ms logger resolution)",
            "instance_destruction_and_teardown_ms": 13.0,
            "instance_destruction_timestamps": "1578617.771 to 1578617.784 (exact difference: 13 ms)"
        },
        "rendering_throughput_status": {
            "fps_measurement": "UNMEASURED (Current probe vk_enum_arm64.exe performs only device discovery and property queries; no swapchain, render pass, or draw calls were issued).",
            "missing_for_throughput": "Requires an extended rendering workload probe (such as vkcube, a minimal triangle render pass, or compute shader dispatch) to measure frames per second or compute GFLOPS.",
            "theoretical_ceiling_note": "As a CPU software rasterizer, throughput is fundamentally bound by CPU vector width (128-bit NEON) and core count; complex 3D rasterization fill-rate will be significantly lower than hardware GPU."
        }
    }

    out_file = LAB / "logs/moltenvk/llvmpipe_baseline.json"
    out_file.write_text(json.dumps(baseline_data, indent=2) + "\n")
    print(f"Wrote updated baseline to {out_file}")

if __name__ == "__main__":
    main()
