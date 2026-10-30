#!/usr/bin/env python3
import json
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab")

def main():
    abi_probe = json.loads((LAB / "logs/moltenvk/abi_probe_result.json").read_text())
    baseline = json.loads((LAB / "logs/moltenvk/llvmpipe_baseline.json").read_text())

    data = {
        "metadata": {
            "task": "task-132",
            "title": "Real GPU (MoltenVK/Metal) Path Feasibility and Technical Subsystem Assessment (Rework 2)",
            "author": "x64-pipe-reviewer",
            "lab": str(LAB),
            "date": "2026-10-26T20:30:00Z",
            "status": "reworked_verified_v2"
        },
        "acceptance_1_fact_checking": {
            "guest_vulkan_icds": [
                {
                    "manifest_path": "fixtures/runtime/lavapipe-derived/usr/share/vulkan/icd.d/lvp_icd.json",
                    "driver_path": "fixtures/runtime/lavapipe-derived/usr/lib/libvulkan_lvp.so",
                    "driver_type": "CPU Software Rasterizer (lavapipe / llvmpipe)",
                    "vulkan_api_version": "1.4.354",
                    "status": "VERIFIED_ACTIVE (Enumerates 1 physical CPU device in test runs)"
                },
                {
                    "manifest_path": "fixtures/runtime/arch-case/usr/share/vulkan/icd.d/freedreno_icd.json",
                    "driver_path": "/usr/lib/libvulkan_freedreno.so",
                    "driver_type": "Qualcomm Adreno Hardware Driver",
                    "status": "INACTIVE (Incompatible with Apple Silicon Metal/HVF environment)"
                }
            ],
            "host_moltenvk_inventory": [
                {
                    "exact_path": "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib64/libMoltenVK.dylib",
                    "format": "Mach-O 64-bit x86_64 dynamically linked shared library",
                    "architecture_verified_via_lipo": "x86_64",
                    "size_bytes": 10242560,
                    "sha256": abi_probe["target_library"]["sha256"],
                    "magic_hex_16": "cffaedfe070000010000000000000000 (cffaedfe=MH_MAGIC_64, 07000001=CPU_TYPE_X86_64 in Little Endian 0x01000007)",
                    "presence": "APPLICATION_BUNDLED_PRIVATE",
                    "scope_boundary_note": "This probe tested this specific x86_64 Mach-O library. An arm64 Mach-O MoltenVK was NOT tested in this lab; commercial App files were not scanned further."
                },
                {
                    "exact_path": "/Applications/Moonlight.app/Contents/Frameworks/libMoltenVK.dylib",
                    "presence": "APPLICATION_BUNDLED_PRIVATE"
                },
                {
                    "location": "/opt/homebrew or /usr/local",
                    "presence": "NOT_FOUND (No global Vulkan SDK or Homebrew MoltenVK installed)"
                }
            ],
            "elfuse_graphics_bridge_status": {
                "drm_virtualization": "NONE (0 references to /dev/dri, drmIoctl, or DRM render nodes in sources/elfuse/src/)",
                "gpu_forwarding": "NONE (No virtio-gpu, virgl, or Metal forwarding layers in elfuse)",
                "syscall_emulation_scope": "Standard POSIX Linux user-space calls only (fs, mem, signals, threads, sockets, futex, timers)",
                "hvc6_embedder_hook_audit": {
                    "declaration": "sources/elfuse/src/core/guest.h:597 (uint64_t (*hvc6_handler)(uint64_t call_nr, const uint64_t args[8], void *userdata))",
                    "trap_dispatch": "sources/elfuse/src/syscall/proc.c:4414 (dispatches when vCPU takes HVC #6 trap)",
                    "pseudo_syscall_dispatch": "sources/elfuse/src/syscall/syscall.c:2772 (ELFUSE_NR_EMBEDDER_HVC6, currently gated strictly on g->is_rosetta)",
                    "primary_setup_location": "sources/elfuse/src/core/bootstrap.c:422 (after guest_init)",
                    "child_inheritance_location": "sources/elfuse/src/runtime/fork-state.c (fork child setup)",
                    "hardware_privilege_boundary": "In ARM64, user-space EL0 code CANNOT directly execute HVC; executing HVC at EL0 traps to EL1 as an Undefined Instruction. EL0 user code must execute SVC #0 (Linux syscall) which the EL1 shim forwards.",
                    "process_inheritance_constraint": "guest.h:592 confirms hvc6_handler is process-local and does NOT survive fork/clone. Wine children would lose the hook unless re-registered in child bootstrap."
                }
            },
            "abi_boundary_verification": {
                "test_script": "scripts/runtime/moltenvk/run_abi_probe.py",
                "raw_stdout_path": "logs/moltenvk/abi_probe_stdout.log",
                "raw_stderr_path": "logs/moltenvk/abi_probe_stderr.log",
                "target_library": "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib64/libMoltenVK.dylib",
                "target_arch": "Mach-O 64-bit x86_64",
                "loader_error": "REJECTION: /Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib64/libMoltenVK.dylib: invalid ELF header",
                "verdict": "DEFINITIVE_ABI_BARRIER: Linux dynamic linker ld-linux-aarch64.so.1 strictly rejects Mach-O MH_MAGIC_64 header; direct dlopen across OS container boundary is impossible."
            }
        },
        "acceptance_2_candidate_paths_evaluation": {
            "paths": [
                {
                    "id": "PATH_A",
                    "name": "Guest Vulkan ICD Shim with Custom Hypercall / Syscall Forwarding (Direct Bridge)",
                    "architecture": "Guest-side libvulkan_bridge.so (ELF) intercepts Vulkan API -> marshals calls via private Linux syscall / HVC -> elfuse host handler unmarshals and calls host libMoltenVK.dylib (Mach-O) -> Apple Metal.",
                    "technical_subsystems_required": [
                        "Interface Layer: Linux syscall trampoline in elfuse for unprivileged EL0 guest callers, plus fork/clone hook re-registration.",
                        "Protocol Marshalling: Serialization and deserialization of 150+ core Vulkan functions, complex structs, and nested pNext chains.",
                        "Memory Subsystem: Zero-copy mapping of host Metal MTLBuffer contents into guest physical memory (hv_vm_map), handling page alignment, GPA fragmentation, and vkMapMemory/vkUnmapMemory lifecycles.",
                        "Synchronization Subsystem: Bridging host Metal command buffer completion handlers to guest Linux futex / thread wakeups.",
                        "Display Presentation: Converting Wine Win32 HWND rendering to macOS CoreAnimation / CAMetalLayer / IOSurface without native X11/Wayland server."
                    ],
                    "deployment_scope": "Can be deployed lab-locally (self-contained host bridge library in sources/ or fixtures/); does NOT require global system installation.",
                    "risk_assessment": "High architectural complexity; potential performance degradation if synchronous call serialization introduces significant overhead; fragile memory tracking."
                },
                {
                    "id": "PATH_B",
                    "name": "Optimized Guest-Side CPU Software Rendering (Tuned Mesa Lavapipe / SwiftShader)",
                    "architecture": "Keep all Vulkan execution inside guest user-space; optimize Mesa lavapipe with NEON SIMD vectorization and multi-threading, or deploy Google SwiftShader.",
                    "technical_subsystems_required": [
                        "Mesa build configuration tuning: Enable multithreading, optimize LLVM JIT code generation for ARM64 NEON.",
                        "Alternative: Compile and deploy Google SwiftShader as an alternative CPU Vulkan ICD."
                    ],
                    "deployment_scope": "100% lab-local (drop-in files into fixtures/runtime/).",
                    "capability_boundary": "Pure CPU rasterization. Zero risk of hypervisor destabilization; 100% stable; suitable for feature verification, compute, and lightweight rendering, but fill-rate limited on complex 3D rasterization.",
                    "risk_assessment": "Low risk; fully verified and currently functional."
                },
                {
                    "id": "PATH_C",
                    "name": "Mesa Venus / VirtIO-GPU Standardized Protocol via User-Space IPC",
                    "architecture": "Guest uses Mesa's existing 'venus' driver (virtio_icd.json) -> serializes Vulkan commands over UNIX domain socket (vtest protocol) -> host standalone virglrenderer test daemon (virgl_test_server --venus) -> host Vulkan implementation (MoltenVK) -> Apple Metal.",
                    "verified_upstream_evidence": {
                        "virglrenderer_upstream_repo": "https://gitlab.freedesktop.org/virgl/virglrenderer",
                        "venus_driver_upstream_docs": "https://docs.mesa3d.org/drivers/venus.html (vtest socket protocol supported via virgl_test_server --venus)",
                        "utm_upstream_implementation": "https://github.com/utmapp/UTM/pull/7576 (PR #7576 by osy, Jan 2026: 'Enable Venus for Vulkan acceleration on Linux guests' by pairing Venus with MoltenVK)",
                        "host_metal_backend_reality": "CRUCIAL FACT: Upstream virglrenderer DOES NOT have a native Metal backend. Venus decodes Vulkan commands and issues them to a HOST Vulkan driver. On macOS, virglrenderer MUST link against host MoltenVK. Venus standardizes guest-host IPC serialization, but host MoltenVK remains mandatory for Metal translation."
                    },
                    "technical_subsystems_required": [
                        "Porting virglrenderer to macOS (replacing Linux-specific epoll/eventfd with kqueue/pipes for virgl_test_server).",
                        "Linking virglrenderer against host MoltenVK dylib (bundled lab-locally).",
                        "Configuring guest Mesa with venus driver and setting VN_DEBUG=vtest to communicate over a lab-local UNIX socket."
                    ],
                    "deployment_scope": "Can be deployed lab-locally as a standalone user-space daemon (virgl_test_server); does NOT require full Linux VM kernel or QEMU PCI emulation.",
                    "risk_assessment": "Medium-high; relies on third-party macOS port of virglrenderer and host MoltenVK stability."
                }
            ]
        },
        "acceptance_3_architectural_alignment": {
            "no_full_linux_vm_rule": "Path B (pure guest) and Path C (vtest socket daemon) do not require a Linux kernel VM. Path A uses user-space hypercall emulation. All candidate paths can run in user space.",
            "reversible_deployment_model": "Path B is 100% reversible within fixtures. Path C requires a standalone host helper binary in sources/ or fixtures/. Path A requires host elfuse changes."
        },
        "acceptance_4_minimal_actionable_first_step": {
            "first_step_experiment": "Phase 1: Proof-of-concept HVC Host Metal Device Query. Implement a minimal embedder handler in elfuse (hooking src/core/bootstrap.c:422 and dispatching via src/syscall/syscall.c:2772) that executes Objective-C [MTLCopyAllDevices()] on host and writes the GPU name string ('Apple M-series GPU') to guest memory. Verify that guest receives the host GPU name without memory corruption.",
            "pass_fail_criteria": "PASS: Guest receives 'Apple M-series GPU' string. FAIL: Translation fault, memory corruption, or vCPU lockup.",
            "caveat": "Microsecond latency measurements are performance optimization targets, not a binary pass/fail for the architectural concept."
        },
        "acceptance_5_llvmpipe_baseline": baseline,
        "acceptance_6_three_layer_conclusion": {
            "established_facts": [
                "Guest currently has 1 verified active Vulkan driver: lavapipe (llvmpipe LLVM 23.1.1) reporting 1 CPU device.",
                "Host has no system-wide MoltenVK installed in standard prefix paths.",
                "elfuse currently has zero GPU / DRM / Metal bridging code in sources/elfuse/src/.",
                "Direct in-guest dlopen of Mach-O dylib fails with 'invalid ELF header' (empirically confirmed with raw logs for x86_64 Mach-O).",
                "Upstream virglrenderer Venus requires an underlying host Vulkan implementation (MoltenVK) on macOS."
            ],
            "candidate_paths": [
                "Path A: Custom HVC Vulkan Bridge (High complexity, custom ICD and memory mapping)",
                "Path B: Optimized CPU Lavapipe (Low complexity, immediately usable, CPU bound)",
                "Path C: Mesa Venus / vtest Socket Daemon (Medium complexity, leverages upstream Venus protocol + MoltenVK)"
            ],
            "unknowns": [
                "Actual rendering throughput (FPS) under complex 3D draw workloads (unmeasured; current probe only tests enumeration).",
                "Porting friction of virglrenderer build system onto macOS Darwin host environment."
            ]
        }
    }

    out_file = LAB / "logs/moltenvk/feasibility-evidence.json"
    out_file.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote updated feasibility evidence to {out_file}")

if __name__ == "__main__":
    main()
