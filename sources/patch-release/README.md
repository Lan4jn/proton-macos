# Wine Win32u Vulkan Reentrancy Guard Patch Package

This package contains the upstreamable source patch, commit message, reproduction guide, and empirical verification data for resolving the Windows ARM64 Vulkan recursive initialization deadlock in Wine's `win32u.so`.

---

## 1. Overview & Package Manifest

- **Target Repository**: `https://github.com/ValveSoftware/wine`
- **Target Branch**: `experimental_11.0`
- **Target Source Commit**: `adea6cbac9d00bb22910145354d00c463fcf3afc` (Committed: 2026-09-24T00:51:45Z)
- **Structural Equivalence Range**: `[66ee546cbea4f15d9098bc146312a818c356f9e5 .. adea6cbac9d00bb22910145354d00c463fcf3afc]`
- **Commit Status Qualification**: Commit `adea6cbac` represents an empirically verified structural and runtime compatible baseline within the equivalent interval `[66ee546cbea4..adea6cbac]`; it is not formally certified via Valve submodule pointer as the unique exact build commit of the distributed container.

### Package Contents

| File | Description |
| :--- | :--- |
| `wine-vulkan-reentrancy-guard-adea6cbac.patch` | Standard unified diff (`-p1`) modifying `dlls/win32u/{d3dkmt.c, vulkan.c, win32u_private.h}` |
| `commit-message.txt` | Full Git commit message containing problem description, root cause, deferral rationale, and two-way control data |
| `README.md` | This document: build instructions, deployment steps, pass/fail criteria, and known caveats |
| `evidence-summary.json` | Machine-readable evidence summary with exact file SHAs, line numbers, and run metrics |
| `apply-check.log` | Verification log of clean `git apply --check`, `patch -p1 --dry-run`, and byte-identical comparison |

---

## 2. Why Source Pinning Matters (ABI & Offset Compatibility)

Wine's `dlls/win32u` communicates with `dlls/winevulkan` using internal, unexported data structures (`struct vulkan_instance`, `struct vulkan_physical_device`, and `struct instance`).

The Valve Proton redistribution package (`experimental-11.0-20260924-arm64`, build timestamp `1790245028` / 2026-09-24T10:17:08Z) ships a pre-built `winevulkan.so` compiled against **Vulkan 1.4.357** (82 instance functions) and contains an `api_version` field introduced in commit `66ee546cbea4`.

Building against commits before `66ee546cbea4` (such as `dc26e618`, which used Vulkan 1.4.339 with 79 functions) creates structural misalignment:
- `sizeof(struct vulkan_instance)` is `0x2e0` instead of `0x2f8` (24 bytes short).
- `physical_devices` pointer offset is `0x2c8` instead of `0x2e0`.

Applying this patch to commit **`adea6cbac`** achieves **100% natural binary struct alignment** with shipped Proton binaries:
- `sizeof(struct vulkan_instance) == 0x2f8` (760 bytes)
- `offsetof(physical_devices) == 0x2e0` (736 bytes)
- `offsetof(physical_device_count) == 0x2e8` (744 bytes)
- `sizeof(struct vulkan_physical_device) == 0x288` (648 bytes)
- `sizeof(struct instance) == 0x368` (872 bytes)
- **Zero manual struct modifications or padding adjustments needed!**

### Byte-Identical Patch Application Verification
Applying `wine-vulkan-reentrancy-guard-adea6cbac.patch` onto a clean tree of `adea6cbac` produces files with identical SHA256 checksums to the tested build tree (`sources/wine-pin-adea/patched/`):

| File | Applied SHA256 Checksum | Tested Build Tree SHA256 Checksum | Match Status |
| :--- | :--- | :--- | :---: |
| `dlls/win32u/d3dkmt.c` | `2281833cd4b95353651044b059fece64a6716fc521befca32ed0e53c576917df` | `2281833cd4b95353651044b059fece64a6716fc521befca32ed0e53c576917df` | **IDENTICAL** |
| `dlls/win32u/vulkan.c` | `8bdc516db04b6a542f8a7975148622812df9167c2ee522c0c4522360dd3e336e` | `8bdc516db04b6a542f8a7975148622812df9167c2ee522c0c4522360dd3e336e` | **IDENTICAL** |
| `dlls/win32u/win32u_private.h` | `7f504dd51cb94bc5e1a4eea31e431df765fd9644e797ac464c16f3cb007ec368` | `7f504dd51cb94bc5e1a4eea31e431df765fd9644e797ac464c16f3cb007ec368` | **IDENTICAL** |

---

## 3. Step-by-Step Reproduction Guide

### Step 1: Check Out Target Source Tree
```bash
git clone https://github.com/ValveSoftware/wine.git
cd wine
git checkout adea6cbac9d00bb22910145354d00c463fcf3afc
```
*(Alternatively, extract the pristine source tarball from `sources/wine-pin-adea/wine-adea6cbac9d00bb22910145354d00c463fcf3afc.tar.gz`)*

### Step 2: Apply Reentrancy Guard Patch
```bash
# Test applicability
git apply --check -v wine-vulkan-reentrancy-guard-adea6cbac.patch

# Apply cleanly
git apply wine-vulkan-reentrancy-guard-adea6cbac.patch
# Or: patch -p1 < wine-vulkan-reentrancy-guard-adea6cbac.patch
```

### Step 3: Configure and Cross-Compile win32u.so
Ensure your build environment has host Wine tools (`winebuild`, `makedep`, `widl`) and a functional `aarch64-linux-gnu` cross toolchain with Vulkan development headers:
```bash
# Generate Vulkan and IPC headers if building from bare git
python3 dlls/winevulkan/make_vulkan -x vk.xml -X video.xml
./tools/make_requests
./tools/make_specfiles

# Configure
./configure --host=aarch64-linux-gnu \
            CC="aarch64-linux-gnu-gcc" \
            READELF="aarch64-linux-gnu-readelf" \
            --with-wine-tools="/path/to/host_wine_build" \
            --with-vulkan \
            --enable-win64 \
            --without-x \
            --without-freetype \
            --disable-tests

# Build only win32u.so
make dlls/win32u/win32u.so -j4
```

### Step 4: Deploy Patched win32u.so
Copy the compiled `dlls/win32u/win32u.so` into the Proton runtime:
```bash
TARGET_LIB="/path/to/proton/files/lib/wine/aarch64-unix"
cp dlls/win32u/win32u.so "${TARGET_LIB}/win32u.so"
```
*(Keep the shipped `winevulkan.so`, `ntdll.so`, and other modules untouched)*

### Step 5: Execute Test Probe
Launch the Windows ARM64 test probe (`vk_enum_arm64.exe`) in a clean prefix:
```bash
wine 'C:\vk_enum_arm64.exe'
```

---

## 4. Pass / Fail Acceptance Criteria & Binary Differentiation

The evaluation strictly differentiates the three relevant `win32u.so` binary variants:

1. **Shipped Original Binary (`4f6013fa...`)**:
   Valve-distributed unpatched `win32u.so` from Proton experimental-11.0-20260924-arm64. Used in the baseline run (`run-73d055tk`).
2. **Pristine adea6cbac Build (`96de5f0a...`)**:
   Compiled from clean `adea6cbac` source without modifications. Used exclusively for static disassembly and struct layout verification (0x2f8 / 0x2e0).
3. **Patched adea6cbac Build (`59a76b05...`)**:
   Compiled from `adea6cbac` with this reentrancy guard patch applied. Used in the patched run (`run-sjo653xi`).

| Stage / Metric | Shipped Original Baseline Control (`FAIL`) | Patched adea6cbac Build (`PASS`) |
| :--- | :--- | :--- |
| **Tested Binary** | Shipped Original (`4f6013fa...`) | Patched adea Build (`59a76b05...`) |
| **Test Run Directory** | `logs/wine-pin/shipped_baseline/run-73d055tk/` | `logs/wine-pin/patched_adea/run-sjo653xi/` |
| **vkCreateInstance() Return** | Does NOT return (hangs forever) | **Returns `VK_SUCCESS`** |
| **Physical Device Query** | Not reached | **Step 4 & Step 5 Reached** |
| **Physical Device Count** | 0 (no output) | **`Physical device count: 1`** |
| **Device Name Output** | None | **`deviceName: llvmpipe (LLVM 23.1.1, 128 bits)`** |
| **Process Exit Code** | **124** (Watchdog timeout kill) | **0** (Clean natural termination) |
| **Execution Duration** | > 65 seconds | **~48 seconds** |
| **stderr Concurrency Trace** | `FUTEX_WAIT_PRIVATE` on `0x201039970` with `word=1` | Clean progression, zero recursive lock waits |

---

## 5. Known Limitations, Caveats & Disclaimers

1. **Diagnostic Mapping Caveat (`ELFUSE_DIAG_SESSION_SHARED=1`)**:
   The runtime verification runs were executed with `ELFUSE_DIAG_SESSION_SHARED=1` active in elfuse. This diagnostic override uses shared alias mappings for winstation sections, which diverges from true Linux private page cache copy-on-write (COW) semantics. The guard patch specifically eliminates in-process `pthread_once` recursion; cross-process page cache coherence remains an orthogonal host runtime concern.
2. **Compiler TLS Allocation Nuance**:
   The guard relies on `static __thread int vulkan_init_depth;` (allocated in `.tbss`). While this eliminates POSIX dynamic key table exhaustion risks (`EAGAIN`/`ENOMEM`), in dynamically loaded shared libraries (`dlopen`), TLS access via `__tls_get_addr` may still allocate Dynamic Thread Vector (DTV) memory under glibc/musl. Therefore, `.tbss` does not guarantee absolute zero dynamic allocation under all dynamic linking edge cases, but it avoids manual `pthread_key` lifecycle failure points.
3. **Source Pinning Dependency**:
   This patch relies on Wine internal structs that are not protected by a stable C ABI. Applying this patch to older Wine trees (e.g. 1.4.339) will cause silent struct offset mismatches with companion libraries.
4. **GDI Display Cache Persistence**:
   During driver initialization, `get_vulkan_gpus()` returns `FALSE`, causing `lock_display_devices()` to record fallback display adapter entries in the registry. Subsequent GDI queries reuse this cached registry state until an external display configuration event (`WM_DISPLAYCHANGE`) triggers a forced refresh (`update_display_cache(TRUE)`). This behavior does not impact direct Vulkan rendering via `winevulkan`.
5. **Scope of Fix**:
   This patch specifically eliminates the recursive initialization deadlock between `vulkan_init_once`, `d3dkmt_init_vulkan`, and `lock_display_devices`. It does not claim upstream approval or that every arbitrary Windows Vulkan game will function without additional platform support.

---

## 6. Release Files SHA256 Checksums

| File | Size (Bytes) | SHA256 Checksum |
| :--- | :---: | :--- |
| `wine-vulkan-reentrancy-guard-adea6cbac.patch` | 8,875 | `a22655b6f7b77edabbf0796fe6ad9d613a01cb2282dd27b1d09c29cadc7443a2` |
| `commit-message.txt` | 5,877 | `4b58e7456d9595dcabf7c4613ff558455581ff23bca01e74f1ea0770cb5bf4d5` |
| `apply-check.log` | 2,173 | `ff138676d47d483448f2197607755ba90bc2c42d3aa05bc46bb22f18395f1917` |
| `evidence-summary.json` | 5,038 | `47fa274a4ff1f76dae9671d48c82d499ba5ec9b53ae3345494d136696dbf532a` |
| `README.md` | (Self) | (See report for self-checksum) |
