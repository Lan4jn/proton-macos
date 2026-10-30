# Proton macOS Lab 最终原件完整性与快速分层回归账本审计报告

**报告日期**：2026-10-16  
**审查角色**：`lab-reviewer`（独立代码审查员）  
**审查任务**：`task-32`（审计最终原件完整性及快速分层回归账本）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**独立测试归档目录**：`logs/continuation-final-review/`  

---

## 一、 执行摘要与审查原则

依据任务书定义与项目全局准则，本审查严格遵循只读审计与快速分层核验规范：
1. **只读承诺与零环境污染**：
   - 严禁修改任何生产脚本、测试代码或原始上游资产；
   - 严禁读取或写入宿主真实 Steam 目录、用户账号或私有凭据；
   - 严禁执行任何 Git commit/push 操作；
   - 不调用任何需要审批的特权扩展（不传 `sandbox_permissions`）。
2. **快速回归与非阻塞**：
   - 不重复运行耗时超 100 秒的长程集成测试，避免无意义占满 CPU/Hypervisor 资源；
   - 依赖测试套件（Fast Python Tests）覆盖核心边界与分类器逻辑；
   - 区分“单元测试 Mock/Synthetic 绿灯”与“实际运行真实证据”，避免虚假泛化。
3. **真实分层账本（严禁夸大）**：
   - 严格以各阶段落盘的真实 JSON/stdout/stderr 日志为依据；
   - 明确切分各层能力边界，绝不将“控制台程序通过”虚假外推为“3D 游戏或 Steamworks 通用”，绝不将“单次样本通过”断言为“100% 绝对等价”。

---

## 二、 原件完整性审计（Sources, Bundles, Scripts）

审查员在只读模式下核验了核心源码树、公开 Proton 种子包以及派生脚本的原始一致性（日志见 `logs/continuation-final-review/integrity_check.log`）：

| 检查目标 | 预期凭据 / 基线 | 实测核验结果 | 判定 |
| :--- | :--- | :--- | :---: |
| **`sources/elfuse` 上游源码树** | 工作区 clean，pinned 提交：`8612033dab8dc60728f604a4ea0441895fc16d39` | `git -C sources/elfuse status` 确认 clean 无改动；`rev-parse HEAD` 精确匹配 `8612033d...` | **PASS** |
| **`artifacts/public-proton` 种子包** | `The412Banner/winlator-contents` 公开 Release，完整归档摘要 `d6c480a9...` (已由历史记录固化，未耗时重算) | 记录完整，来源置信度明确注明为 `PUBLIC_REDISTRIBUTOR_CHECKSUM_VERIFIED_VALVE_ORIGIN_CLAIMED`，且 `independent_valve_signature_verified: false` | **PASS** |
| **`bundle.json` 关键文件摘要** | 包含 5 个核心 ELF/PE 二进制校验和 | Python 逐项读取计算 SHA-256，与 `bundle.json` 记录完全一致（`ALL_PASS`） | **PASS** |
| **`proton` 启动脚本一致性** | 派生包 `fixtures/runtime/proton-derived/proton` 与公开原包解压原件 | 执行 `cmp -s <orig> <derived>` 退出码为 `0`，逐字节完全一致（byte-for-byte exact match） | **PASS** |
| **派生 elfuse 构建版本** | 冻结特定实验修复目标 | `sources/elfuse-fex-derived/build/elfuse` (layout-only): `0079fc5d...`<br>`sources/elfuse-crash-derived/build/elfuse-candidate` (guard): `f83455b0...`<br>`sources/elfuse-lifecycle-derived/build/elfuse` (lifecycle): `f2a678dd...` | **PASS** |

---

## 三、 快速分层回归测试矩阵（Fast Python Suites）

审查员在隔离沙箱环境中（`HOME` 与 `TMPDIR` 均重定向至 `logs/continuation-final-review/` 专属目录）独立执行了全量快速测试套件，累计执行 **123 项测试**（122 项通过，1 项按设计跳过外部实时网络测试）：

| 测试套件 | 覆盖模块与重点 | 用例数 | 耗时 | 实测状态 | 归档日志路径 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Suite 1: Backend 全套** | 进程隔离、Supervisor、回归测试、运行时显式选择、Steam Handoff 边界 | 50 项 | 5.680s | **50/50 PASS** | `logs/continuation-final-review/suite1_backend.log` |
| **Suite 2: FEX 诊断与分类** | FEX 载入特征分类、假绿防护、超时退出码解耦、脏退出状态机判定 | 24 项 | 0.001s | **24/24 PASS** | `logs/continuation-final-review/suite2_fex_diagnostics.log` |
| **Suite 3: Integration 前置** | 公开清单模式、无网络 SteamCMD 响应解析、前置条件退出码 | 17 项 | 0.201s | **17/17 PASS** | `logs/continuation-final-review/suite3_integration.log` |
| **Suite 4: Steam 离线适配器** | 敏感字段脱敏、白名单、0600 独占创建、`-- %verb%` 参数边界 | 20 项 | 1.182s | **20/20 PASS** | `logs/continuation-final-review/suite4_steam.log` |
| **Suite 5: Proton 获取与审计** | ELF64/ARM64EC 合成审计、容量预检免责、阶段隔离无网络 Mock | 12 项 | 0.277s | **11 PASS, 1 SKIP** | `logs/continuation-final-review/suite5_proton.log` |

*注：以上单元测试均在受控隔离沙箱下秒级完成，未触发耗时超 100s 的长程实测，严格保障快速回归；Suite 5 的 1 项跳过严格依据测试回显实际原因标注：`skipped 'Live test skipped unless RUN_LIVE_STEAM_TEST=1'`，非任意推断。*

---

## 四、 核心执行层分层能力全量账本（Factual Accounting Ledger）

基于全实验周期内各项真实落盘的原始执行日志，逐层厘定实际通过、失败与阻断状态，严禁夸大：

| 执行层级 / 维度 | 运行组件 / 负载目标 | 运行时基准与校验和 | 实测判定 | 核心指标与真实证据 | 关键边界与局限性说明 |
| :--- | :--- | :--- | :---: | :--- | :--- |
| **1. 基础 ELF HVF 基线** | 汇编 hello、C exit 42、mmap+JIT、clone+wait4 | `sources/elfuse/build/elfuse`<br>(pinned `8612033d...`) | **PASS** | 7 项全过（正向 5 + 负向 2），Exit 0 / 42<br>`logs/elfuse/run.9CAvma/` | 证明基于 HVF 的 Linux AArch64 原生 ELF 执行能力，非 Wine 证明。 |
| **2. Linux ABI 语义（动态库/信号）** | `dynamic_hello`, `shared`, `signal` | 原始 clean `elfuse`<br>`fixtures/runtime/sysroot` | **PASS** | `DYNAMIC_GLIBC_OK`, `SHARED_OK`, `SIGNAL_OK`<br>`logs/abi/run-*` (Exit 0) | 证明动态 glibc 加载与共享匿名页基础功能。 |
| **3. Linux ABI 缺项（原始 elfuse）** | `futex.c` (跨进程唤醒)<br>`spawn_missing.c` (错误传递) | 原始 clean `elfuse`<br>`fixtures/runtime/sysroot` | **FAIL** | `FUTEX_TIMEOUT_DESPITE_SHARED_WRITE` (Exit 5)<br>`SPAWN_RETURN=0 CHILD_EXIT=127` (Exit 9) | 原始上游源码真实存在的兼容缺项，已如实保留，未作假绿伪装。 |
| **4. Linux ABI 同步修复（派生构建）** | 派生 futex 跨进程共享 WAIT/WAKE 实验修复 | `sources/elfuse-derived/build/elfuse` | **PASS (局部)** | 最小用例转绿，多等待者唤醒 Exit 0<br>`logs/abi-fix/confirmed-clean.log` | 仅限有限共享 WAIT/WAKE 修复，负 wake 计数等深层边界保留未称全兼容。 |
| **5. 真实 Wine 11 组件装载** | `files/bin-arm64/wine --version` | 原版包二进制 + Debian glibc 2.41 | **PASS** | 标准输出输出 `wine-11.0` (Exit 0)<br>`logs/runtime/glibc241-wine.log` | 仅证明 Wine 命令行组件自身完成动态链接与版本查询。 |
| **6. FEX 动态库原生加载** | `libarm64ecfex.so` | Linux Python 3.14 + ctypes (mode=2) | **PASS** | 输出 `FEX_NATIVE_MODULE_LOADED` (Exit 0)<br>`logs/runtime/run-njak1o36/` | **严格限定：仅证明 `dlopen` 成功，绝不等于已执行 x64 指令翻译**。 |
| **7. 最小 x64 PE 入口执行** | `minimal-x64.exe`<br>(ntdll-only 导入，直接返回 43) | `sources/elfuse-fex-derived/build/elfuse`<br>(layout-only `0079fc5d...`) | **PASS** | 精确返回目标自定义退出码 **`43`**<br>`logs/fex-init/run-5g8b1rkf`<br>`logs/fex-runtime-review/run-l84rpgk3` | **里程碑突破**：证实 x64 机器码由 FEX 成功载入、翻译并在 CPU 上执行。 |
| **8. x64 控制台 Hello（空指针保护版，Direct Wine）** | `hello-x64.exe`<br>(Win32 控制台输出 + 正常退出) | `sources/elfuse-crash-derived/build/elfuse-candidate`<br>(guard `f83455b0...`) | **PASS** | 输出 `X64_FEX_OK`，Exit 0，耗时 **51.01s** (实测 51.011s)<br>`logs/lead-round5/run-54af6nhn` | 仅证明当前针对特定空指针的候选保护生效，后台线程生命周期未根治。 |
| **9. 原版 Proton 启动链（runinprefix 动词，Guard f834）** | `hello-x64.exe` 经原版 `proton` 脚本驱动 | 原版 `proton` 脚本 + Linux Python 3.14 + `f834` | **PASS** | 输出 `X64_FEX_OK`，Exit 0，耗时 **68.72s** (实测 68.718s)<br>`logs/lead-round7/run-2bxmxfs0` | 完整验证 Linux Python 成功驱动原版 Proton launcher 执行 x64 控制台程序。 |
| **10. 生命周期修复版（Direct Wine，f2）** | `hello-x64.exe` (Direct Wine) | `sources/elfuse-lifecycle-derived/build/elfuse`<br>(lifecycle `f2a678dd...`) | **PASS** | 输出 `X64_FEX_OK`，Exit 0，耗时 **63.46s** (Reviewer 独立 `run-7zknvqy7`)<br>或执行员 `run-dyoqcrtf` (37.6s)<br>`logs/fex-lifecycle-review/run-7zknvqy7` | 验证在引入线程停止与 join 机制后，Direct Wine 独立执行依然绿灯。 |
| **11. 生命周期修复版（Proton 链复验，f2）** | `hello-x64.exe` 经原版 `proton` 脚本驱动 | `sources/elfuse-lifecycle-derived/build/elfuse`<br>(lifecycle `f2a678dd...`) | **PASS** | 输出 `X64_FEX_OK`，Exit 0，耗时 **46.05s** (实测 46.05s)<br>`logs/proton-contrast/run-x0q7o2qx` | 顺序单实例执行下成功完成，未见新增等待点或异常分支。 |
| **12. 历史 Proton Launcher 110s 超时** | `hello-x64.exe` 经原版 `proton` 脚本驱动 | Lead 独立首测快照 | **FAIL** | 耗时 110.0s 触发超时 (Exit 124)<br>`logs/lead-round7/run-rkbehni4` | **真实保留失败**：虽然并发调度竞争为合理候选解释，但在缺乏排他性因果证明下，**原因定性为未定 (REASON_UNDETERMINED)**。 |
| **13. Wine 桌面环境与建窗** | 完整 Proton `run` 动词 (包含 `explorer.exe`) | 原版 Proton 完整会话 | **BLOCKED** | 耗时 150s 超时，存在桌面建窗与 explorer 错误 | 尚未跑通 Windows 桌面环境，不可用 `runinprefix` 替代该结论。 |
| **14. Linux 底层 Vulkan Loader/实例** | `libvulkan.so.1` + `vkCreateInstance` | Linux Vulkan 1.4.357 + `3ace7bdc...` (lifecycle 先版)<br>及 candidate `f83455b0...` | **PASS** | Loader dlopen 成功，实例创建成功 (Exit 0)<br>Lead 独立 `logs/lead-round7/run-r_9wfv85` (0.63s)<br>任务 28 原日志 `logs/graphics-probe/run-sdpq8k55` (0.42s) | 仅证明 Vulkan 用户态 Loader 与 Instance 抽象层可正常初始化。 |
| **15. Linux 底层 Vulkan 物理设备枚举** | `vkEnumeratePhysicalDevices` | Linux Vulkan 1.4.357 + `3ace7bdc...` (lifecycle 先版)<br>及 candidate `f83455b0...` | **FAIL** | 接口返回 `-3` (`VK_ERROR_INITIALIZATION_FAILED`)<br>Lead 独立 `logs/lead-round7/run-r_9wfv85`<br>任务 28 原日志 `logs/graphics-probe/run-sdpq8k55` | **重要阻断**：物理设备枚举失败，`device_count` 无效，未能探测到宿主可用 GPU。*(新 task-33 启动官方 lavapipe 探测属于独立新 scope，本账本原默认设备枚举失败记录保持基线真实性)* |
| **16. 完整 3D 游戏 / Steamworks / DRM** | 实际商业 Windows 游戏 | 原版 Proton + 完整图形环境 | **NOT_TESTED** | 未测试 / 前置条件未就绪 | 严格禁止在没有有效 GPU 渲染与桌面支持前宣称“游戏可运行”。 |

---

## 五、 Steam 离线边界与环境安全审计

审查员执行了对 Steam 隔离与系统残留的专项检查：

1. **离线 Mock 目标隔离状态**：
   - 检查了 `artifacts/steam-prepared/` 目录下全部 5 个候选配置方案（`runtime-handoff-execute`, `continuation-probe`, `runtime-handoff-review-plan`, `reviewed-probe`, `runtime-handoff-plan-only`）；
   - **核验事实**：所有 `install-plan.json` 均记录 `"applied": false`；
   - **目标路径检查**：所有计划所指向的模拟目标目录（如 `fixtures/runtime/steam-shaped/mock-steam/...`）**完全不存在（`target_exists: False`）**，未发生任何安装行为；
   - **零宿主接触**：宿主真实 `~/Library/Application Support/Steam`、`~/.steam` 及登录凭据保持绝对零接触、零读写。
2. **宿主残留进程检查**：
   - 通过 `ps -Ao pid,ppid,stat,command` 全局扫描本实验（`proton-macos-lab`）相关的孤儿进程；
   - **实测结果**：输出 `NO_LINGERING_LAB_PROCESSES`，证明后端的会话 Supervisor 与组清理机制有效，宿主系统无任何残留实验进程。

---

## 六、 审查结论与最终签字

1. **数据与证据真实性**：
   - 全实验所有测试用例、基线检查、差异对比均严格基于真实落盘日志与客观退出码，无假绿、无截断、无虚假包装；
   - 原始 elfuse 缺陷、历史 110s 超时、Vulkan 物理设备枚举失败等事实均真实呈现并保留；
   - 突破性进展（x64 PE Exit 43 真实翻译、原版 Proton Python 驱动、Wine 11 版本查询、生命周期安全修复）均具备两端互证的多份独立日志支撑。
2. **最终审查判定**：**批准通过 (APPROVED)**
   - `task-32` 审计与分层回归账本圆满完成，真实反映了当前 macOS ARM64 运行原版 Valve Proton 的实际技术状态与精确边界。
