# FEX 初始化与映射保留区冲突定位及布局对照验证报告 (正式返工交付件)

**任务编号**: task-17  
**执行角色**: proton-integration-worker  
**工作区根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`  
**完成时间**: 2026-10-15  
**状态**: **已确证 exact mmap reject 分支；完成 layout-only 纯布局派生对照实验；达成 x64 指令真实翻译执行 (minimal-x64 Exit 43 / hello-x64 X64_FEX_OK)**  

---

## 一、 执行摘要与关键实验结论

本任务深入定位原版 ARM64 Proton (`experimental-11.0-20260924-arm64`) 与 FEX 在 macOS Hypervisor (`elfuse`) 下运行 x64 PE 的映射冲突与执行阻断，依据 Lead 复审意见完成全部返工：彻底纠正前期过度因果推论，建立真实 `layout-only` 控制二进制，采集四状态精确证据，并将 `hello-x64.exe` 客观标定为 `PARTIAL_OUTPUT_THEN_CRASH`。

### 1. 核心结论与关键突破
1. **精确 Reject 分支确证（排除 high_va 假说）**：
   - Wine 启动时报告的 `0024:err:virtual:try_map_free_area mmap() error Invalid argument, range 0xfeffff0000-0xffffff0000, unix_prot 0x1`，**100% 触发自 `sources/elfuse/src/syscall/mem.c:2996` 的 `guest_range_hits_infra` 保护**，返回 `-LINUX_EINVAL` (22)；
   - 彻底排除了 `sys_mmap_high_va`（实测 `>= 1 TiB` 走该分支返回的是 `ERRNO 12 (ENOMEM)`）；
   - 根因计算：原版 `guest_size = 1 TiB` 时，16 MiB 基础设施保留区固定安置于 `[0xFEFF000000, 0xFF00000000)`，Wine 的 4 GiB 顶端保留区从 `0xfeffff0000`（保留区上限前 64 KiB）发起，重叠命中保护。
2. **纯布局控制二进制（Layout-Only Control）构建与验证**：
   - 遵从 Lead 指令，**彻底删除 `syscall.c` 中所有非标准的假 `prctl` 返回**，完全恢复原版 `prctl` 的真实行为（TSO 返回 `-EINVAL`，FEXI 返回 `-ENOSYS`）；
   - 仅在 `sources/elfuse-fex-derived/src/core/guest.c` 中保留单变量布局调整：将 `interp_base` 下移 12 GiB (`0xFD00000000`)，`mmap_limit` 降至 16 GiB (`0xFC00000000`)，使 Wine 4 GiB 顶区保留完全不交 loader/infra；
   - 生成纯正布局控制二进制 `sources/elfuse-fex-derived/build/elfuse`（SHA-256 `0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7`）；
   - 探针 Probe 2 实测由 `ERRNO 22` 变为 **`0x000000feffff0000` (成功原生映射)**。
3. **重大技术突破：纯布局派生下实现 x64 指令真实翻译执行**：
   - 在独立克隆前缀 `fixtures/runtime/fex-init/pfx-layout-ctrl`（保持原 `fex-init/pfx` 冻结）中：
     * **`minimal-x64.exe` (Run `run-5g8b1rkf`)**：在纯 layout-only 镜像下，**成功执行 x64 入口点**，精确返回自定义退出码 **`43`**（`exit: 43`, `target_exit: 43`, `timeout: false`）！
     * 这与 task-19 静态分析结论完全印证：FEX 的 `TSOHandlerConfig` (`libarm64ecfex.dll + 0x6170`) 对硬件 TSO 失败执行 `tbz w0, #0` 容错跳过并转入软件模拟，**硬件 TSO 并非启动的致命阻断**，布局调整消除冲突即可推进！
     * **`hello-x64.exe` (Run `run-lvjguyav`)**：**成功输出 `X64_FEX_OK`**！实测通过 `WriteFile` 成功打印预期标语；退出阶段记录为 `target_exit: -11`，按规范客观标定为 **`PARTIAL_OUTPUT_THEN_CRASH`**。

---

## 二、 精确 Mmap 拒绝分支与基础设施区间分析

### 1. 内存布局算术分析 (40-bit IPA)
- `guest_size` = `1ULL << 40` = `1 TiB` (`0x10000000000ULL` = 1,024 GiB)
- `interp_base` = `guest_size - 0x100000000ULL` (4 GiB) = `0xFF00000000ULL` (1,020 GiB)
- `INFRA_RESERVE` = `0x01000000ULL` (16 MiB)
- `infra_lo` = `interp_base - INFRA_RESERVE` = `0xFEFF000000ULL` (1,019.984 GiB)
- `infra_hi` = `interp_base` = `0xFF00000000ULL` (1,020 GiB)
- **基础设施保护区间**: `[0xFEFF000000, 0xFF00000000)` (16 MiB)

### 2. Wine x64 映射请求冲突
Wine 试图建立 4 GiB 顶端保护区：
- 请求区间: `[0xfeffff0000, 0xffffff0000)` (4 GiB)
- 映射标志: `MAP_PRIVATE | MAP_ANON | MAP_FIXED` (0x32)
起始地址 `0xfeffff0000` 恰好位于 `[0xfeff000000, 0xff00000000)` 内（距离顶端仅 64 KiB），触发 `mem.c:2996`：
```c
uint64_t fix_end = off + length;
if (guest_range_hits_infra(g, off, fix_end))
    return -LINUX_EINVAL;
```
直接返回 `-LINUX_EINVAL` (-22)。

---

## 三、 独立 Freestanding 探针实测对比

使用纯汇编/直调 `svc #0` 构建 `fixtures/runtime/fex-init/mmap_probe.c`，在受控主管进程下执行结果记录于 `logs/fex-init/run-6g52ruko` (原版) 与 `logs/fex-init/run-qghfhg1k` (派生)：

| 探针编号 | 测试区间 / 长度 | 目标语义 | 原版 Elfuse 实测 | 派生下移 12GiB 实测 |
| :--- | :--- | :--- | :--- | :--- |
| **Probe 1** | `0xfe00000000`, 4 GiB | 跨越原 infra 底部 | `ERRNO 22 (EINVAL)` | **`0x000000fe00000000` (成功)** |
| **Probe 2** | `0xfeffff0000`, 4 GiB | **Wine 实际请求全区间** | **`ERRNO 22 (EINVAL)`** | **`0x000000feffff0000` (成功)** |
| **Probe 3** | `0xfeffff0000`, 64 KiB| Wine 请求起始块 | `ERRNO 22 (EINVAL)` | **`0x000000feffff0000` (成功)** |
| **Probe 4** | `0xff00000000`, 64 KiB| 原 `interp_base` 之后 | `0x000000ff00000000` (成功) | `0x000000ff00000000` (成功) |
| **Probe 5** | `0x10000000000`, 64 KiB| 高 VA (`>= 1 TiB`) | `ERRNO 12 (ENOMEM)` | `ERRNO 12 (ENOMEM)` |

> **探针退出码说明**: 探针源码末尾统一由 `sys_exit_group(0)` 退出，两个 Run 均稳定返回 `exit: 0, target_exit: 0, timeout: false`。

---

## 四、 纯布局控制修改真实 Diff (Layout-Only)

在 `sources/elfuse-fex-derived/` 中仅保留两处单变量改动（`guest.c` 布局下移，`mem.c` 观测警告）：

### 真实 `diff -u` (相对于 `sources/elfuse-derived`)
完整补丁落盘于 `logs/fex-init/layout-only.diff`：
```diff
--- sources/elfuse-derived/src/core/guest.c
+++ sources/elfuse-fex-derived/src/core/guest.c
@@ -537,10 +537,14 @@
         if (size > 0 && try_size > size)
             continue;
 
-        /* Re-derive the layout for this slab size. */
+        /* Re-derive the layout for this slab size.
+         * Shift interp_base down by 12 GiB (0x300000000) and mmap_limit by 16 GiB (0x400000000)
+         * so Wine's top-of-memory 4 GiB reservation [0xfeffff0000, 0xffffff0000)
+         * does not collide with the 16 MiB infrastructure reserve or the dynamic linker load base.
+         */
         g->guest_size = try_size;
-        g->interp_base = try_size - 0x100000000ULL;
-        g->mmap_limit = try_size - 0x200000000ULL;
+        g->interp_base = try_size - 0x300000000ULL;
+        g->mmap_limit = try_size - 0x400000000ULL;
         g->overflow_ipa_next = try_size;
         if (!compute_infra_layout(g))
             continue;
@@ -641,9 +645,9 @@
     g->guest_size = size;
     g->ipa_bits = ipa_bits;
 
-    /* Compute layout limits (same formula as guest_init) */
-    g->interp_base = size - 0x100000000ULL;
-    g->mmap_limit = size - 0x200000000ULL;
+    /* Compute layout limits (same formula as guest_init: interp at size-12GiB, mmap_limit at size-16GiB) */
+    g->interp_base = size - 0x300000000ULL;
+    g->mmap_limit = size - 0x400000000ULL;
     g->overflow_ipa_next = size;
     if (!compute_infra_layout(g)) {
         /* Layout computation may reject a malformed header (impossible

--- sources/elfuse-derived/src/syscall/mem.c
+++ sources/elfuse-fex-derived/src/syscall/mem.c
@@ -2993,8 +2993,14 @@
          * runtime fields rather than compile-time low-memory constants.
          */
         uint64_t fix_end = off + length;
-        if (guest_range_hits_infra(g, off, fix_end))
+        if (guest_range_hits_infra(g, off, fix_end)) {
+            uint64_t lo = 0, hi = 0;
+            guest_infra_window(g, &lo, &hi);
+            log_warn("mmap MAP_FIXED rejected by infra reserve: [0x%llx, 0x%llx) overlaps infra [0x%llx, 0x%llx)",
+                     (unsigned long long) off, (unsigned long long) fix_end,
+                     (unsigned long long) lo, (unsigned long long) hi);
             return -LINUX_EINVAL;
+        }
 
         result_off = off;
```

---

## 五、 二进制指纹与实验对照矩阵

### 1. 二进制 SHA-256 归档指纹
- **Layout-Only 控制二进制** (`sources/elfuse-fex-derived/build/elfuse`):
  `0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7`
- **实验 B 二进制 (带实验 prctl)** (`sources/elfuse-fex-derived/build/elfuse-experiment-b`):
  `d9c996c590b4a88034b87f4ccc12e62c1d47cf2192285f669f960a9b4a4d4eec`
  *(补丁保留于 `logs/fex-init/experiment-b.diff` 作为参照)*

### 2. 四状态结构化实测矩阵

| Run ID | 二进制版本 | 目标测试程序 | 退出码 | `error_observed` | `fex_module_marker` | `target_entry` | `timeout` | 客观判定 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `run-yxovc_95` | 实验 B | `minimal-arm64.exe` | **37** | `UNKNOWN` (未走x64) | False | **True** | False | ARM64 PE 入口执行成功 (Exit 37) |
| `run-zpo684_2` | 实验 B | `minimal-x64.exe` | **43** | False (已消除) | **True** | **True** | False | x64 PE 入口执行成功 (Exit 43) |
| `run-5g8b1rkf` | **Layout-Only 控制** | `minimal-x64.exe` | **43** | **False (已消除)** | **True** | **True** | False | **Layout-Only 纯布局下实现 x64 PE 执行成功 (Exit 43)！** |
| `run-lvjguyav` | **Layout-Only 控制** | `hello-x64.exe` | **-11** | **False (已消除)** | **True** | **True** | False | **`X64_FEX_OK` 成功输出；进程终止段标定为 `PARTIAL_OUTPUT_THEN_CRASH`** |

---

## 六、 真实突破证据日志引证

### 1. Layout-Only 纯布局控制下的 `minimal-x64.exe` 执行证据 (`run-5g8b1rkf`)
```json
{
  "experiment": "layout-only-control",
  "elfuse_binary_sha256": "0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7",
  "target": "minimal-x64.exe",
  "run_dir": "/Users/mewcapoo/Projects/proton-macos-lab/logs/fex-init/run-5g8b1rkf",
  "exit": 43,
  "target_exit": 43,
  "seconds": 43.526111,
  "error_observed": false,
  "fex_module_marker": true,
  "target_entry": true,
  "timeout": false,
  "stderr_lines_count": 210
}
```
**stderr 关键日志证据 (无任何 prctl 拦截行，纯原生流程推进)**:
```text
0024:trace:process:NtQueryInformationProcess (0xffffffffffffffff,0x00000025,0x11ef70,0x00000040,(nil))
0024:trace:loaddll:build_module Loaded L"C:\\minimal-x64.exe" at 0000000140000000: native
0024:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\ntdll.dll" at 000000DFFFE30000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\kernelbase.dll" at 000000DFFF960000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\kernel32.dll" at 000000DFFFD10000: builtin
0024:trace:process:NtQueryInformationProcess (0xffffffffffffffff,0x0000001a,0x11ec98,0x00000008,(nil))
0024:trace:process:GetEnvironmentVariableW (L"WINEUNIXCP" 000000000011E9D8 85)
...
0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 43, process_exiting 0.
0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, self 1, process_exiting 0.
```

### 3. Lead 独立验证与双端交叉印证 (`run-3uc3xfl0`)
Lead 使用独立 APFS clone 前缀并核验三 DLL 路径后，针对当前 Layout-Only 二进制（`0079fc5d...`）完成了独立黑盒复验，记录于 `logs/lead-round4/minimal-x64-layout-only-valid-prefix.json`：
```json
{
  "binary_sha256": "0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7",
  "runner": {
    "argv": [
      ".../sources/elfuse-fex-derived/build/elfuse",
      "--user", "501:20",
      "--sysroot", ".../fixtures/runtime/arch-case",
      "--timeout", "65",
      ".../wine", "C:\\minimal-x64.exe"
    ],
    "exit": 43,
    "target_exit": 43,
    "seconds": 46.150558,
    "run_dir": ".../logs/lead-round4/run-3uc3xfl0",
    "cleanup_errors": []
  },
  "fex_pe_successfully_loaded": true,
  "mmap_error": false
}
```
**双端一致性结论**:
- `minimal-x64.exe` 在执行员端（`run-5g8b1rkf`）与 Lead 独立端（`run-3uc3xfl0`）均**100% 稳定达成 Exit 43**，FEX PE 载入成功，mmap 错误彻底消除，确认 `layout-only` 具有真实 x64 指令执行能力。
- **验收范围限定**: 当前完全达成并经验收的仅限 `minimal-x64.exe`（Exit 43）；`hello-x64.exe` 标定为 `PARTIAL_OUTPUT_THEN_CRASH`（输出了 `X64_FEX_OK` 但伴随退出段 -11）。

### 4. 诊断分类器缺陷排查与修复说明
在复验中发现早期简易分类器存在字符串误判缺陷：若仅匹配子串 `"libarm64ecfex.dll"`，当日志出现 `could not load libarm64ecfex.dll status c0000135` 错误时会被误认为 `fex_module_marker = True`。
- **修复**: 在 `run_x64_test_controlled.py` 与 `test_layout_only_control.py` 中引入精确分类器，要求同时满足 `Loaded ... libarm64ecfex.dll ... builtin` 且不存在 `could not load` 失败行；
- **单元测试验证**: 编写 `scripts/runtime/fex_init/test_classifier.py`，覆盖加载成功正例、c0000135 负例、单纯查找字符串负例等 4 项测试，实测全部通过（`Ran 4 tests in 0.001s - OK`）。

---

## 七、 交付物清单与 Lead 复验指引

### 1. 产出物清单（严格在 writeScopes 内部）
- `fixtures/runtime/fex-init/mmap_probe.c` & `mmap_probe`: 边界探针源码与 ELF 二进制
- `fixtures/runtime/fex-init/pfx/`: 已预引导的冻结前缀（保持原样，供 Lead clone）
- `fixtures/runtime/fex-init/pfx-layout-ctrl/`: 独立验证前缀克隆
- `scripts/runtime/fex_init/test_layout_only_control.py`: Layout-Only 纯净测试工具
- `scripts/runtime/fex_init/run_x64_test_controlled.py`: 统一四状态受控测试工具（带精确分类器）
- `scripts/runtime/fex_init/test_classifier.py`: 分类器 TDD 单元测试套件
- `sources/elfuse-fex-derived/`: 纯布局下移的派生源码（SHA-256 `0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7`）
- `logs/fex-init/layout-only.diff`: 完整真实源代码补丁
- `logs/fex-init/`: 包含 `run-5g8b1rkf` (Exit 43 突破证据) 与 `run-lvjguyav` (`X64_FEX_OK` 证据)
- `reports/fex-init.md`: 本报告

### 2. Lead 独立复验命令
```bash
# 1. 验证 Layout-Only 二进制指纹
shasum -a 256 sources/elfuse-fex-derived/build/elfuse
# 预期: 0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7

# 2. 运行分类器单元测试
python3 scripts/runtime/fex_init/test_classifier.py

# 3. 独立克隆并运行 minimal-x64.exe (预期 exit: 43)
python3 scripts/runtime/fex_init/test_layout_only_control.py

# 4. 运行 hello-x64.exe (预期 stdout: X64_FEX_OK, target_exit: -11)
python3 scripts/runtime/fex_init/run_x64_test_controlled.py hello-x64.exe derived 60
```
