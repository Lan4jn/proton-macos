# Windows x64 经 Wine/FEX 调用软件 Vulkan 实测报告 (task-35 终验冻结版)

**实验日期**：2026-10-16  
**执行员**：`proton-package-worker`  
**关联任务**：`task-35`（验证 Windows x64 经 Wine/FEX 调用软件 Vulkan）  
**宿主环境**：Apple Silicon macOS 27.0.1 (Build 26A434, arm64, Rosetta 2 可用, 磁盘可用空间 246 GiB)  
**交付物路径**：
- 目标 PE 源码与 Def：`fixtures/runtime/windows-vulkan/vk_enum_x64.c`, `kernel32.def`
- 编译脚本：`scripts/runtime/windows_vulkan/build_pe.sh`
- 目标 PE 二进制：
  - 首轮实测版本：`dc47ae89...` (执行了三次 100s 实测并捕获到 vkCreateInstance 阻断)
  - 最终守护版本：`f77f9b8f...` (补充 CPU/llvmpipe 严格断言与非 CPU exit 15 分类保护)
- 生产分类器与测试：`scripts/runtime/windows_vulkan/classifier.py`, `test_classifier.py`
- 执行器：`scripts/runtime/windows_vulkan/run_windows_vulkan.py`
- 独立前缀：`fixtures/runtime/windows-vulkan/pfx`
- 原始运行日志：`logs/windows-vulkan/`
  - `run-6_zr16od` (Attempt 1: 正常基线环境，捕获 LoadLibrary 成功与 vkCreateInstance 桌面等待超时)
  - `run-40za9k7o` (Attempt 2: winex11.drv=d 环境，证实底层 win32u 仍尝试建窗)
  - `run-w8dv4wns` (Attempt 3: explorer.exe=d 诊断实验，捕获 get_desktop_window 启动 explorer 失败)
  - `windows_vulkan_result.json` (生产分类器生成的结构化指标汇总)
- Lead 独立分类器验收日志：`logs/lead-round7/windows-vulkan-classifier-final.log` (**8PASS**)

---

## 1. 核心结论与执行摘要 (Executive Summary)

1. **Windows x64 Vulkan PE 编译与跨架构加载成功**：
   - 编写了极小 Windows x64 控制台程序 `vk_enum_x64.c`，手写 Vulkan 1.0 64位 ABI 结构体（`VkApplicationInfo`, `VkInstanceCreateInfo`, `VkPhysicalDeviceProperties` 带 4KiB 缓冲区），纯 `kernel32.dll` 动态加载（`LoadLibraryA` + `GetProcAddress`），**零外部 Windows SDK 依赖，零 CRT 依赖**。
   - 通过宿主 `clang -target x86_64-pc-windows-msvc` 与 `lld-link` 完成编译，生成合规的 `PE32+ executable (console) x86-64`。
   - **版本说明**：
     - 首版 PE（SHA: `dc47ae89a181166f1fa09f72d9b780e8fc00cd81e658f3b7b1004075ac06bcd0`）：实际执行了三次 100s 有界实测，成功走通 `LoadLibraryA("vulkan-1.dll")` 与 entrypoint 解析，并深入至 `vkCreateInstance` 内部。
     - 最终守护版 PE（SHA: `f77f9b8fa427120cc1488625f46f4cc05b0f1d2d2b22032f137cb81462cec412`）：根据 Lead 复审意见，补充了严格的 `deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU (4)` 与 `deviceName` 包含 `llvmpipe` 断言（否则直接 exit 15）；该版本已编译就绪并同步至前缀中，因当前执行停滞在 `vkCreateInstance` 内部，设备属性查询尚未触达，故按规范不再进行多余的 100s 长跑。
   - 实测在 Wine/FEX 下执行时，**成功通过 Windows PE thunk 跨架构装配**：
     - `LoadLibraryA("vulkan-1.dll")` 成功（装载基址 `0xfc050000`）。
     - 动态符号解析全部成功：`vkCreateInstance`, `vkEnumeratePhysicalDevices`, `vkGetPhysicalDeviceProperties` 均解析为有效函数指针。
     - `winevulkan.dll` 与 `winevulkan.so` 成功加载，并在 `vulkan_init_once` 中顺利枚举出 lavapipe ICD 支持的主机扩展（VK_KHR_surface, VK_EXT_headless_surface, VK_KHR_portability_enumeration 等）。
2. **定位首个 Windows-to-Linux Vulkan 桥阻断（First Blocker）**：
   - **阻断点**：在进入 `vkCreateInstance` 内部初始化时，Wine 的 `winevulkan` 模块为支持 Win32 Window Surface 扩展，无条件调用了 Wine 的视窗管理层（`get_desktop_window()`）。
   - **现场实证与环境隔离**：
     - **正常环境（Attempt 1: `run-6_zr16od`）**：在无 X11/Wayland 桌面服务的 Headless 实验环境下，`get_desktop_window()` 试图拉起 `explorer.exe /desktop` 创建虚拟桌面。因环境缺项，`get_desktop_window failed to create desktop window` 循环报错，导致进程在 100s 超时前无法完成 `vkCreateInstance`。
     - **实验性禁用探索（Attempt 3: `run-w8dv4wns`）**：在显式注入 `WINEDLLOVERRIDES="explorer.exe=d"` 的诊断实验下，明确捕获到 `0024:err:win:get_desktop_window failed to start explorer c0000135`。该报错系主动禁用引起的预期失败，有力证明了建窗循环是由 `get_desktop_window` 对 explorer 的调用发起的，但**不作为正常环境下的唯一排他因果**，两者严格分开记录。
3. **有限 First Blocker 结论与边界界定**：
   - **已证实范围**：Windows x64 PE 的 `vulkan-1.dll` 动态库加载成功、函数指针正确解析、`vkCreateInstance` 调用入口已进入，底层 Linux lavapipe ICD 扩展已被成功读取。
   - **未通过范围**：实例创建（`vkCreateInstance`）未成功返回，Windows 侧设备枚举（`vkEnumeratePhysicalDevices`）未触达。
   - **严谨概念界定**：**“任务完成”仅代表首个技术阻断的实验审计闭环完成，绝不等于 Windows Vulkan 技术通过**。

---

## 2. 参与运行的关键组件 SHA-256 审计清单

| 组件名称 | 本地路径 | SHA-256 校验和 | 角色与性质 |
| :--- | :--- | :--- | :--- |
| **elfuse runtime** | `sources/elfuse-lifecycle-derived/build/elfuse` | `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a` | 具备 preempt stop/join 修复的最终版 elfuse |
| **Target PE (首轮)**| `fixtures/runtime/windows-vulkan/vk_enum_x64.exe` (实测) | `dc47ae89a181166f1fa09f72d9b780e8fc00cd81e658f3b7b1004075ac06bcd0` | 极小 x64 Vulkan 探测程序（实测三次 100s 捕获到 vkCreateInstance 阻断） |
| **Target PE (最终)**| `fixtures/runtime/windows-vulkan/vk_enum_x64.exe` (就绪) | `f77f9b8fa427120cc1488625f46f4cc05b0f1d2d2b22032f137cb81462cec412` | 增加严格 CPU 类型与 llvmpipe 名称断言（非 CPU exit 15）的最终守护版本 |
| **Linux Sysroot** | `fixtures/runtime/arch-case` | `c6bc1ef497...` (usr/bin/python3.14) | 纯用户态 aarch64 Linux rootfs |
| **Lavapipe ICD** | `fixtures/runtime/lavapipe-derived/.../lvp_icd.json` | `5c37895ce497041a7d65fc97931c3bf7918ea52f6b40285a73e65c92c416e919` | 软件 Vulkan 驱动清单定义 |
| **libvulkan_lvp.so**| `fixtures/runtime/lavapipe-derived/usr/lib/libvulkan_lvp.so` | `fa7223e7f45b7ee7ea9b119fa99b40fdb261e479a3fe270ee2c7c258d356fae3` | Mesa Lavapipe aarch64 纯软件光栅化驱动 |
| **libLLVM.so.23.1** | `fixtures/runtime/lavapipe-derived/usr/lib/libLLVM.so.23.1` | `dbbc034d6be0495f5539fa985be0bca4be96cb711c25dbbb113f044d01878d6b` | 局部依赖的 LLVM JIT 运行时 |
| **Wine Loader** | `fixtures/runtime/proton-derived/files/bin-arm64/wine` | `0eb603be3624255de6d13740b73c4c5bbb9ee5c1f5f9120abdb3ebc408dab91b` | 原版 ARM64 ELF Wine 加载器 |
| **Wine Server** | `fixtures/runtime/proton-derived/files/bin-arm64/wineserver` | `dc6b16a7428df4beca04620839fc13e231a529270bd40b43c3ae3dd2d990995c` | 原版 ARM64 ELF Wineserver 守护进程 |
| **winevulkan.so** | `files/lib/wine/aarch64-unix/winevulkan.so` | `b9f5f0b543501adfe5e449297ce6985055b85a11124d67e81b67f338d7c22998` | Wine 原生 Linux Vulkan 桥接库 |
| **vulkan-1.dll** | `drive_c/windows/system32/vulkan-1.dll` | `c97b830d176aa14757523ce2eb5b9f71c4c92da09c9519520cb2a41a63c871c5` | Windows 原生 Vulkan 客户端调度加载器 |
| **winevulkan.dll** | `drive_c/windows/system32/winevulkan.dll` | `0bf42426365b8214342fc2b347b4df4bc1ca0272bc63fc8a211324aa845701d4` | Wine Windows 侧 Vulkan ICD 驱动 |

---

## 3. 实测命令行与环境隔离

### 3.1 执行命令行
```bash
/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-lifecycle-derived/build/elfuse \
    --user 501:20 \
    --sysroot /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case \
    --timeout 85 \
    /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/sh \
    -c 'LD_LIBRARY_PATH="/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/lib:/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix:/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib" "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wine" "C:\vk_enum_x64.exe"'
```

### 3.2 环境变量注入
- `WINEPREFIX`: `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/windows-vulkan/pfx`
- `VK_ICD_FILENAMES`: `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/share/vulkan/icd.d/lvp_icd.json`
- `WINEDEBUG`: `+loaddll,+process,+vulkan`
- 排除项：严格禁止在宿主 `extra_env` 中传入 `LD_*` 变量（由 `process.py` 防注入机制保护，通过 guest shell 传导）。

---

## 4. 关键日志实证与阶段分析

### 4.1 Windows x64 PE 标准输出 (STDOUT)
```
==========================================================
[WIN_X64_VK] Starting Windows x64 Vulkan Enumeration Test
==========================================================
[WIN_X64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
[WIN_X64_VK] SUCCESS: vulkan-1.dll loaded at 0xfc050000
[WIN_X64_VK] Step 2: Resolving Vulkan function pointers...
[WIN_X64_VK] SUCCESS: All function pointers resolved.
[WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
```
*证明：Windows x64 二进制已由 FEX 正确翻译并在 Wine 中执行，API 解析 100% 成功。*

### 4.2 Wine Vulkan 装配与扩展枚举实证 (STDERR)
严格锚定 `loaddll` 正向装载行：
```
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\vulkan-1.dll" at 000000DFFC050000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\winevulkan.dll" at 000000DFFBF60000: builtin
0024:trace:vulkan:DllMain 000000DFFBF60000, 1, 0000000000000000
0024:trace:vulkan:vkCreateInstance create_info 0000000140004030, allocator 0000000000000000, instance 000000000011FF48
0024:trace:vulkan:vulkan_init_once Host instance extensions:
0024:trace:vulkan:vulkan_init_once   - VK_KHR_device_group_creation
0024:trace:vulkan:vulkan_init_once   - VK_KHR_external_fence_capabilities
0024:trace:vulkan:vulkan_init_once   - VK_KHR_external_memory_capabilities
0024:trace:vulkan:vulkan_init_once   - VK_KHR_external_semaphore_capabilities
0024:trace:vulkan:vulkan_init_once   - VK_KHR_get_physical_device_properties2
0024:trace:vulkan:vulkan_init_once   - VK_KHR_get_surface_capabilities2
0024:trace:vulkan:vulkan_init_once   - VK_KHR_surface
0024:trace:vulkan:vulkan_init_once   - VK_KHR_surface_maintenance1
0024:trace:vulkan:vulkan_init_once   - VK_EXT_headless_surface
0024:trace:vulkan:vulkan_init_once   - VK_KHR_portability_enumeration
```
*证明：底层 Linux `libvulkan.so.1` 与 `libvulkan_lvp.so` 均已被 Wine 正确调用，并成功读取出 ICD 的扩展能力。*

### 4.3 首个技术缺项：`get_desktop_window` 视窗循环实证
1. **正常环境实测（Attempt 1: `run-6_zr16od`）**：
   ```
   0024:trace:process:NtCreateUserProcess L"\\??\\C:\\windows\\system32\\explorer.exe" image L"C:\\windows\\system32\\explorer.exe" cmdline L"\"C:\\windows\\system32\\explorer.exe\" /desktop" parent (nil) machine 0
   00dc:err:class:NtUserRegisterClassExWOW Failed to get shared session object for window class
   00dc:err:win:get_desktop_window failed to create desktop window
   00dc:trace:process:NtCreateUserProcess L"\\??\\C:\\windows\\system32\\explorer.exe" image L"C:\\windows\\system32\\explorer.exe" cmdline L"\"C:\\windows\\system32\\explorer.exe\" /desktop" parent (nil) machine 0
   ```
2. **主动禁用诊断实验（Attempt 3: `run-w8dv4wns`）**：
   ```
   00dc:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code -1073741515, process_exiting 0.
   0024:err:win:get_desktop_window failed to start explorer c0000135
   0024:err:win:get_desktop_window failed to create desktop window
   ```
   *确证因果：`winevulkan` 在初始化过程中触发了 `get_desktop_window`，在无桌面环境下无法获得窗口会话对象，进入反复拉起 explorer 的死循环。*

---

## 5. 生产分类器与独立单测断言 (`test_classifier.py`)

生产分类器已抽取至 `scripts/runtime/windows_vulkan/classifier.py`，并在 `run_windows_vulkan.py` 中直接集成。测试套件 `test_classifier.py` 直接引用该生产函数进行严格回归（包含实例创建后超时边界细分测试）：
```bash
$ python3 -m unittest scripts/runtime/windows_vulkan/test_classifier.py -v
test_classify_desktop_timeout (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_desktop_timeout_after_instance_created (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_load_failure (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_non_cpu_rejection (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_non_llvmpipe_rejection (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_success_rejected_if_cleanup_errors (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_success_rejected_if_target_nonzero (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_success_with_all_guards (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.001s

OK
```
生产分类器当前对实测结果（`logs/windows-vulkan/windows_vulkan_result.json`）输出的判定为：
- **`verdict: VK_CREATE_INSTANCE_DESKTOP_WINDOW_TIMEOUT`**
- **`stage: VK_CREATE_INSTANCE_SURFACE_PROBE`**
- **`message: Timed out during vkCreateInstance: winex11.drv explorer.exe desktop window creation loop`**

---

## 6. Team Lead 独立验收实证 (8PASS)

Team Lead 在其独立环境中复核了生产分类器的全部 8 项测试用例，记录于 `logs/lead-round7/windows-vulkan-classifier-final.log`：
```
test_classify_desktop_timeout (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_desktop_timeout_after_instance_created (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_load_failure (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_non_cpu_rejection (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_non_llvmpipe_rejection (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_success_rejected_if_cleanup_errors (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_success_rejected_if_target_nonzero (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok
test_classify_success_with_all_guards (scripts.runtime.windows_vulkan.test_classifier.TestVulkanClassifier) ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.001s

OK
```
Lead 独立验收全绿确认了生产分类器及测试套件的有效性。

---

## 7. 技术阻断与后续分工交接声明 (Handoff to task-37)

1. **确证的技术边界**：
   - Windows x64 PE 的 Vulkan 入口装配与动态链接：**已通过**。
   - Wine 底层向 Linux lavapipe 的驱动查询与扩展枚举：**已通过**。
   - Windows 侧纯 Headless 设备实例创建：**受阻于 Wine 视窗管理层对 `get_desktop_window` 的强耦合**。
2. **后续分工与交接**：
   - 避免无界修改注册表或引入伪 DLL；
   - 下一阶段隔离实验已交由 `task-37` (`steam-macos-research`) 开展，探索通过隔离 Xvfb（严格禁止 abstract/TCP 作用域越界）满足视窗管理层的桌面依赖；
   - 本任务（`task-35`）执行员不再修改原运行时或重复进行 100s 实测，本报告与代码已正式冻结交付。
