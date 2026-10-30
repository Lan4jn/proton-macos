# Linux Vulkan 加载与设备枚举边界实测报告 (Task-28)

## 1. 测试背景与目标

当前基于原版 Valve ARM64 Proton / Wine / FEX 的用户态执行层已取得重大突破：
- x64 控制台程序已验证在 ARM64 macOS 上经 FEX 翻译并输出 `X64_FEX_OK` (exit 0)；
- 真实 Linux Python 3.14 已能驱动原版 Proton 启动脚本；
- 然而，当运行包含桌面环境或图形组件时，出现 Wine `explorer.exe` 桌面创建失败或超时。

**本任务目标**：
在不构建完整图形驱动桥的前提下，运行真实受控的 Linux Vulkan 底层能力探针，精确切分“CPU/FEX 翻译层”与“底层 Vulkan 渲染接口层”，给出第一手实测证据，明确当前图形边界。

---

## 2. 探针环境基线与组件哈希

| 组件 | 文件路径 | SHA-256 |
| :--- | :--- | :--- |
| **elfuse candidate** | `sources/elfuse-crash-derived/build/elfuse-candidate` | `f83455b073611030d388e1f7c4be1dfee26af34106a373b3a6713497790f3e26` |
| **Linux Python** | `fixtures/runtime/arch-case/usr/bin/python3.14` | `c6bc1ef497b896b7575c546b13f9bafe52e2066f184fdd3fec6af4b5b6349947` |
| **Linux Vulkan Loader** | `fixtures/runtime/arch-case/usr/lib/libvulkan.so.1.4.357` | `7a5220b7847ea8003efec60bd08824d61de6a020a4d0177dcddd3c9d4bf677c7` |
| **Mesa Freedreno ICD** | `fixtures/runtime/arch-case/usr/share/vulkan/icd.d/freedreno_icd.json` | `3d3945591795cef0227cc46db683b36daffdb056dde416b0350dbbc9de9cb17b` |
| **Linux vulkaninfo** | `fixtures/runtime/arch-case/usr/bin/vulkaninfo` | `3415e1be31f0eec01bbbf28e5e81568d931982330f021d063e59ff7fdea69b68` |

---

## 3. 实测受控执行与层级结果

测试由宿主受控 supervisor (`scripts/backend/process.py`) 启动，超时限制 30 秒，在隔离环境中运行了两组独立探针，并经 Lead 独立实测复验：

### 3.1 探针 A: Python ctypes 真实 Vulkan ABI 探测
- **执行命令 (argv)**:
  ```json
  [
    "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-crash-derived/build/elfuse-candidate",
    "--user", "501:20",
    "--sysroot", "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case",
    "--timeout", "30",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/python3.14",
    "/Users/mewcapoo/Projects/proton-macos-lab/scripts/runtime/graphics_probe/linux_vulkan_probe.py"
  ]
  ```
- **耗时**: `0.42` 秒 | **退出码**: `0` | **超时**: `False`
- **分层检测结果**:
  1. **Loader dlopen 层**:
     - `libvulkan.so.1` 成功解析并加载 (`dlopen_success: true`, `dlopen_error: null`)。
  2. **实例版本层 (`vkEnumerateInstanceVersion`)**:
     - 返回值: `0` (`VK_SUCCESS`)
     - Loader 报告版本: `1.4.357` (原始值 `4211045`)
  3. **实例创建层 (`vkCreateInstance`)**:
     - 调用结构: 真实标准 ABI `VkApplicationInfo` + `VkInstanceCreateInfo`
     - 返回值: `0` (`VK_SUCCESS`)
     - 实例句柄创建成功 (`instance_created: true`)
  4. **物理设备枚举层 (`vkEnumeratePhysicalDevices`)**:
     - 调用参数: `vkEnumeratePhysicalDevices(instance, &count, NULL)`
     - 返回值 (`VkResult`): `-3` (`VK_ERROR_INITIALIZATION_FAILED`)
     - **判定与数据有效性校准**: 当接口返回 `-3` 失败时，`device_count` 输出未被底层填充有效值（`device_count_valid = false`, `device_count = null`），即**物理设备枚举失败，未能获得可用设备列表**，而非完成枚举并确认 GPU 数量为 0。
     - **探针判定 (verdict)**: `VK_DEVICE_ENUMERATION_FAILED`

### 3.2 探针 B: 原生 Linux `vulkaninfo --summary`
- **执行命令 (argv)**:
  ```json
  [
    "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-crash-derived/build/elfuse-candidate",
    "--user", "501:20",
    "--sysroot", "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case",
    "--timeout", "30",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/vulkaninfo",
    "--summary"
  ]
  ```
- **耗时**: `0.32` 秒 | **退出码**: `1`
- **Stderr 原始输出**:
  ```text
  'DISPLAY' environment variable not set... skipping surface info
  ERROR: [Loader Message] Code 0 : setup_loader_term_phys_devs:  Failed to detect any valid GPUs in the current config
  ERROR at /build/vulkan-tools/src/Vulkan-Tools/vulkaninfo/./vulkaninfo.h:249:vkEnumeratePhysicalDevices failed with ERROR_INITIALIZATION_FAILED
  ```
- **对照结论**: 原生 `vulkaninfo` 同样卡在 `vkEnumeratePhysicalDevices` 并抛出 `ERROR_INITIALIZATION_FAILED`，与 ctypes 探针结果完全吻合。

### 3.3 Lead 独立复验确认 (run-pa6_l1f3)
- **日志路径**: `logs/lead-round7/run-pa6_l1f3`
- **执行耗时**: `0.6` 秒（真实 Linux Python 3.14）
- **复验结果**:
  - `verdict`: `VK_DEVICE_ENUMERATION_FAILED`
  - `vkResult`: `-3` (`VK_ERROR_INITIALIZATION_FAILED`)
  - `device_count_valid`: `false`, `device_count`: `null`
- **结论**: 边界判定与数据校准已获 Lead 独立实测背书，图形边界证据冻结。

---

## 4. 根因分析与技术边界证明

探针结果提供了明确、可复现的边界证明：

1. **Loader 正常，ICD 与当前硬件不匹配**:
   - `arch-case` sysroot 中仅声明了一个 ICD 文件 `/usr/share/vulkan/icd.d/freedreno_icd.json`，指向 `/usr/lib/libvulkan_freedreno.so` (Qualcomm Adreno GPU 驱动)。
   - 当前宿主硬件为 Apple Silicon (M 系列芯片，集成 Apple GPU)，无高通 Adreno 硬件支持。
2. **sysroot 设备节点观察**:
   - Linux 下 Mesa 等驱动通常依赖 `/dev/dri/card0` 或 `/dev/dri/renderD128` 节点。在当前 `arch-case` sysroot 观察中，`/dev/dri` 节点不存在。
   - 源码审计显示 elfuse 的 `syscall/io.c` 主要处理通用文件/终端 ioctl，未包含 Linux 特定的 `DRM_IOCTL_*` 分发，但此观察仅说明当前用户态环境未配备 DRI 直通，不断言底层全部 fallback 机制。
3. **无软件光栅化驱动 (Software Rasterizer)**:
   - sysroot 中未包含 `libvulkan_lvp.so` (Lavapipe/LLVMpipe)，因此没有备用 CPU 离屏渲染通道。
4. **渲染路径与桌面创建边界分立**:
   - **Vulkan 路径阻断**: `Windows Game PE (Direct3D 11/12)` $\rightarrow$ `DXVK / VKD3D` $\rightarrow$ `winevulkan.dll` $\rightarrow$ `winevulkan.so` $\rightarrow$ `libvulkan.so.1` $\rightarrow$ `ICD Driver` $\rightarrow$ `GPU`。因底层物理设备枚举返回 `-3`，当前基于 Linux Vulkan 的 Direct3D 渲染路径**明确未通过**。
   - **桌面创建分立性**: Wine `explorer.exe` 的桌面窗口创建失败不能直接等同于 Vulkan 失败所致。Wine 桌面可使用 GDI 或 X11 驱动（`winex11.drv`），其失败更可能涉及独立的 X11/Wayland 窗口环境或 GDI 驱动缺项，属于不同维度的独立问题。

---

## 5. 残余未知与严谨声明

1. **不声明图形游戏或 Steamworks 成功**:
   - 本次探针严格证明了：**CPU 架构与 FEX 指令翻译成功并不等同于 GPU 渲染通过**。
   - 目前 Proton 在缺少 Linux-Metal 桥或 DRI 模拟的情况下，无法直接运行依赖 D3D/Vulkan 的 3D 游戏。
2. **潜在后续实验方向 (非当前任务实现范围)**:
   - (A) 纯用户态方案：将 Linux `winevulkan.so` 重定向/桥接至 macOS 宿主的 MoltenVK / Metal，跳过 Linux DRM；
   - (B) 软件渲染方案：在 sysroot 中引入 Lavapipe (`libvulkan_lvp.so`) 验证纯 CPU 离屏光栅化；
   - (C) 虚拟化方案：在轻量 VM/HVF 中暴露 virtio-gpu / virgl 虚拟显卡。

---

## 6. 证据产物汇总

- 探针脚本: `scripts/runtime/graphics_probe/linux_vulkan_probe.py`
- 运行器: `scripts/runtime/graphics_probe/run_graphics_probe.py`
- 结构化完整日志: `logs/graphics-probe/vulkan_probe_evidence.json`
- 执行子目录: `logs/graphics-probe/run-hgs8p1q0/`, `logs/graphics-probe/run-sdpq8k55/`
- Lead 独立复验日志: `logs/lead-round7/run-pa6_l1f3`
