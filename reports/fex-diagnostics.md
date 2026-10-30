# FEX 运行时诊断分类修复与边界验证报告

**报告日期**：2026-10-15  
**执行角色**：`steam-probe-worker`（运行时诊断与状态分类实现员）  
**关联任务**：`task-21`（修复 FEX 日志状态分类假阳性并补测试）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**测试日志归档**：`logs/fex-diagnostics/red.log`、`logs/fex-diagnostics/green.log`  

---

## 一、 缺陷背景与根因分析

在第四轮实验推进原版 Proton 与 FEX 执行 Windows x64 PE 过程中，Lead 独立审计发现了关键的诊断分类假阳性与状态误判：

1. **模块加载假阳性（False Positive）**：
   - 原 `scripts/runtime/fex_init/run_x64_test_controlled.py:63` 仅通过简单的子串包含检查 `any("Loaded" in l and "libarm64ecfex.dll" in l)` 来断定模块装载。
   - **真实反例复现**：在 Lead 真实运行日志 `logs/lead-round4/run-kb_ei513`（exit 53）第 199 行中，stderr 记录：
     ```text
     0024:err:module:load_arm64ec_module could not load L"C:\\windows\\system32\\libarm64ecfex.dll", status c0000135
     ```
     原代码由于未严格校验成功前缀与失败互斥，极易被探针日志或包含搜索字串的行（如 `find_exe_file looking for ...`）误导，将装载失败误报为模块加载成功。

2. **局部输出与全局成功混淆（Partial vs Whole Success）**：
   - 在 `hello-x64.exe` 的实测中，控制台 stdout 确实输出了 `X64_FEX_OK`，但进程随后在宿主层触发段错误崩溃（`target_exit: -11`，SIGSEGV）；
   - 若测试框架仅仅依据 stdout 包含 `X64_FEX_OK` 或 stderr 中捕获到的 Wine 内部追踪行：
     ```text
     0024:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 0, process_exiting 0.
     ```
     便宣布整体执行成功，则是严重的假绿（False Green）。`NtTerminateProcess` 的内部 trace 并不等同于进程在宿主 OS 层面干净退出为 0。

3. **异常状态与假绿防范**：
   - 当命令发生超时（exit 124）或进程清理异常（`cleanup_errors` 非空）时，即使目标进程自身恰好返回 0，也绝不能将其判定为 `whole_success`；
   - 当 stderr 中既没有出现已知的 mapping 错误（如 `try_map_free_area`），又尚未到达 FEX 模块加载阶段时，`error_observed` 必须诚实返回 `"UNKNOWN"`，不得假定为 `False`。

---

## 二、 修复方案与纯函数架构设计

遵循短小专注、无长 Wine 运行、零外部依赖原则，将所有解析分类逻辑封装在纯函数模块中：

### 1. 纯函数解析模块 (`scripts/runtime/fex_init/diagnostics.py`)
- **安全可导入与零 I/O 副作用**：完全解耦进程执行、磁盘 I/O 与结果分类；`classify_run_outcome` 为严格纯函数，绝不执行磁盘读取或 SHA256 哈希计算；
- **独立元数据提取 (`extract_run_context_metadata`)**：将上下文元数据采集独立为纯数据提取函数，由调用者显式传入真实路径，彻底废除硬编码的假路径；
- **严格正反例解析 (`classify_fex_module_marker`)**：
  - 正例规则：必须严格正则锚定 Wine loaddll 前缀（`loaddll:(?:build_module|build_ntdll_module)\s+Loaded\s+.*libarm64ecfex\.dll.*:\s*builtin`）；
  - 反例规则：若出现 `could not load\s+.*libarm64ecfex\.dll`，立即标记 `failure: True` 并提取 NTSTATUS（如 `c0000135`），且即使同一日志中存在加载字串，`loaded` 亦坚决置为 `False`；
  - 欺骗行过滤：如 `not Loaded ...`、`skip Loaded ...`、`looking for ...` 等绝不误报为装载成功；
- **三态错误观测 (`classify_error_observed`)**：
  - `True`：显式出现 `try_map_free_area` 或特定冲突地址（`0xfeffff0000`）；
  - `False`：FEX 模块已证实加载（证明该关键路径已绕过地址冲突）；
  - `"UNKNOWN"`：未到达或无法确证，绝不主观猜测；
- **分层状态机 (`classify_run_outcome`)**：
  - `target_entry`：验证是否到达执行入口（`minimal-arm64` 对应 exit 37，`minimal-x64` 对应 exit 43，`hello-x64` 对应 stdout 逐行精确包含 `X64_FEX_OK`）；
  - `partial_output_then_crash`：当且仅当 `target_entry=True` 但 `target_exit < 0`（特别是 `-11` 段错误）时触发；
  - `whole_success` 严格防假绿：
    - 针对 `hello-x64.exe`：必须满足 `target_entry`、总体 `exit == 0`、真实 `target_exit == 0`、未超时、无清理异常、无崩溃；
    - 针对 `minimal-x64.exe`：必须严格要求总体 `exit == 43` 且真实 `target_exit == 43`，彻底排除 `exit 124` 超时及 `exit 125` 清理异常下的假绿；
    - 针对 `minimal-arm64.exe`：必须严格要求总体 `exit == 37` 且真实 `target_exit == 37`；
  - 细分状态值：`TIMEOUT` / `CLEANUP_FAILED` / `PARTIAL_OUTPUT_THEN_CRASH` / `WHOLE_SUCCESS` / `TARGET_ENTRY_REACHED` / `FEX_MODULE_LOAD_FAILED` / `FEX_MODULE_LOADED_NO_ENTRY` / `NOT_LOADED`。

### 2. 控制运行脚本重构 (`scripts/runtime/fex_init/run_x64_test_controlled.py`)
- 重构 `run_test`，由 runner 调用 `extract_run_context_metadata` 采集当前真实环境的路径与关键 DLL 状态，并将其作为元数据显式传递给 `classify_run_outcome`；
- 保留 `if __name__ == '__main__':` 守护，保持模块安全导入特性。

---

## 三、 TDD 单元测试验证与实测证据

### 1. RED 阶段失败证据（`logs/fex-diagnostics/red.log`）
在返工中新增针对 Lead 发现边界的负例测试，真实复现了以下失败：
```text
FAIL: test_minimal_arm64_false_green_on_mismatched_overall_exit
AssertionError: True is not false : Minimal arm64 with mismatched overall exit must not be whole_success!

FAIL: test_minimal_x64_false_green_on_mismatched_overall_exit
AssertionError: True is not false : Minimal x64 with mismatched overall exit must not be whole_success!

FAIL: test_negative_not_loaded_prefix_pattern
AssertionError: True is not false : 'not Loaded ...' line must not trigger loaded true positive
```

### 2. GREEN 阶段通过证据（`logs/fex-diagnostics/green.log`）
修复正则锚定与 minimal 判定后，全量 20 项测试全部通过：

**执行命令**：
```bash
python3 -m unittest scripts.runtime.fex_init.test_diagnostics -v
```

**控制台实测完整回显**：
```text
test_error_observed_explicit_mapping_error (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_error_observed_false_when_fex_loaded (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_error_observed_unknown_when_neither (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_minimal_arm64_false_green_on_mismatched_overall_exit (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_minimal_arm64_false_green_on_timeout_with_exit_37 (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_minimal_x64_false_green_on_cleanup_error_with_exit_43 (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_minimal_x64_false_green_on_mismatched_overall_exit (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_minimal_x64_false_green_on_timeout_with_exit_43 (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_negative_could_not_load_status_c0000135 (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_negative_empty_lines (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_negative_not_loaded_prefix_pattern (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_negative_only_search_string (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_partial_output_then_crash_with_fake_ntterminate_zero (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_positive_load_builtin (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_target_entry_hello_x64 (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_target_entry_minimal_arm64 (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_target_entry_minimal_x64 (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_whole_success_clean_hello_x64 (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_whole_success_false_on_cleanup_error (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok
test_whole_success_false_on_timeout (scripts.runtime.fex_init.test_diagnostics.TestFexDiagnostics) ... ok

----------------------------------------------------------------------
Ran 20 tests in 0.001s

OK
```
**退出码**：`0`。耗时仅 1 毫秒。

同时复核既有 `test_classifier.py`（4 项测试）：
```bash
python3 -m unittest scripts.runtime.fex_init.test_classifier -v
# Ran 4 tests in 0.000s, OK
```
两套测试套件共计 24 项单测 100% 通过。

---

## 四、 交付文件清单

| 文件路径 | 状态 | 职责说明 |
| :--- | :---: | :--- |
| `scripts/runtime/fex_init/diagnostics.py` | 修复 | 纯函数解析与状态分类核心模块（正则锚定、三态 error_observed、Entry 与 Whole Success 严格解耦、独立元数据提取） |
| `scripts/runtime/fex_init/test_diagnostics.py` | 修复 | 20 项完整单元测试套件（覆盖负例、欺骗行前缀、伪造 trace、崩溃标记、超时与清理异常防假绿） |
| `scripts/runtime/fex_init/run_x64_test_controlled.py` | 修复 | 显式采集元数据并接入纯函数 `classify_run_outcome`，保持 import 安全 |
| `logs/fex-diagnostics/red.log` | 更新 | TDD RED 阶段真实失败记录 |
| `logs/fex-diagnostics/green.log` | 更新 | TDD GREEN 阶段 20 项测试全量通过原始记录 |
| `reports/fex-diagnostics.md` | 更新 | 本交付报告 |

---

## 五、 状态更新

- 任务 `task-21` 既定目标全部完成，各边界约束均已落实并由单元测试闭环。
- 未修改已冻结的 elfuse C 代码或原版 Proton 包，未改动全局环境或 Steam 客户端。
