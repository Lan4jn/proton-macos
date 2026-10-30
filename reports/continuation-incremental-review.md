# Proton macOS Lab 增量分层审计与最终证据账本报告 (Task-53)

**报告日期**：2026-10-16  
**审查角色**：`lab-reviewer`（独立代码审查员）  
**审查任务**：`task-53`（独立审计新增诊断、环境对照与最终分层证据，覆盖 task-39 至 task-52）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**独立测试归档目录**：`logs/incremental-review/`  

---

## 一、 执行摘要与审查总则

本审查严格执行独立增量审计职责，聚焦 task-39 至 task-52 期间的新增实验产物、环境剖析、测试套件与执行证据：
1. **只读承诺与零环境污染**：
   - 不执行任何长期 Wine/HVF 运行，不启动 Xvfb，不进行外网网络下载；
   - 严禁读写宿主真实 Steam 目录、用户账号或私有凭据；
   - 严禁执行 Git commit/push 操作；所有工具调用绝不传递 `sandbox_permissions`。
2. **分层事实与非泛化原则（严禁夸大）**：
   - 真实落盘的离线测试与日志是唯一定性依据；
   - 明确区分“单元测试 Mock/Synthetic 绿灯”与“实际运行真实证据”；
   - 明确区分“裸控制台 PE 成功”与“Windows Vulkan/图形桌面成功”；
   - 严格指出：**未捕获到 Trace（`NO_TRACE`）不等于异常未发生；`LD_LIBRARY_PATH` 等差异属于已证配置差异与候选诱因，不等于排他性根因；特定环境 Profile 关联不等于单一变量因果**。

---

## 二、 源码、脚本与包资产完整性审计

审查员在只读模式下核验了上游源码树、种子包关键二进制及脚本一致性：

| 资产维度 | 预期基准 / 记录凭据 | 实际核验结果 | 判定 |
| :--- | :--- | :--- | :---: |
| **`sources/elfuse` 上游源码** | `git status` clean，HEAD 对齐 `8612033dab8dc60728f604a4ea0441895fc16d39` | 工作区干净（`CLEAN`），HEAD 精确吻合 | **PASS** |
| **`proton` 启动脚本一致性** | 派生包 `fixtures/runtime/proton-derived/proton` 与原包解压原件 | 执行 `cmp -s <orig> <derived>` 退出码为 `0`，逐字节完全一致（byte-for-byte exact match） | **PASS** |
| **公开 Proton 种子包 5 核心哈希** | `artifacts/public-proton/bundle.json` 中 5 个核心 ELF/PE 二进制 SHA-256 记录 | Python 逐项读取计算哈希，全部 100% 匹配（`ALL_PASS`） | **PASS** |
| **包来源声明与独立签名解耦** | 元数据置信度记录 | 明确标明 `publisher: The412Banner/winlator-contents`，来源声明为发布者声明，**未独立验证 Valve 官方签名** (`independent_valve_signature_verified: false`) | **PASS** |
| **派生版本代码变更边界** | `sources/elfuse-socket-derived` 与 `elfuse-lifecycle-derived` 对比 | 代码差异仅限于 `src/syscall/net.c` 与 `src/syscall/net-absock.c` 两处文件（实现 `ELFUSE_ABSOCK_BASE` 路径重定向支持） | **PASS** |

---

## 三、 快速分层单元测试独立复测矩阵（Fast Offline Suites）

审查员在隔离沙箱环境中（`HOME` 与 `TMPDIR` 均重定向至 `logs/incremental-review/` 专属目录）独立执行了各模块快速测试套件，累计执行 **134 项独立单元测试**（134 项全量 PASS，0 FAIL，0 ERROR，零 ResourceWarning）：

| 独立测试套件 | 覆盖模块与测试重点 | 用例数 | 耗时 | 实测状态 | 归档日志路径 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Backend 单元测试全套** | 进程隔离、会话 Supervisor、absock base 校验、运行时显式选择、Steam Handoff 边界；**确证无 ResourceWarning 泄漏** | 63 项 | 11.42s | **63/63 PASS** | `logs/incremental-review/suite_backend_63.log` |
| **FEX 诊断与分类套件** | FEX 载入特征识别、伪退出码防护、脏退出分类（`test_classifier.py` + `test_diagnostics.py`） | 24 项 | 0.001s | **24/24 PASS** | `logs/incremental-review/suite_fex_diagnostics_24.log` |
| **Steam 离线适配器套件** | 敏感字段脱敏、白名单、0600 独占写入及 `-- %verb%` 参数边界（`tests/steam`） | 20 项 | 6.68s | **20/20 PASS** | `logs/incremental-review/suite_steam_offline.log` |
| **Integration 前置诊断套件** | 公开清单模式、无网络 SteamCMD 响应解析、前置条件退出码（`scripts/integration`） | 17 项 | 1.14s | **17/17 PASS** | `logs/incremental-review/suite_integration_prereq.log` |
| **Task-52 环境分类器单元测试** | 离线断言 PREP_FAIL 与 SUCCESS_PE_OUTPUT_CLEAN_EXIT0 分类逻辑（`test_env_classifier.py`） | 7 项 | 0.001s | **7/7 PASS** | `logs/incremental-review/suite_env_classifier.log` |
| **Task-42 运行分类器单元测试** | 离线断言历史 3 次运行的依赖缺失与超时分类（`test_run_classifier.py`） | 3 项 | 0.001s | **3/3 PASS** | `logs/incremental-review/suite_wine_badalloc_classifier.log` |

*注：以上各项均为零 HVF/Wine 消耗的快速纯单元测试，用例数严格各自独立汇报，绝不盲目合并为虚假单一大套件。*

---

## 四、 核心增量执行层（Task 39-52）真实证据对账账本

审查员基于各任务落盘的真实原始日志与结构化记录，对近期各阶段的执行事实、状态解耦与技术边界进行了严密对账：

| 任务 / 实验分支 | 运行环境与运行时哈希 | 负载与目标 | 实测判定 | 核心指标与真实证据 | 关键技术边界与局限说明 |
| :--- | :--- | :--- | :---: | :--- | :--- |
| **Task-42: 异常捕获**<br>(3 次运行事实) | `elfuse-socket-derived`<br>(`06a2fceb...`) | Windows Vulkan PE<br>(`f77f9b8f...`) | **BLOCKED**<br>(未观测到trace) | 实际发生 3 次运行：<br>- `run-2hb_cnux` / `run-tkhs_6ra`: 报 126 (缺 user32/ucrtbase)<br>- `run-qgaia7if`: Step 3 发生 85s 观察超时 (rc: -15)<br>`wine_stderr.log`: 344 行，**未观测到 trace** | **状态严格解耦**：外层控制器退出码 0，内部 Wine 为 `OBSERVATION_TIMEOUT`。未观测到 trace 仅属实测未捕获，不证明底层 `__cxa_throw` 未发生。`LD_LIBRARY_PATH` 遗漏 Wine Unix 驱动库属于强候选诱因，非排他性根因。 |
| **Task-46: 环境对照**<br>(受控单次运行) | `elfuse-socket-derived`<br>(`06a2fceb...`) | Windows Vulkan PE<br>(`f77f9b8f...`) | **BLOCKED**<br>(Preloader 超时) | 唯一受控运行 `run-1792127044` (耗时 60.21s)：<br>Wine 退出码 124 (`CRASH_TIMEOUT`)，停在 `wine-preloader` 地址 `PC=0x20011e804`，未进入 Vulkan 调用，**未观测到 trace** | 内部 Wine 状态独立标定为 `OBSERVATION_TIMEOUT`。静态代码分析发现 `libLLVM.so` 经 `_ZSt17__throw_bad_allocv` 抛出异常，为后续诊断提供了关键机制事实。 |
| **Task-48: 阶段库初测**<br>(环境剥离故障) | `elfuse-socket-derived`<br>(`06a2fceb...`) | 裸控制台 `hello-x64.exe`<br>+ `--clear-env` | **FAIL**<br>(准备链缺陷) | Arm A 与 Arm B 均以 0.16s 触发 SIGSEGV（退出码 139），EL0 data fault at 0x0 | 恢复 profile 后微探针版本查询及 52 hello 成功，未定位单变量或全部 root，亦未证排他性。 |
| **Task-50: 早期环境微探针**<br>(4 次对比测试) | `elfuse-socket-derived`<br>(`06a2fceb...`) | 针对 `/bin/sh -c true` 与 `wine --version` 的环境二分 | **CONFIRMED**<br>(Profile 关联) | - Case A1 (`--clear-env` + true): Exit 0 (0.18s)<br>- Case A2 (`--clear-env` + wine): **Exit 139 (0.16s)**<br>- Case B1 (`clean_env` + true): Exit 0 (0.16s)<br>- Case B2 (`clean_env` + wine): **Exit 0, `wine-11.0` (0.17s)** | **科学定性**：实证了 `--clear-env` 与崩溃之间的直接对应关系，证实环境 profile 关联；**严格指出：多个环境变量联动变化，不能断言单一 HOME 变量为排他根因**。 |
| **Task-52: 受控基础环境**<br>(双臂严格顺序实测) | `elfuse-socket-derived`<br>(`06a2fceb...`) | 裸控制台 `hello-x64.exe`<br>(真实 SHA `26cccc8c...`) | **PASS**<br>(控制台成功) | - **Arm A (基线)**: 79.28s，**Exit 0**，输出 **`X64_FEX_OK`**<br>- **Arm B (阶段库)**: 63.98s，**Exit 0**，输出 **`X64_FEX_OK`**<br>Arm B 记录 63 次构造阶段标记，未见 throw marker | **重要边界界定**：证实在此受控配置下，`libbadalloc_phase.so` 完全未阻碍 FEX 启动与 PE 退出。**严禁泛化：仅限裸控制台 PE 成功，不代表图形驱动成功，不代表性能提升，亦不代表无 observer OOM**。 |

*年代范围说明：关于目标 PE `f77f9b8fa427120cc1488625f46f4cc05b0f1d2d2b22032f137cb81462cec412`，早期 task-35 记录的“f77 未重跑”仅指代 task-35 当时的历史状态；在后续的 task-42 与 task-46 中，该 PE 均已进行了真实的受控加载实测。*

---

## 五、 隔离机制与 Steam Candidate 状态审计

1. **抽象套接字中继权限与路径安全**：
   - 宿主运行器在启动时严格校验 `lab/.s` 的 `lstat` 属性（要求 `uid == getuid()`，`mode == 0700`，且 `not islink`），并在失败时阻断；
   - **科学定性纠偏**：底层 C 语言代码 (`net-absock.c:135`) 显式检查并禁止 group/other 读写执行权限（`(st.st_mode & (S_IRWXG | S_IRWXO)) != 0` 则拒绝），但不强制要求 owner 恰好具备完整的 `rwx`；而外层 Python 脚本核验更严格的 `0700` 模式。此外，宿主 `/tmp/elfuse-absock-*` 增量为零确证了特定中继目录未在常见临时目录下生成，但不等于证明了全系统全域绝对零写入。
2. **Steam Candidate 候选状态核实**：
   - 全盘核验 `artifacts/steam-prepared/` 目录下全部 9 处 `install-plan.json`；
   - **实测核验结果**：全部候选计划均记录 `"applied": false`；
   - **模拟目标检查**：所有模拟目标路径（如 `mock-steam/...` 或 `not-installed/...`）**完全不存在**，未发生任何实际安装；宿主真实 Steam 目录零接触、零读写、无账号或密钥交互。

---

## 六、 审查结论与交付签字

1. **测试统计与事实账本总结**：
   - 快速离线单元测试累计 **134 项**（134 项全量 PASS，0 FAIL，0 ERROR，零 ResourceWarning）；
   - Task 39-52 增量执行事实完整对账，所有失败与超时均客观保留；
   - 关键因果关系与定性边界（未观测到 trace≠底层未 throw、Profile 关联≠单一因果、控制台成功≠图形成功）均已严密校准。
2. **最终审查判定**：**批准通过 (APPROVED)**
   - `task-53` 增量分层审计工作全面完成，报告已归档于 `reports/continuation-incremental-review.md`。审查员就绪待命。
