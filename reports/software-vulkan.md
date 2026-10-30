# 官方 ARM64 Lavapipe 软件 Vulkan 设备隔离验证报告 (Task-33)

## 1. 实验背景与核心目标

在 Task-28 中，我们实测证明了当前用户态环境的 Vulkan loader (`libvulkan.so.1`) 与实例创建功能正常，但由于 sysroot 中仅存在高通 Adreno 专用驱动 (`libvulkan_freedreno.so`) 且缺少 Linux DRM/DRI 内核节点，物理设备枚举直接返回 `VK_ERROR_INITIALIZATION_FAILED` (`-3`)。

**本任务目标**：
在完全不依赖凭据、不修改宿主全局配置、不改动 `arch-case` 基础镜像的前提下，通过隔离引入官方 ARM64 软件光栅化驱动（Lavapipe / `libvulkan_lvp.so`），实测验证纯 CPU 软件 Vulkan 物理设备枚举通道是否可用，精确厘清当前渲染边界。

---

## 2. 官方发行包获取与置信度审计

按照“预算 $\le 150$ MiB、不超过 3 个关键包、无包管理器全局安装”的约束，从 Arch Linux ARM 官方镜像获取包：

| 软件包 | 官方源 URL | 文件大小 | SHA-256 |
| :--- | :--- | :--- | :--- |
| **vulkan-swrast** (1:26.2.4-1) | `http://fl.us.mirror.archlinuxarm.org/aarch64/extra/vulkan-swrast-1%3A26.2.4-1-aarch64.pkg.tar.xz` | 1,893,908 B (~1.81 MiB) | `7a7f91740277b249e7ffde741ce0775ce54cf288e2f27e14e84451b9a26439e8` |
| **llvm-libs** (23.1.1-1) | `http://fl.us.mirror.archlinuxarm.org/aarch64/extra/llvm-libs-23.1.1-1-aarch64.pkg.tar.xz` | 37,588,856 B (~35.85 MiB) | `d890dc562274f6e2ec59d5b2ceb21ddeabee89c0563ead27a550ee11810cdff4` |

- **总包数**: `2` 个包（远低于 3 个包上限）
- **总下载体积**: `39,482,764` B (~37.65 MiB，远低于 150 MiB 上限)
- **解包位置**: 隔离释放至 `fixtures/runtime/lavapipe-derived/`，完全未触碰 `arch-case`。
- **签名与置信度校准说明**:
  - 镜像上的 `.sig` 分离签名文件均已下载并存入 `artifacts/graphics-software/`。
  - 本次获取仅从官方 HTTP 镜像目录列出并下载，计算了本地 SHA-256 校验和，但**未单独采集并核对 Arch Linux ARM 官方 repo db (`extra.db`) 内部的预期 SHA-256**。
  - 宿主与 lab 隔离沙箱未全局安装 Arch Linux ARM 官方 GPG 密钥环（严禁全局安装），且传输为 HTTP 镜像源，因此本实验将置信度严格界定为：
    **`HTTP_MIRROR_DOWNLOADED_PGP_UNVERIFIED`**
    （HTTP 镜像源已下载并记录本地哈希，PGP 签名未验证，未做 repo db 预期校验和闭环校验），绝不自称完成未执行的验证步骤。

---

## 3. 动态链接 (DT_NEEDED) 与依赖闭包审计

根据两轮收敛规则，对解包后的二进制进行动态依赖审计：
1. **第一轮 (`libvulkan_lvp.so`)**:
   - `DT_NEEDED` 包含：`libLLVM.so.23.1`, `libz.so.1`, `libzstd.so.1`, `libdrm.so.2`, `libexpat.so.1`, `libxcb*.so`, `libwayland-client.so.0`, `libdisplay-info.so.3`, `libudev.so.1`, `libSPIRV-Tools.so`, `libstdc++.so.6`, `libc.so.6`。
   - 发现唯一缺项为 `libLLVM.so.23.1`（`arch-case` 现存为 `libLLVM.so.22.1`）。
2. **第二轮 (`libLLVM.so.23.1`)**:
   - `DT_NEEDED` 包含：`libffi.so.8`, `libedit.so.0`, `libz.so.1`, `libzstd.so.1`, `libxml2.so.16`, `libstdc++.so.6`, `libc.so.6`。
   - 经核查，以上依赖在 `arch-case/usr/lib/` 中**已全部就绪**。
3. **闭包结论**:
   - 依赖链在 2 轮内完全收敛，仅需补充 `vulkan-swrast` 与 `llvm-libs` 两个包即可形成完整的动态链接闭包，未发生无界包依赖膨胀。

---

## 4. 实测受控执行与设备枚举结果

测试使用当前经过审查的生命周期修复二进制 `elfuse-lifecycle-derived` (`sources/elfuse-lifecycle-derived/build/elfuse`, SHA-256: `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`)，在受控隔离进程中运行。

### 4.1 探针 A: Python ctypes 标准 ABI 探测 (`probe_lavapipe.py`)
- **执行命令 (argv)**:
  ```json
  [
    "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-lifecycle-derived/build/elfuse",
    "--user", "501:20",
    "--sysroot", "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case",
    "--timeout", "30",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/python3.14",
    "/Users/mewcapoo/Projects/proton-macos-lab/scripts/runtime/software_vulkan/probe_lavapipe.py"
  ]
  ```
- **环境变量**: `VK_ICD_FILENAMES=/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/share/vulkan/icd.d/lvp_icd.json`
- **执行状态**: 耗时 `0.42` 秒 | 退出码 `0` | 超时 `False`
- **分层检测数据**:
  - `LLVM 预加载`: 成功 (`success: true`)
  - `Loader dlopen`: 成功加载 `/usr/lib/libvulkan.so.1`
  - `vkEnumerateInstanceVersion`: 返回 `0` (`VK_SUCCESS`)，版本 `1.4.357`
  - `vkCreateInstance`: 返回 `0` (`VK_SUCCESS`)，实例成功创建
  - `vkEnumeratePhysicalDevices`:
    - 返回值: `0` (`VK_SUCCESS`)
    - 数据有效性: `device_count_valid = true`
    - 物理设备数量: `device_count = 1`
  - `VkPhysicalDeviceProperties` 详情:
    - 设备句柄: `0x13462d0`
    - `deviceName`: `llvmpipe (LLVM 23.1.1, 128 bits)`
    - `deviceType`: `VK_PHYSICAL_DEVICE_TYPE_CPU` (数值 `4`)
    - `vendorID`: `0x10005` (Khronos / Mesa 官方软件渲染器 Vendor ID)
    - `apiVersion`: `1.4.354`
    - `driverVersion`: `0x6802004` (Mesa 26.2.4)
  - **判定 (verdict)**: **`LAVAPIPE_SOFTWARE_DEVICE_ENUMERATED`**

### 4.2 探针 B: 原生 Linux `vulkaninfo --summary`
- **执行命令 (argv)**:
  ```json
  [
    "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-lifecycle-derived/build/elfuse",
    "--user", "501:20",
    "--sysroot", "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case",
    "--timeout", "30",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/sh",
    "-c",
    "LD_LIBRARY_PATH=/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/lib /usr/bin/vulkaninfo --summary"
  ]
  ```
- **执行状态**: 耗时 `0.55` 秒 | 退出码 `0` | 超时 `False`
- **实际输出摘要**:
  ```text
  ==========
  VULKANINFO
  ==========
  Vulkan Instance Version: 1.4.357

  Devices:
  ========
  GPU0:
  	apiVersion         = 1.4.354
  	driverVersion      = 26.2.4
  	vendorID           = 0x10005
  	deviceID           = 0x0000
  	deviceType         = PHYSICAL_DEVICE_TYPE_CPU
  	deviceName         = llvmpipe (LLVM 23.1.1, 128 bits)
  	driverID           = DRIVER_ID_MESA_LLVMPIPE
  	driverName         = llvmpipe
  	driverInfo         = Mesa 26.2.4-arch1.1 (LLVM 23.1.1)
  	conformanceVersion = 1.3.1.1
  ```

### 4.3 Lead 独立复验确认 (run-3i7xsthu)
- **运行日志**: `logs/lead-round7/run-3i7xsthu`
- **执行耗时**: `0.474` 秒（真实 Linux Python 3.14 + `f2a678...` elfuse + derived ICD）
- **复验结果**:
  - `VkResult`: `0` (`VK_SUCCESS`)
  - `device_count_valid`: `true`, `device_count`: `1`
  - `deviceType`: `VK_PHYSICAL_DEVICE_TYPE_CPU`
  - `deviceName`: `llvmpipe (LLVM 23.1.1, 128 bits)`
- **确认范围**: Lead 独立复验完全认可当前**有限物理设备枚举成功**的实验结论。

---

## 5. 对比 Task-28 与技术边界结论

| 维度 | Task-28 (原基线) | Task-33 (本次 Lavapipe 隔离实验) |
| :--- | :--- | :--- |
| **ICD 配置** | `freedreno_icd.json` (Qualcomm 硬件驱动) | `lvp_icd.json` (Lavapipe CPU 软件驱动) |
| **内核 DRM 依赖** | 强依赖 `/dev/dri/*`，因缺失而初始化失败 | 纯 CPU 光栅化，不依赖 `/dev/dri/*` 内核硬件节点 |
| **vkCreateInstance** | `VK_SUCCESS` (0) | `VK_SUCCESS` (0) |
| **vkEnumeratePhysicalDevices** | `VK_ERROR_INITIALIZATION_FAILED` (`-3`) | **`VK_SUCCESS` (0)** |
| **device_count** | `null` (枚举失败，count 无效) | **`1` (有效)** |
| **deviceType** | 无 | **`VK_PHYSICAL_DEVICE_TYPE_CPU`** |
| **deviceName** | 无 | **`llvmpipe (LLVM 23.1.1, 128 bits)`** |

### 核心结论与严谨声明：
1. **CPU 级 Vulkan 设备枚举通道打通**:
   通过隔离挂载官方 Lavapipe 驱动，我们在没有任何内核 DRM 驱动和无虚拟机的情况下，成功在 Apple Silicon macOS 上让 Linux 用户态环境完整完成了 Vulkan 实例创建和物理设备枚举。
2. **严格区分软件模拟与硬件加速**:
   - 本实验成功枚举出的设备类型明确为 **`PHYSICAL_DEVICE_TYPE_CPU`**，由 LLVM JIT 在 CPU 上进行光栅化；
   - **绝不冒充 Apple GPU 硬件加速或 Metal 桥接**，宿主 Apple Silicon 的硬件 GPU 依然未直接暴露给 Linux 空间。
3. **严格限定为设备枚举边界，不宣称实际绘制/分发**:
   - 本任务按约束仅证明了**物理设备枚举（Device Enumeration）**成功；
   - **绝不宣称实际命令调度（Dispatch）、绘制调用（Draw call）或图形渲染管线通过**；
   - **不外推 3D 游戏或 UI 运行成功**：不进行 3D 游戏启动、三角形绘制或 Steam GUI 运行测试。

---

## 6. 证据产物汇总

- **下载来源账本**: `artifacts/graphics-software/packages_manifest.json`
- **已下载官方包**:
  - `artifacts/graphics-software/vulkan-swrast-1:26.2.4-1-aarch64.pkg.tar.xz` (及 `.sig`)
  - `artifacts/graphics-software/llvm-libs-23.1.1-1-aarch64.pkg.tar.xz` (及 `.sig`)
- **隔离解包目录**: `fixtures/runtime/lavapipe-derived/`
- **探针脚本**:
  - `scripts/runtime/software_vulkan/probe_lavapipe.py`
  - `scripts/runtime/software_vulkan/run_software_vulkan_probe.py`
- **完整结构化日志**: `logs/software-vulkan/software_vulkan_evidence.json`
- **Lead 独立实测日志**: `logs/lead-round7/run-3i7xsthu`
