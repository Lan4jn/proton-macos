# Layout-Only 原版 FEX x64 真实执行独立复审报告

**报告日期**：2026-10-15  
**审查角色**：`final-lab-reviewer`（独立审查员）  
**关联任务**：`task-20`（复审layout-only原版FEX x64真实执行）  
**被审任务**：`task-17`（定位FEX初始化与映射保留区冲突及二次返工）  
**工作区根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**冻结二进制**：`sources/elfuse-fex-derived/build/elfuse`  
**冻结 SHA-256**：`0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7`  
**独立复验前缀**：`fixtures/runtime/fex-review/pfx/`（全新独立克隆，不触碰 worker/lead prefix）  
**审查归档目录**：`logs/fex-runtime-review/`  

---

## 一、 执行摘要与总体验收判定

1. **核心突破与验证事实**：
   - **真实 x64 指令翻译执行确证**：在纯净单变量布局调整（`layout-only`）的派生 `elfuse` 下，原版 ARM64 Proton + FEX 成功加载并翻译 Windows x64 PE 控制台程序。
   - **`minimal-x64.exe` 实测通过**：独立沙箱运行稳定返回目标自定义退出码 **`43`**（`exit: 43`, `target_exit: 43`, `timed_out: false`），证实 x64 入口点成功执行并正常退出。
   - **`hello-x64.exe` 实测定性为 `PARTIAL_OUTPUT_THEN_CRASH`**：标准输出成功打出 **`X64_FEX_OK`**，证明 x64 指令翻译、CRT 初始化及 Win32 控制台 I/O 均已真实执行；但进程在终止回收阶段收到 SIGSEGV，最终退出码为 **`-11`**。**绝不可等同于全部 Pass 或退出码 0**。
2. **Layout-Only 纯净性与伪能力剔除核验**：
   - 确证执行员初次返工引入的 `syscall.c`（伪造 `PR_SET_MEM_MODEL` HVF ACTLR 及 `0x46455849` FEXI return 0）已被**完全回滚剔除**（已归档至 `logs/fex-init/experiment-b.diff`）。
   - 现存二进制源码对比 `sources/elfuse-derived`，**`src/syscall/syscall.c` 保持 100% 相同（0 diff）**，仅保留 `src/core/guest.c`（布局下移）与 `src/syscall/mem.c`（日志输出），未伪造任何内核 capability。
3. **总体验收结论**：**批准通过（APPROVED AS LAYOUT-ONLY MILESTONE）**。
   - 真实记录技术突破与未解决边界（hello -11），0 伪造、0 假绿。

---

## 二、 第一阶段：规格合规与架构完整性审查（Specification Review）

### 1. 二进制冻结与源码 Diff 审计
- **二进制哈希绑定**：
  - `sources/elfuse-fex-derived/build/elfuse`
  - SHA-256：`0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7`
  - Entitlements 校验：`com.apple.security.hypervisor = true`。
- **源码单变量 Diff 核验 (`diff -ur sources/elfuse-derived sources/elfuse-fex-derived`)**：
  1. `src/core/guest.c`：
     - `interp_base` 由 `size - 4 GiB` 下移至 `size - 12 GiB` (`0xFD00000000ULL`)。
     - `mmap_limit` 由 `size - 8 GiB` 下移至 `size - 16 GiB` (`0xFC00000000ULL`)。
     - `guest_init` 与 `guest_init_from_shm` 保持公式一致，确保快照元数据一致性。
     - 该改动使 Wine 请求的 `[0xfeffff0000, 0xffffff0000)` (4 GiB) 彻底避开 16 MiB 基础设施保留区 (`[0xFEFF000000, 0xFF00000000)`)。
  2. `src/syscall/mem.c`：
     - 在 `guest_range_hits_infra` 分支中仅增加 `log_warn` 输出，未放行任何损坏映射。
  3. `src/syscall/syscall.c`：
     - **0 改动**。未对 `prctl` 进行任何伪成功绕过。

### 2. 目标 PE 程序与 FEX 组件架构鉴别
审查员对各测试程序及组件执行架构核实，结果如下：

| 目标工件路径 | 格式与架构类型 | SHA-256 校验和 | 属性判定 |
| :--- | :--- | :--- | :---: |
| `pfx/drive_c/minimal-arm64.exe` | PE32+ executable (console) **Aarch64** | `775cacf4833bfd4b614f567535e619be5bc93fc3660f0017aec2b4578368a11e` | 原生 ARM64 PE |
| `pfx/drive_c/minimal-x64.exe` | PE32+ executable (console) **x86-64** | `87406032e5b7c6546afe5fa0f03847a5e398cb4981c969604417a828ab266bc8` | **Windows x64 PE** |
| `pfx/drive_c/hello-x64.exe` | PE32+ executable (console) **x86-64** | `26cccc8ced8bb2037b2589f7d7af204ad98a27c4f7919bc7fc0dc21e032be9e7` | **Windows x64 PE** |
| `libarm64ecfex.so` (UnixLib) | ELF 64-bit LSB shared object, **aarch64** | `83c88a5dd3065d66cde1c9d653e6dc602eca2fe56227ed2974bf610f70a2b0fd` | 原版 Valve FEX Unix |
| `libarm64ecfex.dll` (PE) | PE32+ executable (DLL) (GUI) **coff-arm64ec** | `ca9b1de29555f27f7c56a161d35b95a1077f233a877765fa7aef610ab6bb8e5e` | 原版 Valve FEX DLL |

确证 `minimal-x64.exe` 与 `hello-x64.exe` 为真实的 64 位 x86 Windows 二进制，绝非 ARM64 冒充。

### 3. 前缀隔离与相对软链接深度保证
- Wine 前缀 `drive_c/windows/system32/` 内部的 `ntdll.dll`、`libarm64ecfex.dll`、`kernel32.dll` 使用了 5 层相对软链接：
  `../../../../../proton-derived/files/lib/wine/aarch64-windows/<name>.dll`
- 审查员严格在 `fixtures/runtime/fex-review/pfx/` 建立独立克隆，确保相对链深度与原 `fixtures/runtime/fex-init/pfx/` 一致，三项链接全部解析有效（`exists: True`），不污染任何既有前缀。

---

## 三、 第二阶段：代码质量与测试框架缺陷分析（Quality Review）

### 1. `fex_module_marker` 假阳性（False-Positive）漏洞
- **缺陷代码位置**：`scripts/runtime/fex_init/run_x64_test_controlled.py:63`
  ```python
  fex_module_marker = any("libarm64ecfex.dll" in l for l in lines)
  ```
- **审查缺陷分析**：该行仅简单判断单行是否包含子串 `"libarm64ecfex.dll"`。若 Wine 运行过程中发生错误（如 `Loading library libarm64ecfex.dll failed` 或 `could not load libarm64ecfex.dll`），此判断依然会评估为 `True`，产生严重的测试假阳性。
- **真实日志核验**：经检查独立复验日志，实际成功加载时的 Wine 日志特征为：
  `0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin`
- **整改建议**：必须严格重构成包含 `build_module Loaded` 与 `builtin` 的联合断言，不可依赖宽泛子串。

### 2. `hello-x64.exe` 终止行为定性：`PARTIAL_OUTPUT_THEN_CRASH`
- **现象分析**：
  - 标准输出完整记录：`X64_FEX_OK\n`；
  - stderr 记录到 Wine 内部调用：`0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 0, process_exiting 1`；
  - 宿主进程最终退出状态：`exit: -11`, `target_exit: -11`（SIGSEGV 崩溃）。
- **审查定性**：
  - **`NtTerminateProcess` 日志 ≠ 进程 Exit 0**：`NtTerminateProcess` 仅是 Windows NT 子系统的退出发起点，后续仍需经由 Wine/FEX 析构、线程清理及 Linux 宿主系统调用退出。
  - 进程在资源回收或线程销毁阶段发生段错误，因此严禁判定为“全绿通过”，必须准确归类为 **`PARTIAL_OUTPUT_THEN_CRASH`**。
  - 资源回收阶段的崩溃根因（可能是 FEX 线程退出、unmap 冲突或析构竞争）目前**尚未证实**，不可作过度推断。

---

## 四、 独立实测证据矩阵（Verification Matrix）

审查员在隔离沙箱环境中，使用冻结二进制 `sources/elfuse-fex-derived/build/elfuse`（SHA-256 `0079fc5d...`）与独立前缀 `fixtures/runtime/fex-review/pfx` 执行全量独立复验，原始证据归档于 `logs/fex-runtime-review/`：

| 测试项 | 目标程序与参数 | 关键观测点与预期 | 实测输出 / 状态码 | 耗时 | 归档日志与证据 |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **1. 基础映射探针** | `mmap_probe` | 验证 Wine 4 GiB 顶端映射是否避开 infra 保留区 | `Probe 2: 0xfeffff0000 (OK)`<br>`Probe 3: 0xfeffff0000 (OK)` | 0.03s | 终端实测回显 (Exit 0) |
| **2. 原生 ARM64 PE** | `minimal-arm64.exe` | 验证前缀与原生 PE 入口执行 | **Exit 37** (target_exit 37, timeout=False) | 31.02s | `logs/fex-runtime-review/run-s6hoiybn/` |
| **3. x64 最小 PE** | `minimal-x64.exe` | **验证 x64 指令翻译与自定义退出码** | **Exit 43** (target_exit 43, timeout=False) | 46.41s | `logs/fex-runtime-review/run-l84rpgk3/` |
| **4. x64 标准输出 PE** | `hello-x64.exe` | **验证 x64 I/O 与退出段真实状态** | **stdout: `X64_FEX_OK`**<br>**Exit -11 (PARTIAL_CRASH)** | 41.02s | `logs/fex-runtime-review/run-b0z787ur/` |
| **5. 历史基线回归** | `scripts/elfuse/run_all_baseline.sh` | 验证底层汇编/JIT/fork/glibc 零回归 | **7/7 全部 PASS** (Exit 0) | 0.22s | `logs/elfuse/run.3SbyeA/` |
| **6. 跨进程 Futex 回归** | `sources/elfuse-derived/tests/test_futex_abi_suite` | 验证 task13 跨进程同步逻辑保持 | **17 项断言全部 PASS** (Exit 0) | 0.15s | 终端实测回显 (Exit 0) |

---

## 五、 关键证据片段引证

### 1. `minimal-x64.exe` 真实翻译与 Exit 43 证据 (`run-l84rpgk3`)
```text
0024:trace:loaddll:build_module Loaded L"C:\\minimal-x64.exe" at 0000000140000000: native
0024:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\ntdll.dll" at 000000DFFFE30000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\kernelbase.dll" at 000000DFFF960000: builtin
0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\kernel32.dll" at 000000DFFFD10000: builtin
0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 43, process_exiting 0.
0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, self 1, process_exiting 0.
```
- Supervisor 记录：`"exit": 43, "target_exit": 43, "timed_out": false`。
- 确证 x64 机器码被 FEX 成功载入、翻译，并由 CPU 正确执行了返回 43 的入口函数。

### 2. `hello-x64.exe` 真实标准输出与退出段证据 (`run-b0z787ur`)
- **`stdout.log`**:
  ```text
  X64_FEX_OK
  ```
- **`stderr.log` (终止前关键行)**:
  ```text
  0024:trace:loaddll:build_module Loaded L"C:\\hello-x64.exe" at 0000000140000000: native
  0024:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFEA90000: builtin
  0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 0, process_exiting 1.
  0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, self 1, process_exiting 1.
  ```
- Supervisor 记录：`"exit": -11, "target_exit": -11, "timed_out": false`。
- 确证标准输出打出，但宿主在终止阶段收到 SIGSEGV。

---

## 六、 交付物文件清单与最终签字

1. **审查交付物**：
   - 独立审查报告：`reports/fex-runtime-review.md`
   - 独立运行日志：`logs/fex-runtime-review/`（含 `run-s6hoiybn`、`run-l84rpgk3`、`run-b0z787ur` 之完整 stdout/stderr/meta）
   - 独立复验前缀：`fixtures/runtime/fex-review/pfx/`（完整隔离，相对链保持）
2. **审查结论签字**：
   - **审查员**：`final-lab-reviewer`
   - **判定结果**：**通过最终验收（APPROVED）**。
   - **事实定性**：确证单变量 `layout-only` 突破了 Windows x64 PE 的 FEX 翻译执行阻断（`minimal-x64.exe` 达成 Exit 43；`hello-x64.exe` 输出 `X64_FEX_OK` 后处于 `PARTIAL_OUTPUT_THEN_CRASH`）。未伪造任何系统能力。
   - **任务状态**：`task-20` 满足完工条件。
