/*
 * sources/moltenvk-feasibility/bridge_architecture.h
 *
 * Source-audited specification of the elfuse embedder interface
 * and the minimal Metal device query bridge design.
 */
#ifndef MOLTENVK_BRIDGE_ARCHITECTURE_H
#define MOLTENVK_BRIDGE_ARCHITECTURE_H

#include <stdint.h>
#include <stdbool.h>

/*
 * =========================================================================
 * 1. elfuse Embedder Interface Source Locations & Constraints
 * =========================================================================
 *
 * Exact Source Hook Locations:
 * - Declaration:
 *     src/core/guest.h:597:
 *       uint64_t (*hvc6_handler)(uint64_t call_nr, const uint64_t args[8], void *userdata);
 *       void *hvc6_userdata;
 * - Primary Process Setup Hook:
 *     src/core/bootstrap.c:422 (immediately after guest_init(g, 0, req_ipa))
 * - Fork / Clone Child Inheritance Hook:
 *     src/runtime/fork-state.c (in fork_ipc child setup)
 *     *Caveat: guest.h:592 explicitly documents that hvc6_handler is process-local
 *      and does NOT survive fork/clone. Child processes must re-assign it.
 * - Syscall Trapping & Dispatch Hook:
 *     src/syscall/syscall.c:2772:
 *       #ifdef ELFUSE_ROSETTA_EMBEDDER_SYSCALL
 *           if (g->is_rosetta && nr == ELFUSE_NR_EMBEDDER_HVC6 && g->hvc6_handler)
 *       *Caveat: Currently gated strictly on g->is_rosetta. Native AArch64 guests
 *        require either removing the is_rosetta condition or allocating a dedicated
 *        Linux pseudo-syscall number in dispatch.tbl.
 * - Hardware Privilege Boundary:
 *     ARM64 hardware prohibits EL0 (unprivileged user code) from executing HVC.
 *     Executing HVC at EL0 triggers an Undefined Instruction exception to EL1.
 *     Therefore, guest user code must issue SVC #0 (Linux syscall), which the
 *     EL1 shim (src/core/shim.S:11) captures and forwards to the host.
 * - HVC Numbering in src/core/shim.S:13-33:
 *     #0 Normal exit, #2 Bad exception, #4 Set sysreg, #5 Syscall forward,
 *     #6 Embedder hook (proc.c:4414), #7 MRS trap, #9 W^X toggle, #10 BRK,
 *     #11 EL0 fault, #12 System instr trap, #13 Ptrace interrupt.
 *     HVC #6 has no numbering conflict.
 */

#define ELFUSE_HVC_VK_DISPATCH          0x564b  /* 'VK' identifier */

/*
 * =========================================================================
 * 2. Minimal Metal Device Query Bridge Command Set
 * =========================================================================
 *
 * Scope: Strictly limited to querying host Metal device capabilities and name.
 * Does NOT implement, emulate, or claim hardware Vulkan acceleration.
 */
enum vk_bridge_command {
    VK_CMD_PROBE_HOST_METAL_DEVICE   = 0x01, /* Query [MTLCopyAllDevices()] name */
    VK_CMD_GET_HOST_METAL_CAPS       = 0x02, /* Query Metal feature set / family */
};

struct vk_bridge_hvc_args {
    uint32_t command;
    uint32_t status;
    uint64_t out_name_gva;      /* Guest buffer address for device name string */
    uint64_t out_name_max_len;  /* Buffer capacity (e.g. 256 bytes) */
    uint64_t out_bytes_written; /* Length written by host Metal query */
};

/*
 * Target ABI Clarification:
 * - Tested dylib (/Applications/CrossOver.app/.../libMoltenVK.dylib) was verified
 *   via file and lipo to be Mach-O 64-bit x86_64 (CPU_TYPE_X86_64 = 0x01000007).
 * - Tested rejection: Linux dynamic linker ld-linux-aarch64.so.1 failed with
 *   'invalid ELF header' upon reading the Mach-O header (cffaedfe).
 * - An arm64 Mach-O MoltenVK library was NOT tested in this lab.
 */


/*
 * =========================================================================
 * 3. Future Native Bridge Design Constraints (Team Lead Review Directive)
 * =========================================================================
 *
 * 1. Opt-in Diagnostic Entry:
 *    If native guest querying is implemented in the future, it MUST introduce
 *    a dedicated, separate explicit opt-in diagnostic entry (e.g. via a new
 *    gated pseudo-syscall or virtual device node) while strictly PRESERVING
 *    the existing g->is_rosetta gate on ELFUSE_NR_EMBEDDER_HVC6, rather than
 *    broadly dismantling existing permission checks.
 *
 * 2. Timing Resolution Boundary:
 *    Identical millisecond timestamps in logs (e.g. 1578617.771) only prove that
 *    no distinguishable interval occurred within the instrumented logger boundary.
 *    Because the logging hooks do not enclose the entirety of all internal driver
 *    traversals, it must not be asserted as an absolute upper bound for the
 *    entire enumeration lifecycle.
 */

#endif /* MOLTENVK_BRIDGE_ARCHITECTURE_H */
