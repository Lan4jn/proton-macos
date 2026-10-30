# x64 Vulkan 探针同插桩对照测试与架构独立性判决报告 (Task-102)

**责任人**：evidence-reviewer-r36 (执行方)  
**实验定性**：**【硬性有效性门槛未达成：run_valid = false / 阻断于上游系统服务崩溃】(PREREQUISITE BLOCK - UNREACHED STEP 3)**  
**遵循规范**：`systematic-debugging` 与 `test-driven-development`（实测数据为纲、工件直接引用、未达标如实宣告、绝不粉饰假绿）  
**关联任务**：Task-102（用 x64 Vulkan 探针测同一 once 插桩，判定缺项是否与架构无关）  
**物理支撑收据**：
1. x64 运行物理收据：`logs/x64-vk/receipt.json` (`run-t9qrkmmc`, 62.128s, exit: 124, `run_valid: false`)
2. 崩溃现场原始日志：`logs/x64-vk/run-t9qrkmmc/stderr.log` (539,933 字节，完整寄存器上下文)
3. 编译生成的探针：`scripts/runtime/x64_vk/vk_enum_x64.exe` (SHA256: `d408405ca8340342a08e6e44ddaccc8ad78d25570bea5a523a4b10067a87dc08`)
4. 派生运行时二进制：`sources/elfuse-once-backtrace-derived/build/elfuse` (SHA256: `2d0b901d13adcdd459ece4b9827db06096f2fde7b7e3ebf60c88d0802b0448a6`)

---

## 一、 实验背景与核心目标

在 Task-82 至 Task-96 的持续攻坚中，ARM64 Windows 路径已确证以下物理事实：
1. `vk_enum_arm64.exe` 能够顺利通过 Step 1（加载 DLL）与 Step 2（解析函数指针），进入 Step 3（`vkCreateInstance`）；
2. 在 Step 3 内部，Wine Unix 端驱动库 `win32u.so`（`__wine_get_vulkan_driver` 与 `vulkan_instance_create`）发生单线程递归重入，导致控制字 `0x20102d440` 两次进入（首次 `word=0`，二次 `word=1`），陷入 `FUTEX_WAIT_PRIVATE` 死锁（AArch64 X29 深度栈回溯证明 Call 1 的上层帧仍在栈底未退出）。

**Task-102 核心目标**：
在相同底层虚拟化与同一套 once 插桩机制下，使用 **x64 Windows Vulkan 探针（通过 FEX 动态二进制翻译）** 跑测同一条链路，回答核心问题：
> **在 ARM64 上确证的 `win32u.so` 同线程递归自锁，是否是超越指令集架构的通用缺项（架构无关）？还是 x64 路径存在不同的物理行为？**

---

## 二、 最小 x64 PE 探针构建与运行配置

### 1. 探针设计与零依赖交叉编译
为避免外部导入库依赖并确保能够纯粹被 FEX 加载执行，在 `scripts/runtime/x64_vk/vk_enum_x64.c` 中构建了零 CRT 依赖的控制台程序：
- **入口点**：`mainCRTStartup`（通过 `GetStdHandle` 与 `WriteFile` 直接输出标准输出）；
- **动态寻址**：通过 `LoadLibraryA("vulkan-1.dll")` 动态加载，并通过 `GetProcAddress` 提取 `vkCreateInstance`、`vkEnumeratePhysicalDevices` 等核心函数，完全不链接 `vulkan-1.lib`；
- **同构分步标记**：严格输出与 ARM64 探针同构的标记（`[WIN_X64_VK] Step 1..5`）；
- **编译参数**：`zig cc -target x86_64-windows-gnu -O2 -nostdlib -Wl,-e,mainCRTStartup -lkernel32`；
- **制品指纹**：`scripts/runtime/x64_vk/vk_enum_x64.exe` (PE32+ executable console x86-64, SHA256: `d408405c...`)。

### 2. 运行环境配置 (Environment Delta)
- **运行时**：复用与 Task-96 完全相同的 `sources/elfuse-once-backtrace-derived/build/elfuse`；
- **前缀与目标**：从既有已验证的前缀 COW 独立克隆至 `logs/x64-vk/pfx`，将 `vk_enum_x64.exe` 拷贝至 `drive_c/vk_enum_x64.exe`；
- **命令行**：`exec .../bin-arm64/wine 'C:\vk_enum_x64.exe'`；
- **观测门禁**：`ELFUSE_ONCE_PANORAMA_OBSERVE=1`, `ELFUSE_ONCE_COUNT_UADDR=0x20102d440`, `ELFUSE_FUTEX_TARGET_UADDR=0x20102d440`, `timeout=62s`。

---

## 三、 实测物理数据与硬性有效性门槛核验

取自物理收据 `logs/x64-vk/receipt.json`：

### 1. 物理运行指标对比表

| 指标项 | ARM64 探针 (Task-96 基线) | x64 探针 (Task-102 实测) | 判定与对比定性 |
| :--- | :--- | :--- | :--- |
| **探针架构** | Windows ARM64 (AArch64 PE) | Windows x86_64 (x64 PE + FEX) | 对照架构不同 |
| **执行耗时** | 62.129 秒 | 62.128 秒 | 均触达 62s 预算 |
| **退出码** | `exit: 124` (`timed_out: true`) | `exit: 124` (`timed_out: true`) | 均超时终止 |
| **stdout 字节数** | 478 字节 (完整输出至 Step 3) | **0 字节 (未产生任何标准输出)** | **严重背离** |
| **Step 3 标记出现** | **`has_step3 = true`** | **`has_step3 = false`** | **未达有效性门槛** |
| **目标 0x20102d440 调用**| **2 次** (`target_count = 2`) | **0 次** (`target_count = 0`) | 未触达目标控制字 |
| **目标 futex enter 触发**| **1 次** (`op=0x80, val=1, word=1`)| **0 次** | 未触达末端 futex |
| **有效性裁定 (run_valid)**| **`VALID (true)`** | **`run_valid = false / FAILED`**| **门槛不达** |

---

## 四、 关键阻断点剖析：卡在哪一步？为什么未达 Step 3？

在实测中，`stdout` 为 0 字节，表明 `vk_enum_x64.exe` 甚至连第 1 行输出（`Step 1: Calling LoadLibraryA`）都未能执行。查阅 `logs/x64-vk/run-t9qrkmmc/stderr.log`，在第 2445 行确凿捕获到了宿主虚拟机级别的崩溃转储（Crash Dump）：

### 1. 崩溃现场转储证据 (Crash Dump Extract)
```text
## Crash
- type: UNEXPECTED_EC
- detail: EC=0x20 syndrome=0x82000007 VA=0xf148

## Binary
- path: /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/wine-preloader
- cmdline: .../wine-preloader .../wine C:\windows\system32\winedevice.exe

## Registers
PC   = 0x000000000000f148  CPSR = 0x0000000060000800
ESR  = 0x0000000056000000  EC=0x15 (SVC from AArch64)
FAR  = 0x0000000000000000  ELR  = 0x00000002000d1c6c
X0   = 0x0000000000000004  X1   = 0x00000001005fd9b8  X2   = 0x000000000000f148  X3   = 0x00000001005fd9b8
X8   = 0x0000000000000049  X29  = 0x00000001005fd980  X30  = 0x00000002000ff0fc
```

### 2. 崩溃根因技术定性
1. **崩溃进程**：并非 `vk_enum_x64.exe` 自身，而是 Wine 的核心后台设备驱动服务进程：`C:\windows\system32\winedevice.exe`（由 `wine-preloader` 启动）；
2. **崩溃异常类型**：`UNEXPECTED_EC: EC=0x20`（AArch64 下的 `Instruction Abort from a lower Exception level`，即尝试从不可执行或非法内存地址抓取指令）；
3. **故障地址**：`VA = 0xf148`（位于零地址附近的低位非法虚拟页）；
4. **致命后果**：
   - Wine 依赖 `winedevice.exe` 托管并加载 Windows 核心驱动（包括 `wineusb`、`winebth` 与虚拟显示设备驱动）；
   - 在启动早期，`winedevice.exe` 发生 `EC=0x20` 崩溃猝死；
   - 随之导致 Wine 服务器无法完成桌面窗口与设备服务树的创建，执行环境整体挂起，**导致下游的 `C:\vk_enum_x64.exe` 根本没有获得被创建进程上下文并执行用户代码的机会**！

---

## 五、 终局对照裁决与可反驳条件

依据任务书设定的判定条件：
> “核心产出=对照结论：x64 路径是否出现与 ARM64 相同的同线程重入自锁、是否同样落在 win32u.so、若不出现则卡在哪一步；必须给出可反驳判据与反驳条件；门槛不达则如实记 run_valid=false 并给原因。”

### 1. 终局结论
1. **有效性定性**：  
   **`run_valid = false (FAILED)`**。x64 探针因受阻于 Wine 上游系统服务崩溃，未能达成硬性有效性门槛（无 Step 3 输出，无目标一旦/futex 记录）。
2. **架构无关性假说定论**：  
   **【不可观测 / 假说未被证实】**。当前实测证明，x64 Vulkan 链路在当前的虚拟化与 Wine 环境中，**根本无法推进至 Vulkan 初始化（`vkCreateInstance`）阶段**，其在启动早期即被 `winedevice.exe` 的 `EC=0x20` 指令异常阻断。  
   因此，“`win32u.so` 重入自锁在 x64 上同样存在”的假设属于**缺乏物理执行条件的未实证假设（Unobservable due to Upstream Block）**，绝不可断言其与架构无关。

### 2. 可反驳条件 (Falsification Conditions)
1. 若修复了 `winedevice.exe` 的 `EC=0x20 (VA=0xf148)` 异常，使得 Wine 能够成功调度 `vk_enum_x64.exe` 并输出 `[WIN_X64_VK] Step 3: Calling vkCreateInstance`，且在 `win32u.so` 同样捕获到 `0x20102d440` 的二次重入死锁，则“架构无关”假说被重新激活并证实；
2. 反之，若修复上游崩溃后，x64 探针在 Step 3 顺利返回通过并成功进入 Step 4（物理设备枚举），则“重入死锁架构无关”假说被彻底证伪，证明重入死锁仅为 ARM64 原生 Wine 独特的编译或分发逻辑缺陷。
