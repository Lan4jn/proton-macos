# proton-macos

An experimental research laboratory exploring Windows binary execution on Apple Silicon (macOS ARM64) using customized Proton/Wine components and the `elfuse` HVF-backed Linux execution harness.

---

## ⚠️ Reality Check & Current Project Status

**This repository is an ongoing research laboratory, NOT a production Wine display driver, NOT an out-of-the-box gaming solution, and NOT an official Valve Proton port.**

### What Has Been Validated
- **Minimal PE Execution**: Minimal Windows x64 console PE (`minimal-x64.exe`) execution under headless/diagnostic environments (reaching exit code 43 / normal termination under controlled session harnesses with APFS clonefile prefix isolation).
- **Wine Runtime Loader Progression**: Step-by-step resolution of early Wine boot/loader dependency closures across core modules (`ntdll`, `kernelbase`, `advapi32`, `user32`, `gdi32`, `win32u`, `shell32`, `ole32`, and `wininet` initialization).
- **Headless Frame Presentation Prototype**: IPC length-framed RGBA8 frame transfer and host-side view presentation spike (A-copy single-frame smoke pass verified with CRC32 matching).
- **Kernel / Harness Guarding**: Process-group-based supervision, fail-closed timeout handling, and deterministic teardown without naked `killall`.

### What Is NOT Implemented / NOT Supported
- **NO Production Display Driver**: P2 (Wine single-window GDI / Metal display driver) is **NOT implemented**.
- **NO Hardware GPU Acceleration**: All Vulkan / graphics probes run via software CPU rasterization (`llvmpipe`). Hardware GPU / Metal presentation paths are unverified.
- **Memory Semantics Remain Experimental**: Guest mapping and cross-process session-sharing behavior have separate diagnostic gates. APFS prefix cloning is filesystem isolation, not proof of guest shared-memory or COW correctness. The final minimal-PE validation did not enable the session-sharing diagnostic opt-ins.
- **NO Games or Production Steam Client**: No commercial games have been verified as playable. Real Steam client discovery, installation, and Steamworks runtime are unverified (dynamic gates remain `NOT_RUN`).

---

## 📦 Repository Scope & Fresh Clone Expectations

### Important Note on Fresh Clone Execution
**A fresh clone of this repository CANNOT run all test suites or benchmarks out of the box.**

To keep this git repository lightweight, clean, and free of massive third-party binaries, the following assets are **deliberately excluded** from version control (see `.gitignore`):
- Valve Proton shipped runtime bundles (~3 GB)
- Full Arch Linux aarch64 guest sysroots and shared library trees
- Upstream Wine compilation trees and intermediate object files
- Multi-gigabyte test execution logs, raw framebuffers, and process core dumps
- SteamCMD binary packages, local libraries, and caches
- Windows PE test executables and runtime prefixes

### What This Repository Contains
- **`scripts/`**: Test runners, session supervisors, lifecycle harnesses, and diagnosis scripts.
- **`sources/`**: Lab-developed C/Python prototypes, presenter spikes, upstream base trees (`sources/elfuse/`), and structured diagnostic closures (`sources/wine-init-round3/`, `sources/p0-session-round2/`, `sources/patch-release/`).
- **`patches/`**: Targeted patches for Wine, Vulkan re-entrancy guards, and runtime fixes. Reproducibility is maintained by applying patches to upstream source trees rather than claiming unverified byte-identical toolchain rebuilds.
- **`fixtures/`**: Curated in-tree test source files (e.g. C/assembly test sources in `fixtures/abi/`, `fixtures/elfuse/`), while large external runtime rootfs are excluded.
- **`reports/`**: Rigorous fact-based audit reports, engineering decision records, and boundary manifests.

To run end-to-end guest experiments, users must independently provide compatible aarch64 Linux sysroots, Proton runtime bundles, and test PE binaries according to documented directory structures.

---

## 📜 Upstream Notices & Licenses

This project builds upon, derives from, and interacts with several upstream open-source projects. **No single unilateral root license is assigned to this repository.** Users and distributors must respect the respective licenses of all upstream components and patches:

- **elfuse**: Hypervisor and system call translation harness, Copyright (C) elfuse contributors, licensed under the **Apache License, Version 2.0** (verified via `sources/elfuse/LICENSE`).
- **Wine**: Portions derived from Wine are Copyright (C) Wine contributors and CodeWeavers, Inc., licensed under the **GNU Lesser General Public License (LGPL), version 2.1 or later**. See [WineHQ](https://www.winehq.org/).
- **Valve Proton**: Portions derived from Proton are Copyright (C) Valve Corporation, licensed under BSD / LGPL / Valve Proton license terms. See [ValveSoftware/Proton](https://github.com/ValveSoftware/Proton).
- **Other Third-Party Libraries**: FEX-Emu, Musl libc, FreeType, Fontconfig, and Zlib retain their respective upstream copyrights and licenses.

Patches to upstream projects are intended to be submitted or applied against their respective upstream source trees under their respective native licenses.

---

## 🔒 Security & Privacy Notice

Prior to public push, a strict commit inventory inspection is conducted across all staged paths. No private credentials, no Steam account authentication tokens, no private keys, and no proprietary game assets are intentionally included in the published commit tree.

## Latest bounded verification

See [Round 3 results](sources/wine-init-round3/RESULTS-FINAL.md): fixed PE exit **43**, launcher/runner **0/0**, elapsed **17.19 s**. Historical reports reference local logs and external assets not distributed here.

Runtime variant patches in `patches/elfuse/variants/` apply independently to elfuse commit `8612033dab8dc60728f604a4ea0441895fc16d39`; they are alternatives, not a cumulative patch series. Source application/hash verification does not establish byte-identical rebuilt executables.
