# 恢复已知 Wine 驱动环境对照并观测首个 C++ 异常实测报告 (审定修订版)

**实验日期**：2026-10-16  
**执行员**：`steam-macos-research`  
**关联任务**：`task-46`（恢复已知 Wine 驱动环境对照并观测首个 C++ 异常）  
**宿主环境**：Apple Silicon macOS 27.0.1 (arm64, Rosetta 2 可用)  
**交付物路径**：
- 前缀与 6 核心 DLL 验证收据：`fixtures/runtime/wine-badalloc-control/dll_verification.json`
- 环境变量对照收据：`fixtures/runtime/wine-badalloc-control/envdelta.json`
- 目标前缀：`fixtures/runtime/wine-badalloc-control/pfx/`
- 控制器脚本：`scripts/runtime/wine_badalloc_control/controller.py`
- 宿主执行器：`scripts/runtime/wine_badalloc_control/run_control.py`
- 运行日志与执行指标：`logs/wine-badalloc-control/run-1792127044/`
  - `summary.json` (宿主执行摘要与 absock 隔离审计)
  - `wine_execution_record.json` (Wine 运行状态与 trace 指标)
  - `wine_stdout.log`, `wine_stderr.log` (Wine 完整终端流)
  - `xvfb_stdout.log`, `xvfb_stderr.log` (Xvfb 服务输出)
  - `xcb_probe.json` (X11 客户端认证握手记录)
  - `Xauthority` (原子 0600 MIT-MAGIC-COOKIE-1 凭据)

---

## 1. 核心结论与执行摘要 (Executive Summary)

1. **整体执行判定：`NO_TRACE` / `OBSERVATION_TIMEOUT`**：
   - 本次实验严格按规范执行了**唯一一次受控对照运行**（未进行任何二次或隐式重跑）。
   - **执行结果**：在加载 `libbadalloc_trace.so` 诊断库与开启 `+seh` 诊断后，Wine 主进程（PID 0024）在加载 `C:\vk_enum_x64.exe`、`ntdll.dll` 及 `libarm64ecfex.dll` 后，于 `wine-preloader` 内部陷入停滞，触发了 `elfuse` 的 vCPU 10 秒看门狗超时中断（`CRASH_TIMEOUT`，Wine 退出码 124，运行耗时 60.21s）。
   - 目标测试程序未进入 `vkCreateInstance` 阶段，未观测到，映射/异常是否发生未知，捕获到的 `[BADALLOC_TRACE]` 行数为 **0**。整体观测状态标定为 `NO_TRACE`。
2. **控制器与 Wine 运行状态严格解耦（严禁以外部 0 判定成功）**：
   - 宿主执行器/外层控制器退出码为 **0**（因控制器正常调度、捕获子进程退出并完成了受控清理）；
   - 内部 Wine 进程退出码为 **124**，观测状态被独立标定为 `OBSERVATION_TIMEOUT`。**明确判定：测试目标未成功，严禁以外层控制器的退出码 0 掩盖内部 Wine 未能完成测量的真实失败**。
3. **中继隔离与路由范围严格界定**：
   - `lab/.s` 目录预检验证通过（mode 0700，uid 501，非符号链接）；
   - 运行前实测证实：在 `ELFUSE_ABSOCK_BASE=/Users/mewcapoo/Projects/proton-macos-lab/.s` 环境下，抽象套接字中继严格生成于 `lab/.s` 内部（如 `n4f079a68415addb6`）；
   - **隔离边界澄清**：虽然本次运行前后宿主 `/tmp/elfuse-absock-*` 目录增量为 0（`new_host_absock_dirs: []`），但这**并非全域 host /tmp 零写的通用数学证明**；结合显式 base 源码约束（`net-absock.c`）与 preflight 实测，**该零污染结论仅确证了本次实验会话的抽象中继路由被有效约束在 `lab/.s` 内部**。
4. **C++ 异常拦截机制的静态符号边界与假说审定**：
   - 近端 `llvm-readelf` 静态审计确证：当前 lavapipe 实际依赖的 `fixtures/runtime/lavapipe-derived/usr/lib/libLLVM.so.23.1`（`DT_NEEDED` 绑定）中**并未导入 `__cxa_throw`**，而是导入了 `_ZSt17__throw_bad_allocv@GLIBCXX_3.4`（符号 215）。
   - **严谨界定**：这一事实仅表明了所选 `libLLVM.so.23.1` 的静态符号引用边界，**既不能证明历史观察到的 `std::bad_alloc` 必然是由 LLVM 发起，也不能自动推导断言 `__cxa_throw` interposer 必然会被绕过**（因为 `libstdc++.so.6` 内部的 `_ZSt17__throw_bad_allocv` 仍可能调用 `__cxa_throw`）。此项仅作为静态符号证据记录，不泛化因果。

---

## 2. 参与运行的关键组件 SHA-256 与 6 核心 DLL 验证

### 2.1 关键组件 SHA-256 清单

| 组件名称 | 本地绝对路径 | SHA-256 校验和 | 属性说明 |
| :--- | :--- | :--- | :--- |
| **elfuse 运行时** | `sources/elfuse-socket-derived/build/elfuse` | `06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d` | 支持显式 `ELFUSE_ABSOCK_BASE` 的派生 runtime |
| **诊断跟踪库** | `fixtures/runtime/badalloc-trace/libbadalloc_trace.so` | `6f034d0aaf3ff6796817d0eb947ace3e1aaa9d4fedeab139e6e6dc5efa0348d5` | v2 版 `__cxa_throw` 调用栈跟踪库 |
| **目标 PE 程序** | `fixtures/runtime/wine-badalloc-control/pfx/drive_c/vk_enum_x64.exe` | `f77f9b8fa427120cc1488625f46f4cc05b0f1d2d2b22032f137cb81462cec412` | 包含 CPU/llvmpipe 严格断言的 Windows x64 PE |
| **Xvfb 官方包** | `artifacts/display-software/xorg-server-xvfb-21.1.25-2-aarch64.pkg.tar.xz` | `9ff2d843b83dd61bf82746f3c675ca64f0d7ffa8c6e9b23281c005c83aedba7d` | 官方 Arch Linux ARM 镜像 HTTP 下载包（未本地 PGP 签名核验，非经认证官方件） |
| **Linux Sysroot** | `fixtures/runtime/arch-case` | `c6bc1ef497...` (usr/bin/python3.14) | APFS 区分大小写 rootfs 镜像 |
| **Lavapipe ICD** | `fixtures/runtime/lavapipe-derived/.../lvp_icd.json` | `2dc30fc23e5114a7dfaa43a68c5d8bde77dc3173e9bf0bc9d74e48a4117f2231` | 软件 Vulkan 驱动声明文件（与 task-33 冻结记录一致，修正此前报告抄错） |

### 2.2 前缀 6 核心 DLL 验证收据 (`dll_verification.json`)
```json
{
  "prefix": "fixtures/runtime/wine-badalloc-control/pfx",
  "dlls": {
    "vulkan-1.dll": {
      "is_symlink": false,
      "exists": true,
      "size_bytes": 655360,
      "sha256": "8c1748972d70333974f063312e1e9f0a084929b38f5141f9a9d397bcc0367222",
      "verified": true
    },
    "winevulkan.dll": {
      "is_symlink": true,
      "link_target": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-windows/winevulkan.dll",
      "exists": true,
      "size_bytes": 1114112,
      "sha256": "54b057f2bb1303272a2d7304e8f342b47ed0945021c1683f778b9c26e1257f90",
      "verified": true
    },
    "user32.dll": {
      "is_symlink": true,
      "link_target": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-windows/user32.dll",
      "exists": true,
      "size_bytes": 3670016,
      "sha256": "ed91a530f3c0c26fd50a427fd02d02d9a6f287a66a2390b5ac0cebb651693a74",
      "verified": true
    },
    "ucrtbase.dll": {
      "is_symlink": false,
      "exists": true,
      "size_bytes": 2490368,
      "sha256": "0331346ae15c7b3484067545216144b1532ae84d9be5df927492b5ad40a9ce94",
      "verified": true
    },
    "win32u.dll": {
      "is_symlink": true,
      "link_target": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-windows/win32u.dll",
      "exists": true,
      "size_bytes": 1376256,
      "sha256": "3e285832ab800634a82e28e4292e009ea3da09520b1786aceae38e3bea1aaf7f",
      "verified": true
    },
    "ntdll.dll": {
      "is_symlink": false,
      "exists": true,
      "size_bytes": 2293760,
      "sha256": "1033f8724e012e31b38b8899ff03ba41c45e6e7e6b9b77fc549bf43baf43f1f4",
      "verified": true
    }
  },
  "overall_verified": true
}
```

---

## 3. 环境变量对照与恢复确认 (`envdelta.json`)

实验配置完全对照恢复了 task-37 原有基准：
1. **完全一致的驱动与运行时变量**：
   - `WINEESYNC=0`, `WINEFSYNC=0`, `PROTON_NO_ESYNC=1`, `PROTON_NO_FSYNC=1`, `PROTON_NO_NTSYNC=1`, `PROTON_USE_ARM64=1`
   - `VK_ICD_FILENAMES=/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/share/vulkan/icd.d/lvp_icd.json`
2. **完整驱动搜索路径恢复（Linux `/bin/sh -c` 内置）**：
   ```bash
   export LD_LIBRARY_PATH="/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/lib:/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix:/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib:/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/lib"
   export LD_PRELOAD="/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/badalloc-trace/libbadalloc_trace.so"
   exec "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wine" "C:\vk_enum_x64.exe"
   ```
3. **受控变量差异 (Deltas)**：
   - `runtime`: 由 `f2a678dd...` 切换至支持 `ELFUSE_ABSOCK_BASE` 的 `06a2fceb...`；
   - `ELFUSE_ABSOCK_BASE`: 显式设为宿主私有目录 `/Users/mewcapoo/Projects/proton-macos-lab/.s`；
   - `WINEDEBUG`: 由 `+loaddll,+process,+vulkan` 扩充为 `+loaddll,+process,+vulkan,+seh`；
   - `LD_PRELOAD`: 注入诊断库 `libbadalloc_trace.so`。

---

## 4. 运行执行指标与计时边界对比

### 4.1 四级计时边界严格界定

本次测试涉及多层独立的超时与控制时钟，具体划分如下：

| 计时层级 | 配置/设计上限 | 实际观察耗时 | 终止触发源与机制说明 |
| :--- | :--- | :--- | :--- |
| **宿主执行器预算 (Runner Timeout)** | 135 秒 (`--timeout 135`) | 64.68 秒 | 宿主进程级生命周期上限，正常随控制器退出结束 |
| **控制器内部 Wine 目标上限** | 90 秒 (`controller.py`) | 60.21 秒 | Python 控制器轮询上限；本轮未达 90s 门限即因子进程退出而终止 |
| **Wine 实际运行存活时间** | 最多 90 秒 | **60.21 秒** | 子进程自然执行耗时，因内部 preloader 崩溃而终结 |
| **elfuse vCPU 看门狗周期** | **10 秒** (`proc.c:4881`) | **10.0 秒** | **实际触发源**：主线程在 FEX 阶段停滞超过 10s 未响应，看门狗强杀并置退出码 124 |

### 4.2 运行执行指标记录 (`summary.json` 与 `wine_execution_record.json`)
```json
{
  "controller_exit_code": 0,
  "runner_elapsed_sec": 64.68,
  "run_dir": "/Users/mewcapoo/Projects/proton-macos-lab/logs/wine-badalloc-control/run-1792127044",
  "new_host_absock_dirs": [],
  "lab_absock_residual": []
}
```
```json
{
  "wine_exit_code": 124,
  "wine_elapsed_sec": 60.21,
  "wine_status": "OBSERVATION_TIMEOUT",
  "badalloc_trace_found": false,
  "trace_lines": []
}
```

### 4.3 终端诊断流与看门狗超时中断现场 (`wine_stderr.log`)
在 `wineboot` 与系统驱动服务启动后，主测试进程进入：
```
0024:trace:seh:RtlInitializeExtendedContext2 context 000000000011F0B0, context_flags 0x100000, context_ex 000000000011FC68, compaction_mask ffffffffffffffff.
0024:trace:process:NtQueryInformationProcess (0xffffffffffffffff,0x00000025,0x11ef70,0x00000040,(nil))
0024:trace:loaddll:build_module Loaded L"C:\\vk_enum_x64.exe" at 0000000140000000: native
0024:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\ntdll.dll" at 000000DFFFE30000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFC0F0000: builtin
```
紧接着，`elfuse` 运行时的 vCPU 看门狗触发强行中断：
```
13:05:05 ERROR src/syscall/proc.c:4881: elfuse: vCPU execution timed out after 10s
13:05:05 ERROR src/syscall/proc.c:4887: elfuse: timeout state: PC=0x20011e804 CPSR=0x20000000
13:05:05 ERROR src/syscall/proc.c:4898: elfuse: ESR_EL1=0x56000000 FAR_EL1=0x0 ELR_EL1=0x20016a63c SCTLR_EL1=0x34d0d985

╔══════════════════════════════════════════════════════════╗
║                   elfuse crash report                    ║
╚══════════════════════════════════════════════════════════╝

## Environment
- elfuse version: 8612033-dirty
- macOS: 27.0.1 (Darwin 27.0.0)
- hardware: Apple M4

## Crash
- type: TIMEOUT

## Binary
- path: /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/wine-preloader
- sysroot: /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case
- cmdline: /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/wine-preloader /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/wine C:\vk_enum_x64.exe

## Memory layout
guest_size  = 0x10000000000 (1048576 MB, 40-bit IPA)
brk         = 0x1000000 .. 0x1200000
mmap RW     = 0x200000000 .. 0x200e00000 (next 0x201145000)
mmap RX     = 0x10000000 .. 0x10200000 (next 0x10066000)
interp_base = 0xfd00000000  mmap_limit = 0xfc00000000
nregions    = 134  hvf_segments = 7
ttbr0       = 0xfcff010000
```
- **现场分析**：
  1. `wine-preloader` 在加载 `libarm64ecfex.dll` 之后，停留在 guest 地址 `PC=0x20011e804` 超过 10 秒（`proc.c:4881` 默认看门狗周期），导致进程被 `CRASH_TIMEOUT`（退出码 124）强行终止；
  2. 目标测试程序 `C:\vk_enum_x64.exe` 的标准输出为空（未触达 `Step 1`，未执行后续 `vkCreateInstance`）；
  3. 由于进程在触达 Vulkan 调用前被看门狗中断，未观测到，映射/异常是否发生未知，`libbadalloc_trace.so` 未触发输出。

---

## 5. 核心缺项与后续推进建议

1. **唯一受控运行纪律**：严格遵守规范，未在此后尝试未经批准的重试；如实记录本次运行停滞于 FEX 加载后的事实（`NO_TRACE`），不伪造成功，不掩盖看门狗中断。
2. **拦截器覆盖范围审定**：
   - 静态证明选中的 `libLLVM.so.23.1` 经由 `_ZSt17__throw_bad_allocv` 抛出异常；
   - 此项作为静态符号边界记录，不作排他性因果推导，不作为必然绕过的自动推论；
3. **下阶段推进建议（非直接重跑图形循环）**：
   - 遵照 Lead 架构指引，下阶段**不再直接重复庞大的 Wine + Vulkan 图形循环**；
   - 优先开展：
     a) **C++ logger 初始化阶段 markers**：在构造函数与注入入口添加轻量可观测打点，证实诊断库在宿主环境与 FEX 运行时的加载就绪状态；
     b) **Bare FEX 配对对照实验 (bare FEX paired control)**：脱离庞大的桌面与视窗驱动依赖，在裸 FEX 环境下单独验证 x64 PE 的跨架构加载与异常拦截能力。
4. **能力与环境边界**：
   - 虚拟 X11 无头桌面与 `lab/.s` 中继已证实能实现隔离访问控制；
   - 本实验属于 Linux 用户态兼容层上的软件虚拟化探索，**绝不代表真实的 macOS Metal 硬件图形加速或原生 Steam 客户端的集成贯通**。
