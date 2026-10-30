# 原版 Proton x64 PE 与 FEX 真实运行推进报告

**任务编号**: task-14  
**执行角色**: proton-integration-worker  
**工作区根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`  
**完成时间**: 2026-10-15  
**状态**: **技术目标部分达成（ARM64 PE 入口执行成功 Exit 37；x64 PE 翻译受阻，定位于 FEX 模块初始化/高地址映射层）**  

---

## 一、 执行摘要与关键结论

本任务推进基于公开 seed 原版 Valve ARM64 Proton (`experimental-11.0-20260924-arm64`) 与 macOS Hypervisor.framework (`elfuse`) 真实运行 Windows PE 的集成诊断，目标是启动最小 x64 PE 并定位首个 Windows 载入阻断。

### 核心结论
1. **Windows x64 PE 目标状态**：**尚未成功（NOT_RUN / BLOCKED AT FEX INIT）**。
   - 目标程序 `fixtures/runtime/pe/hello-x64.exe` 未能输出 `X64_FEX_OK`，亦未返回 exit 0。
   - **不是停滞在 Wine 引导层，而是成功到达 FEX 模块载入边界**：在消除前缀断链后，Wine loader 成功加载 `C:\minimal-x64.exe` 与 `C:\hello-x64.exe`，并触发 `load_arm64ec_module` 成功将 5.1MB 的 FEX 翻译引擎 `C:\windows\system32\libarm64ecfex.dll` 映射至内存（`0x000000FFFFC10000: builtin`）。随后进程停滞于 FEX 内部初始化，伴随 `elfuse` 拒绝高地址空间映射（`0xfeffff0000-0xffffff0000`）错误。
2. **底层 Wine ARM64 PE 执行基线**：**重大突破（VERIFIED / 真实入口执行成功）**。
   - 构造仅导入 `ntdll!NtTerminateProcess` 的控制样本 `minimal-arm64.exe`，在独立前缀 `fixtures/runtime/pe-worker/pfx` 中顺利通过 `wineboot` 引导，Wine 原生加载并执行 `mainCRTStartup`，调用 `NtTerminateProcess((HANDLE)-1, 37)` 退出，**返回确凿的自定义退出码 `37`**（Run `run-z5ilwjrt`，Exit: 37, Timed out: False）。
   - **这是本实验室内首个由原版 Proton Wine 在 macOS HVF 下完整加载并真实执行 Windows PE 入口点的可复现实测证据**。
3. **关键阻断排除与因果确认**：
   - 确认历史 `wine: could not load kernel32.dll, status c0000135` 并非 Wine 核心功能故障，而是因为 `default_pfx_arm64` 内部 766 个相对软链接（如 `system32/kernel32.dll -> ../../../../../lib/wine/...`）在移动到不同目录深度的独立前缀后发生路径断裂。修复对应目标链接后，Wine 即可顺利载入 `kernel32.dll` 与 `libarm64ecfex.dll`。

---

## 二、 实验样本构建与审计证据

为精确剥离 FEX 指令翻译与 Wine 前缀引导、Win32 子系统（kernel32/services）的复杂交织，本任务采用 LLVM 工具链纯手工构建了仅导入 `ntdll.dll` 的最小双架构 PE 样本。

### 1. 源码与构建定义
- **源码路径**: `fixtures/runtime/pe-worker/src/minimal.c`
```c
__declspec(dllimport) long __stdcall NtTerminateProcess(void *handle, long status);

void mainCRTStartup(void) {
#ifdef __aarch64__
    NtTerminateProcess((void *)-1, 37);  // ARM64 专有预期退出码
#else
    NtTerminateProcess((void *)-1, 43);  // x64 专有预期退出码
#endif
}
```
- **构建方式**: 使用 macOS 现存的 Homebrew `llvm@22` 与 `lld@21`：
```bash
LLVM_BIN="/opt/homebrew/opt/llvm@22/bin"
LLD_BIN="/opt/homebrew/opt/lld@21/bin"

# 1. 生成纯 ntdll 导入库
"$LLVM_BIN/llvm-dlltool" -m arm64 -d ntdll.def -l ntdll-arm64.lib
"$LLVM_BIN/llvm-dlltool" -m i386:x86-64 -d ntdll.def -l ntdll-x64.lib

# 2. 编译并链接 ARM64 控制样本
"$LLVM_BIN/clang" -target aarch64-pc-windows-msvc -c minimal.c -o minimal-arm64.obj -nostdlib -O2
"$LLD_BIN/lld-link" /subsystem:console /entry:mainCRTStartup /nodefaultlib /out:minimal-arm64.exe minimal-arm64.obj ntdll-arm64.lib

# 3. 编译并链接 x64 测试样本
"$LLVM_BIN/clang" -target x86_64-pc-windows-msvc -c minimal.c -o minimal-x64.obj -nostdlib -O2
"$LLD_BIN/lld-link" /subsystem:console /entry:mainCRTStartup /nodefaultlib /out:minimal-x64.exe minimal-x64.obj ntdll-x64.lib
```

### 2. 静态审计 (`llvm-readobj` 与反汇编证据)
执行 `llvm-readobj --coff-imports` 实测输出：
```text
File: fixtures/runtime/pe-worker/minimal-arm64.exe
Format: COFF-ARM64, Arch: aarch64
Import {
  Name: ntdll.dll
  Symbol: NtTerminateProcess (0)
}

File: fixtures/runtime/pe-worker/minimal-x64.exe
Format: COFF-x86-64, Arch: x86_64
Import {
  Name: ntdll.dll
  Symbol: NtTerminateProcess (0)
}
```

反汇编确认入口逻辑：
- `minimal-arm64.exe`:
  ```asm
  140001004: mov  x0, #-0x1        // handle = (HANDLE)-1
  140001008: mov  w1, #0x25        // exit_code = 37 (0x25)
  14000100c: ldr  x2, [x2, #0x38]  // IAT NtTerminateProcess
  140001010: br   x2
  ```
- `minimal-x64.exe`:
  ```asm
  140001000: movq $-0x1, %rcx      // handle = (HANDLE)-1
  140001007: movl $0x2b, %edx      // exit_code = 43 (0x2b)
  14000100c: jmpq *0x1025(%rip)    // IAT NtTerminateProcess
  ```

---

## 三、 实验矩阵与实测日志分析

在独立前缀 `fixtures/runtime/pe-worker/pfx`（隔离 c: 与 z: 驱动器映射，不污染已有 `seed-prefix`）中，通过受控 supervisor runner 开展了多轮单变量实验：

| Run ID | 目标程序 | 底层 elfuse | 软链接状态 | 退出码 | 实际耗时 | 关键现象与结论 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `run-jt0n8dm_` | `wine --version` | 原版 | N/A | **0** | 0.5s | 组件基线可用，回显 `wine-11.0` |
| `run-840ge3ed` | `hello-x64.exe` | 原版 | 未修复相对断链 | **-15 (124)** | 30.0s (超时) | 捕获到 wineboot 中 explorer 多次创建失败循环 |
| `run-jxn3h1fv` | `minimal-arm64.exe` | 原版 | 未修复断链 | **53 (0x35)** | 27.8s | wineboot 完成退出 0；加载 PE 后因断链报 `could not load kernel32.dll, status c0000135` |
| `run-z5ilwjrt` | `minimal-arm64.exe` | 原版 | **已修复软链接** | **37** | 29.7s | **成功！** wineboot exit 0；主进程顺利加载并**真实执行入口，退出码 37** |
| `run-itm388nh` | `minimal-x64.exe` | 原版 | **已修复软链接** | **124** | 35.1s (超时) | wineboot exit 0；**成功载入 libarm64ecfex.dll**，但随后停滞在 FEX 内部 |
| `run-lwywifbc` | `minimal-x64.exe` | **派生 (futex补丁)**| **已修复软链接** | **124** | 35.1s (超时) | 行为与原版一致，同在载入 `libarm64ecfex.dll` 后停滞 |
| `run-nfst2nym` | `hello-x64.exe` | 原版 | **已修复软链接** | **124** | 35.1s (超时) | 完整 x64 PE 同在载入 `libarm64ecfex.dll` 后停滞 |

---

## 四、 关键突破与详细执行追踪

### 1. ARM64 PE 成功执行全链路 (`run-z5ilwjrt`)
在修复 `system32/kernel32.dll` 与 `system32/kernelbase.dll` 指向实际原版库后，执行命令：
```bash
elfuse --user 501:20 --sysroot fixtures/runtime/arch-case --timeout 30 \
  fixtures/runtime/proton-derived/files/bin-arm64/wine C:\minimal-arm64.exe
```

**原始 stderr 关键追踪 (`logs/runtime-worker/run-z5ilwjrt/stderr.log`)**:
```text
002c:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 0, process_exiting 1.
0024:trace:process:NtQueryInformationProcess (0xffffffffffffffff,0x00000025,0x11fb50,0x00000040,(nil))
0024:trace:loaddll:build_module Loaded L"C:\\minimal-arm64.exe" at 0000000140000000: native
0024:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\ntdll.dll" at 000000DFFFE30000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\kernelbase.dll" at 000000DFFF960000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\kernel32.dll" at 000000DFFFD10000: builtin
0024:trace:process:NtQueryInformationProcess (0xffffffffffffffff,0x0000001a,0x11f8a8,0x00000008,(nil))
0024:trace:process:GetEnvironmentVariableW (L"WINEUNIXCP" 000000000011F5D8 85)
0024:trace:process:NtQueryInformationProcess (0xffffffffffffffff,0x00000007,0x11fae0,0x00000008,(nil))
0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 37, process_exiting 0.
0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, self 1, process_exiting 0.
```
- **分析**:
  1. `002c` (`wineboot.exe`) 顺利完成系统前缀初始化并干净退出（`exit_code 0`）。
  2. 主进程 `0024` 被唤醒，`LdrLoadDll` 识别 `C:\minimal-arm64.exe` 为 native AArch64 PE。
  3. Win32 初始化链加载了已修复的 `ntdll.dll`、`kernelbase.dll` 和 `kernel32.dll`。
  4. 进程跳转至 `mainCRTStartup`，执行 `NtTerminateProcess((HANDLE)-1, 37)`。
  5. `0024` 进程以 `exit_code 37` 终止，runner 记录 `exit: 37, target_exit: 37`。

### 2. x64 PE 的精确阻断边界 (`run-itm388nh`)
运行架构相同的 x64 版本 `C:\minimal-x64.exe`：
```text
002c:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 0, process_exiting 1.
0024:err:virtual:try_map_free_area mmap() error Invalid argument, range 0xfeffff0000-0xffffff0000, unix_prot 0x1.
0024:trace:process:NtQueryInformationProcess (0xffffffffffffffff,0x00000025,0x11ef70,0x00000040,(nil))
0024:trace:loaddll:build_module Loaded L"C:\\minimal-x64.exe" at 0000000140000000: native
0024:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\ntdll.dll" at 000000DFFFE30000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000FFFFC10000: builtin
```
- **架构因果分析**:
  1. Wine 成功识别到目标为 x86-64 二进制，触发 `load_arm64ec_module`。
  2. Wine 顺利将官方 5.1MB 的 `libarm64ecfex.dll` 映射至内存 `0x000000FFFFC10000`。
  3. **此时已跨越 Wine 前缀引导阶段，真正触达 FEX 边界**。
  4. 阻断停滞发生在 `libarm64ecfex.dll` 载入之后。核心嫌疑机制包括：
     - **高地址内存映射受阻**: 载入 PE 前报告 `mmap() error Invalid argument, range 0xfeffff0000-0xffffff0000`。在 `sources/elfuse/src/syscall/mem.c`（L2963）中，地址 `>= g->guest_size` 时走 `sys_mmap_high_va`，该函数对非 Rosetta guest 直接返回 `-LINUX_ENOMEM`，导致 Wine 64位虚拟内存顶端保护区分配失败。
     - **FEX 硬件辅助与系统调用缺项**: `libarm64ecfex.so` 依赖 `prctl(PR_SET_TSO)` 以及 unaligned atomic 控制；若底层虚拟化不支持，FEX JIT 内部初始化可能陷入死循环或等待。

---

## 五、 进程生命周期与安全审计

1. **主管进程模式接入**:
   - 遵照代码审查意见，废弃初期简单的 `safe_process.py`，全面复用并委托由 `steam-probe-worker` 修复后的 `scripts.backend.process.run_isolated` 及 `scripts/backend/supervisor.py`。
   - 主管进程全程持有进程组会话 Leader 身份，直到所有后代发送 `SIGTERM` / `SIGKILL` 清理完毕，彻底杜绝 child wait 回收后的 PID/PGID 复用误杀风险。
2. **实验室进程零残留实测**:
   - 经 `ps -eo pid,ppid,pgid,stat,command | grep -E "elfuse|wine"` 检查，所有运行结束后无任何背景 `elfuse`、`wine`、`wineserver` 进程残留。
3. **隔离与规范红线**:
   - 未修改 `sources/elfuse` 原始源码，未修改 `artifacts/public-proton` 原版包。
   - 所有产出限定在 `scripts/runtime/`、`fixtures/runtime/pe-worker/`、`logs/runtime-worker/` 与本报告。
   - 零账号、零凭据交互，无 git commit/push。

---

## 六、 交付物清单与后续建议

### 1. 新增与修改交付物
- `scripts/runtime/safe_process.py`: 委托至 backend process 的薄适配器。
- `scripts/runtime/test_safe_process.py`: 4 项针对 runner 行为的 TDD 单元测试。
- `scripts/runtime/run_pe_diagnostic.py` / `run_pe_comparison.py` / `run_pe_diagnostic_arm64.py`: 自动化诊断与比较脚本。
- `fixtures/runtime/pe-worker/src/`: 最小 PE 源码 (`minimal.c`) 与模块定义 (`ntdll.def`)。
- `fixtures/runtime/pe-worker/minimal-arm64.exe`: 经编译审计的 ARM64 PE（Exit 37 验证样本）。
- `fixtures/runtime/pe-worker/minimal-x64.exe`: 经编译审计的 x64 PE。
- `fixtures/runtime/pe-worker/pfx/`: 修复了相对断链的独立实验前缀。
- `logs/runtime-worker/`: 包含 `run-z5ilwjrt` (Exit 37) 与 `run-itm388nh` (FEX 边界) 的原始日志与 JSON。
- `reports/runtime-worker.md`: 本报告。

### 2. 后续工程突破路线
1. **优先修复 `elfuse` 高地址 VA 映射能力**: 放宽非 Rosetta 环境下合法的 MAP_FIXED 高地址内存分配，解决 `0xfeffff0000-0xffffff0000` 映射拒绝。
2. **FEX 模块专用追踪**: 针对 `libarm64ecfex.so` / `dll` 注入跟踪或导出更详细的 FEX 日志（如配置 `FEX_LOGLEVEL=debug` / `Config.json` 调试选项），捕获 FEX 在进入指令翻译前的具体停滞函数。
3. **保留 ARM64 PE 作为后续自动化回归的基线测试用例**。
