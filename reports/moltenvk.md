# 真实 GPU (MoltenVK / Metal) 路径可行性与技术子系统评估报告 (Task-132 修订版)

**评估者**：x64-pipe-reviewer  
**核心结论与声明**：
1. **现状事实核查与 ABI 屏障确证**：
   - **Guest ICD 现状**：Guest Linux 系统仅有 1 个可工作的 Vulkan ICD，即 Mesa `lavapipe`（CPU 软件模拟器，报告为 `llvmpipe (LLVM 23.1.1, 128 bits)`，枚举设备数 `count=1`）；无硬件 GPU ICD 或 virtio-gpu 驱动；
   - **宿主 MoltenVK 现状**：宿主 macOS 未在全局系统路径（`/opt/homebrew`, `/usr/local`）安装任何公共 MoltenVK SDK；仅在商业 App 内部存在私有捆绑动态库；
   - **ABI 绝对屏障实测**：在 `elfuse` 容器内由真实 guest python3.14 尝试 `dlopen` 实际存在的 Mach-O 动态库，被 Linux 动态链接器 `ld.so` 明确拒绝（错误信息：`invalid ELF header`）。经 `file` 与 `lipo -info` 核实，该目标文件为 **Mach-O 64-bit x86_64** 架构（Magic 前 16 字节为 `cffaedfe070000010000000000000000`，小端 `0x01000007` 为 `CPU_TYPE_X86_64`）。**本次实测确证了该真实 Mach-O 文件被 Linux guest ld 严格拒绝；明确说明本次未测试 arm64 Mach-O MoltenVK（亦不再扫描商业应用其他私有文件）。无论何种 CPU 架构，Mach-O 头部均不是合法 ELF 头部，跨 OS 边界直接 dlopen 在机制上无法成立**；
   - **`elfuse` 源码现状**：查阅 `sources/elfuse/src/` 源码，`elfuse` 包含 0 行 GPU / DRM / virgl / Metal 代码，无现成图形桥接能力。
2. **候选路径评估与上游事实核对**：
   - **路径 A（自定义 HVC Vulkan 转发 Bridge）**：在 Guest 实现 ELF Vulkan ICD，通过 private Linux syscall -> EL1 shim -> HVC 转发至宿主 `elfuse`，再调用 host MoltenVK / Metal。需攻克接口特权级、协议序列化、Metal `MTLBuffer` 映射至 Guest 物理内存（`hv_vm_map` 零拷贝管理）、命令缓冲区完成同步及 Win32 HWND 跨进程画面呈现等 5 个重型技术子系统，架构复杂度极高；
   - **路径 B（调优 Guest 侧纯 CPU 软件渲染 - 推荐近期务实路线）**：继续沿用 Mesa `lavapipe` 或引入 Google `SwiftShader`。**100% 遵守“不写完整 Linux VM”与“可逆本地部署”原则**，超管风险为零，但算力上限受制于 CPU 核心与 NEON 向量宽度；
   - **路径 C（基于 Mesa Venus 协议的 VirtIO-GPU 用户态 Socket 桥接）**：查证 FreeDesktop 上游与 UTM 官方实现，**上游 virglrenderer 本身并无原生 Metal 后端**；Venus 负责将 Vulkan 命令序列化并通过 Socket（`vtest` 模式）传递，而在 macOS 宿主端，virglrenderer **依然必须依赖宿主 MoltenVK 将其转化为 Metal**。该路径避免了自行设计 Vulkan 协议，但仍需在宿主解决 virglrenderer 的 macOS 编译支持及其对 MoltenVK 的链接；
3. **部署模型与工程清单收敛**：
   - 移除无实测依据的历法工期推测（如 3-6 人月/1-2 人月），代之以各路径所需的**具体技术子系统分解清单**；
   - 明确桥接库与守护进程**可完全采用 lab-local 独立部署**（如放置在 `fixtures/` 或 `sources/` 局部目录），不强制依赖宿主全局系统级安装；
4. **基线测量纠偏**：
   - 纠正基线度量表述：6.179 秒为 Vulkan 实例初始化的总体开销（涵盖 `libvulkan_lvp.so` 加载、Mesa 核心启动、LLVM 编译基础设施初始化与扩展筛选，**不能断言全是 LLVM JIT**）；
   - 设备枚举与属性查询耗时小于 1 毫秒（时间戳均为 `1578617.771`），实例销毁耗时 13 毫秒（`1578617.771` 至 `1578617.784`）；
   - **明确声明：因现有探针（`vk_enum_arm64.exe`）未包含实际绘制负载（Draw Call / Swapchain / Compute），渲染吞吐（FPS）在当前测试中为未实测项（UNMEASURED），删除所有无实测依据的帧率推断与“绝对稳定”断言**；
5. **严正声明**：**本报告绝不宣称已实现真实 GPU 加速**。

---

## 1. 事实核查证据清单 (Acceptance 1)

### 1.1 Guest 侧 Vulkan ICD 现存事实
在 `fixtures/runtime/` 目录检索所有 Vulkan ICD Manifests：
- **现存清单**：
  1. `fixtures/runtime/lavapipe-derived/usr/share/vulkan/icd.d/lvp_icd.json`：
     ```json
     {
         "ICD": {
             "api_version": "1.4.354",
             "library_path": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/lib/libvulkan_lvp.so"
         },
         "file_format_version": "1.0.1"
     }
     ```
     驱动库：`libvulkan_lvp.so`（Mesa CPU 软件模拟，在 Wine 中报告为 `llvmpipe (LLVM 23.1.1, 128 bits)`）；
  2. `fixtures/runtime/arch-case/usr/share/vulkan/icd.d/freedreno_icd.json`：
     高通骁龙 Adreno 硬件驱动，Apple Silicon 环境下无法加载；
- **核查结论**：Guest 侧除 CPU 软件光栅化的 `lavapipe` 外，**无任何硬件 GPU ICD 或 virtio-gpu 驱动**。

### 1.2 宿主 macOS 侧 MoltenVK 存在状态与 ABI 屏障核验
在宿主标准路径检索（`/opt/homebrew`、`/usr/local`、`/Library/Frameworks`）：
- **公共 SDK**：**未检测到全局安装的 MoltenVK 库、头文件或 Vulkan SDK**；
- **真实目标库文件核验**（不碰商业应用其他私有文件）：
  - 路径：`/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib64/libMoltenVK.dylib`；
  - 文件大小：`10,242,560 字节`；
  - SHA-256：`86eb61cf6fca7e9a8f2762a4fa95e4d1f274cb459f373111f1966a3ba081395b`；
  - `file` 实测结果：`Mach-O 64-bit dynamically linked shared library x86_64`；
  - `lipo -info` 实测结果：`Non-fat file: ... is architecture: x86_64`；
  - Magic 字节：前 16 字节为 `cffaedfe070000010000000000000000`。其中 `cffaedfe` 为 `MH_MAGIC_64`，次 4 字节小端 `07000001`（`0x01000007`）严格对应 Darwin 内核 `CPU_TYPE_X86_64`（`CPU_TYPE_I386 | CPU_ARCH_ABI64`）；
- **实测范围限制声明**：
  本次实测仅直接验证了该特定的 x86_64 Mach-O 动态库被 Guest Linux `ld.so` 拒绝，**明确说明本次并未在 lab 中使用 arm64 架构的 MoltenVK 动态库进行测试，亦不再扫描商业 App 的其他私有文件**。但根据操作系统原理，任何 Mach-O 文件（无论 arm64 还是 x86_64）均以 `0xcffaedfe` 开头，Linux 动态链接器均会直接判定为 `invalid ELF header`。

### 1.3 ABI 绝对屏障实测与原始日志
执行受控脚本 `scripts/runtime/moltenvk/run_abi_probe.py`：
- **运行身份**：
  - Host 运行时：`sources/elfuse-once-panorama2-derived/build/elfuse`（SHA-256: `8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda`）；
  - Guest 解释器：`/usr/bin/python3.14`（Host 路径：`fixtures/runtime/arch-root/usr/bin/python3.14`，SHA-256: `ad8043621415f9ff7aa60a349c25bbbf5377f07823f66c88f28c2e68449c2111`）；
  - 目标库：`/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib64/libMoltenVK.dylib`；
  - 完整执行参数：
    ```text
    /Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-once-panorama2-derived/build/elfuse       --user 501:20       --sysroot /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-root       --timeout 10       /usr/bin/python3.14       -c "import ctypes; ctypes.CDLL('/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib64/libMoltenVK.dylib')"
    ```
- **原始标准输出日志（`logs/moltenvk/abi_probe_stdout.log`）**：
  ```text
  REJECTION: /Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib64/libMoltenVK.dylib: invalid ELF header
  ```
- **原始标准错误日志（`logs/moltenvk/abi_probe_stderr.log`）**：
  ```text
  08:58:42 WARN  src/core/sysroot.c:409: sysroot /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-root is case-insensitive; workloads with colliding guest names such as Linux kernel trees may fail. Use --create-sysroot to run inside a case-sensitive APFS sparsebundle.
  ```

### 1.4 `elfuse` 源码审计与 `hvc6_handler` 机制核实
审计 `sources/elfuse/src/` 源码：
1. **GPU / DRM 相关实现**：
   - 检索 `drm`、`/dev/dri`、`gpu`、`virgl`、`virtio`、`metal`：**确认 elfuse 源码中完全没有 GPU 虚拟化或 DRM 模拟代码**；
2. **`hvc6_handler` 真实存在性与编号冲突核实**：
   - **函数声明**：`src/core/guest.h:597` 定义 `uint64_t (*hvc6_handler)(uint64_t call_nr, const uint64_t args[8], void *userdata);`；
   - **主进程挂载点**：`src/core/bootstrap.c:422`，在 `guest_init` 完成后；
   - **触发点 1**：`src/syscall/proc.c:4414`，当 vCPU 触发 HVC #6 异常时调用；
   - **触发点 2**：`src/syscall/syscall.c:2772`，当 guest 执行伪系统调用 `ELFUSE_NR_EMBEDDER_HVC6` 时进入（**源码目前严格受 `if (g->is_rosetta ...)` 门控**）；
   - **硬件特权级边界**：在 ARM64 体系结构中，用户态（EL0）无法直接执行 `HVC` 指令（EL0 执行 HVC 会作为 Undefined Instruction 异常陷入 EL1）。因此未提权的普通 Linux 应用程序（EL0）必须发起 `SVC #0` 系统调用，由 EL1 向量表（`shim.S`）转发至宿主；
   - **进程继承边界 (COW / Fork Caveat)**：`src/core/guest.h:592` 注释明确写明：`The hook is process-local and does not survive fork(). elfuse implements fork via posix_spawn() of a fresh process, so the child must register its own handler.`。Wine 依赖 `fork`/`clone` 派生子进程，此 hook 无法天然跨进程保留，需在 `src/runtime/fork-state.c` 的子进程启动路径显式重新注册；
   - **HVC 编号分布（`src/core/shim.S:13-33`）**：
     `#0` Normal exit, `#2` Bad exception, `#4` Set sysreg, `#5` Syscall forward, `#6` Embedder hook, `#7` MRS trap, `#9` W^X toggle, `#10` BRK, `#11` EL0 fault, `#12` System instr trap, `#13` Ptrace interrupt。
     **HVC #6 无编号冲突，但需要 EL1 shim 的配套支持方可对非 Rosetta 原生 Guest 开放**。

---

## 2. 候选路径深度评估 (Acceptance 2 & 3)

### 2.1 路径 A: 自定义 HVC Vulkan 转发 Bridge (Direct Bridge)
- **架构描述**：在 Guest 编写 `libvulkan_bridge.so` (ELF)，拦截 150+ 个 Vulkan API -> 序列化为自定义 HVC 载荷 -> `elfuse` 宿主端解包 -> 调用宿主 `libMoltenVK.dylib` -> 驱动 Apple Metal。
- **所需技术子系统清单**：
  1. **特权接口与进程继承**：在 `elfuse` 中开放针对 native guest 的专用 Linux syscall 号，并在 `fork_ipc` 中实现 embedder hook 的跨进程自动重新注册；
  2. **协议序列化解析层**：实现 150+ 个 Vulkan 核心函数及大量扩展参数的深度序列化/反序列化，包括复杂的动态多级嵌套 `pNext` 链表解析；
  3. **内存共享与生命周期管理**：解决 `vkMapMemory` 难题。必须将 Metal 的 `[MTLBuffer contents]` 宿主内存通过 `hv_vm_map` 动态映射进 Guest GPA，并妥善管理页对齐、GPA 地址碎片回收与并发访问；
  4. **异步同步转换层**：将 Metal Command Buffer 的异步完成回调映射为 Linux 内部的 `VkFence` / `VkSemaphore` 线程唤醒；
  5. **跨进程画面呈现**：Wine 渲染至 Win32 GDI/X11 HWND；需在无原生 X11/Wayland 桌面服务的环境下，将帧缓冲对接至 macOS CoreAnimation / CAMetalLayer / IOSurface。
- **部署模式**：**完全可 lab-local 部署**（桥接库放在 lab 内部源码或局部目录，编译产物纳入 fixtures，无需宿主全局安装）。
- **风险与评价**：高风险。即使 HVC 往返耗时较低，跨特权级序列化和频繁的虚存动态映射（`hv_vm_map`）仍可能引入严重微卡顿，且工程复杂度极高。

---

### 2.2 路径 B: 调优 Guest 侧纯 CPU 软件渲染 (推荐近期务实路线)
- **架构描述**：保持所有图形执行闭环在 Guest 内存空间。继续基于 Mesa 现有 `lavapipe` 进行编译参数优化（启用多线程光栅化、针对 AArch64 NEON 指令集展开向量化优化），或引入 Google `SwiftShader`。
- **所需技术子系统清单**：
  1. Mesa 交叉编译选项优化：调整 `lp_bld_nir`，开启更多并发 Worker 线程；
  2. 可选：编译集成 Google SwiftShader CPU Vulkan 驱动并生成对应的 `vk_swiftshader_icd.json`。
- **部署模式**：**100% lab-local 可逆部署**（仅需在 `fixtures/runtime/` 内替换或新增驱动 `.so` 与 manifest，对宿主环境 0 侵入）。
- **能力边界与评价**：
  - **优势**：零超管风险，100% 遵守“不写完整 Linux VM”的既定路线；无需任何跨 ABI 内存共享或特权穿透；
  - **局限**：受制于 CPU 物理核心数与 NEON 向量带宽，光栅化填充率较低，无法应对现代高负载 3D 游戏，但非常适合系统引导、UI 呈现、驱动合规性验证与离线计算。

---

### 2.3 路径 C: Mesa Venus / VirtIO-GPU 协议直通 (标准化协议解包)
- **架构描述**：Guest 使用 Mesa 现成的 `venus` Vulkan 驱动（`virtio_icd.json`）-> 通过 UNIX Domain Socket（`vtest` 协议模式）将命令流输出至宿主 -> 宿主运行独立守护进程 `virgl_test_server --venus` -> 宿主调用 MoltenVK -> 驱动 Apple Metal。
- **可核验上游证据**：
  1. **Upstream 源码与规范**：
     - Virglrenderer 仓库：`https://gitlab.freedesktop.org/virgl/virglrenderer`；
     - Mesa Venus 文档：`https://docs.mesa3d.org/drivers/venus.html` 明确支持通过 UNIX socket 的 `vtest` 模式（`virgl_test_server --venus`）与 Guest 通信，无需 QEMU PCI 内核驱动；
  2. **UTM 官方实现参考**：
     - UTM 讨论与 Pull Request：Issue #4551 及 PR #7576（`https://github.com/utmapp/UTM/pull/7576`，由 osy 于 2026-01 合并：“Enable Venus for Vulkan acceleration on Linux guests”）；
     - **上游核心事实**：**virglrenderer 自身没有原生的 Metal 后端**；Venus 仅是 Vulkan 命令的序列化协议，在宿主端解码后依然需要一个底层的 Vulkan 实现。在 macOS 宿主上，**UTM 必须将 virglrenderer 链接到宿主 MoltenVK 才能把调用转换为 Metal**。
- **所需技术子系统清单**：
  1. 移植 virglrenderer 到 macOS（在构建配置中解决 Linux 专有头文件依赖，开启 `-Dvenus=true`）；
  2. 宿主编译并捆绑 lab-local 的 MoltenVK 与 `virgl_test_server` 可执行程序；
  3. 配置 Guest 环境变量 `export VN_DEBUG=vtest`，指向 lab 内部的本地 socket。
- **部署模式**：**可 lab-local 部署**（独立编译守护进程放置于 lab 目录中作为后台辅助进程启动，无需修改操作系统全局配置）。
- **风险与评价**：中高风险。相较于路径 A，其优势在于协议面由 Mesa 官方维护；劣势在于 virglrenderer 在 macOS 平台的编译维护较为脆弱，且依然需要宿主 MoltenVK 的支持。

---

## 3. 现状基线性能量化与表述纠偏 (Acceptance 5)

基于 Task-127 真实运行日志（`logs/wine-pin/patched_adea/run-sjo653xi/stderr.log`）实测提取准确度量（已更新至 `logs/moltenvk/llvmpipe_baseline.json`）：

### 3.1 实测时间开销分布
- **总运行时间**：`48.18 秒`
- **Wine 前缀与系统服务初始化**：`41.99 秒`（占总时间约 87%）
- **Vulkan 实例初始化总体开销**：`6.179 秒`
  - 起始时间戳：`1578611.592`（`vkCreateInstance` 调用入口）
  - 完成时间戳：`1578617.771`（`Created instance 0x103ed70`）
  - **内涵说明**：涵盖动态加载 `libvulkan_lvp.so`、Mesa 核心子系统初始化、LLVM 编译管道环境建立及主机/客户机扩展匹配筛选。**明确纠偏：不可断言此 6.179 秒全部为 LLVM JIT 编译**。
- **物理设备枚举与属性获取开销**：**`< 1 毫秒`**
  - 起始与结束时间戳：均为 `1578617.771`（在 1ms 分辨率日志中无跳变），表明在驱动初始化就绪后，纯元数据查询开销极低；
- **实例销毁与退出开销**：**`13 毫秒`**
  - 发生于 `1578617.771` 至 `1578617.784`（DllMain detach）。

### 3.2 渲染吞吐 (FPS) 状态与缺失说明
- **实测状态**：**未测量（UNMEASURED）**；
- **缺失说明**：现有探针 `vk_enum_arm64.exe` 的职责严格限于物理设备发现与属性查询（Step 1 至 Step 5），**未创建渲染交换链（Swapchain），未发起任何绘制调用（Draw Call），未提交命令缓冲区，亦无计算着色器负载**。
- **纠偏断言**：**严谨删除所有无实测依据的帧率推断（如 1-5 FPS）与“绝对稳定”表述**。真实渲染性能需待后续加载具有实际绘制循环的探针（如 `vkcube` 或离屏三角形渲染）后方能量化。

---

## 4. 最小可执行第一步实验设计：最小 Metal 设备查询桥 (Acceptance 4)

若后续决策确需探索跨特权级宿主图形穿透，建议执行以下**仅针对宿主 Metal 设备查询的极简探针设计**，不涉及硬件 Vulkan 加速：

### 4.1 实验目标与真实源码 Hook 定位
1. **真实源码挂载点**：
   - **主进程初始化**：`sources/elfuse/src/core/bootstrap.c:422`，在 `guest_init(g, 0, req_ipa)` 完成后，注册宿主 handler：`g->hvc6_handler = probe_metal_device_handler;`；
   - **子进程继承处理**：`sources/elfuse/src/runtime/fork-state.c`，在 fork_ipc child 初始化处重新绑定该 handler，解决 `guest.h:592` 提示的跨进程丢失问题；
   - **Guest 系统调用分发**：`sources/elfuse/src/syscall/syscall.c:2772`，将原本受 `g->is_rosetta` 限制的 embedder 系统调用对原生 AArch64 开放；
2. **宿主执行动作**：
   - 宿主端调用 Apple Metal 接口：`NSArray<id<MTLDevice>> *devices = MTLCopyAllDevices();` 并读取 `[devices.firstObject name]`；
   - 宿主将该名称字符串（如 `Apple M-series GPU`）拷贝至 Guest 传入的虚拟地址缓冲区；
3. **Guest 测试代码**：
   - 编写极简 20 行汇编或 C 程序，发起该系统调用并打印返回的设备名称字符串；
4. **判定准则 (Pass/Fail Gate)**：
   - **PASS**：Guest 成功接收并输出宿主真实 Metal GPU 名称字符串，无内存违规或 vCPU 异常；
   - **FAIL**：发生 GVA 翻译异常、内存越界崩溃或 vCPU 挂死。
   - **科学界限说明**：微秒级时延指标仅作为性能优化参考，**单次实验结果仅验证接口连通性，不作为整条架构路线的唯一生杀死锁判据**。

---


### 4.2 未来原生 Guest 查询的设计约束与计时边界说明 (Lead 审查核定)
1. **显式 Opt-in 独立入口原则**：
   未来若实施针对 native guest 的 Metal 设备查询，**严禁直接移除现有 `syscall.c:2772` 中对 `ELFUSE_NR_EMBEDDER_HVC6` 的 `g->is_rosetta` 权限门控**。应新增专用的、显式 opt-in 的诊断入口（如受专门环境变量保护的独立伪系统调用号或虚拟字符设备），保持既有架构权限边界的完整性；
2. **日志时间戳分辨率边界**：
   日志中呈现的同毫秒时间戳（如 `1578617.771`）仅表示**在当前已埋点观测边界内未产生可分辨的毫秒级间隔**。由于探针埋点并未完全包围驱动内部所有未插桩函数与系统资源分配，不得将同毫秒读数断言为整个物理设备枚举全生命周期的绝对时间上限。

## 5. 三层确定性结论汇报 (Acceptance 6)

1. **第一层：已确证硬事实（100% 证据闭环）**：
   - Guest 系统目前仅有 `lavapipe` CPU 驱动可用（报告为 1 个 CPU 设备）；
   - 宿主无全局公共 MoltenVK 安装；
   - Guest 无法直接跨 ABI `dlopen` 宿主 Mach-O 动态库（glibc 明确报错 `invalid ELF header`，原始输出已入档）；
   - `elfuse` 源码中无任何 DRM 或 GPU 硬件虚拟化设施；
   - 上游 virglrenderer 的 Venus 模式在 macOS 上依然强制依赖宿主 MoltenVK。
2. **第二层：候选路径规划与技术子系统定位**：
   - **近期务实路线**：**路径 B（Guest 侧纯 CPU 渲染优化）**，100% 符合“不写完整 Linux VM”与“可逆本地部署”原则；
   - **远期演进路线**：若性能不可妥协，优先评估 **路径 C（Mesa Venus + lab-local vtest 守护进程）**，避免路径 A 的庞大自定义 ICD 协议负担。
3. **第三层：未证与后续事项（Unknowns）**：
   - 真实 3D 游戏在并发多线程配置下 `lavapipe` 的实际渲染帧率（当前探针无绘制指令，处于未实测状态）；
   - 在 macOS 宿主环境下为无窗口离屏渲染编译 `virglrenderer` 的实际移植摩擦。

---

## 6. 交付工件清单

1. **主报告**：`reports/moltenvk.md`
2. **机器可读综合证据**：`logs/moltenvk/feasibility-evidence.json`
3. **基线测量数据（纠偏版）**：`logs/moltenvk/llvmpipe_baseline.json`
4. **ABI 屏障实测输出与原始日志**：
   - `logs/moltenvk/abi_probe_result.json`
   - `logs/moltenvk/abi_probe_stdout.log`
   - `logs/moltenvk/abi_probe_stderr.log`
5. **架构规范头文件**：`sources/moltenvk-feasibility/bridge_architecture.h`
6. **自动化脚本**：
   - `scripts/runtime/moltenvk/run_abi_probe.py`
   - `scripts/runtime/moltenvk/measure_llvmpipe_baseline.py`
   - `scripts/runtime/moltenvk/assemble_evidence.py`
