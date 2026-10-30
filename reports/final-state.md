# Proton-on-Darwin / elfuse 实验终局状态与四分法定论声明 (Task-104 终局汇总版)

**审查执行员**：evidence-reviewer-r36 (独立复核与终局定论)  
**终局总定调**：**【本阶段目标未完成，不得表述为已完成或已跑通】(TARGET NOT MET - EXPERIMENT INCOMPLETE)**  
**关联任务**：Task-101 / Task-104（终局汇总：并入 task-102/103 结论并明确目标未完成）  
**物理支撑收据与全量日志**：
1. 终局审计复核记录：`logs/final-audit/audit_summary.json` (30/30 审计项全量对齐物理工件)
2. x64 探针运行收据：`logs/x64-vk/receipt.json` (`run-t9qrkmmc`, exit: 124, `run_valid: false`)
3. x64 崩溃现场原始日志：`logs/x64-vk/run-t9qrkmmc/stderr.log` (第 2435 行 EC=0x20 VA=0xf148 异常)
4. 会话中继架构设计：`reports/private-map-relay-design.md` (Task-103: DESIGN ONLY, SHA `59572e19...`)
5. 终局状态收据：`logs/final-r39r40/receipt.json`
6. 综合交付索引：`reports/FINAL.md`

---

## 一、 审计复核对账报告 (Audit the Audit)

### 1. 独立抽样对账核验表 (覆盖指令指定核心指标)

| 抽检序号 | 审计项内容 | 报告/审计表记录值 | 物理工件文件 | 工件字段路径 | 工件实际物理值 | 抽查判定 |
| :---: | :--- | :--- | :--- | :--- | :--- | :---: |
| **S1** | **Task-94 Windows once 指标** | 19 / 5 / 1 / True | `logs/once-panorama2/comparison.json` | `windows.total_calls` / `distinct_addresses_count` / `uncompleted_word1_count` / `closed_loop_detected` | `19 / 5 / 1 / true` | **一致 (PASS)** |
| **S2** | **Task-94 Linux once 指标** | 2895 / 254 / 0 / False | `logs/once-panorama2/comparison.json` | `linux.total_calls` / `distinct_addresses_count` / `uncompleted_word1_count` / `closed_loop_detected` | `2895 / 254 / 0 / false` | **一致 (PASS)** |
| **S3** | **Task-94 终局裁定 verdict** | `{windows_closed_loop: true, linux_closed_loop: false, is_bridge_specific: true}` | `logs/once-panorama2/comparison.json` | `verdict` | `{"windows_closed_loop": true, "linux_closed_loop": false, "is_bridge_specific": true}` | **一致 (PASS)** |
| **S4** | **Task-96 栈帧完全重合** | Call 2 depth 18-26 100% 吻合 Call 1 depth 0-8 | `logs/once-backtrace/windows/receipt.json` | `call2_frames[18..26]` vs `call1_frames[0..8]` | 地址、FP、模块及偏移 100% 逐字吻合 | **一致 (PASS)** |
| **S5** | **Task-96 win32u.so 度量** | 帧数 14 帧 / 行数 14 行 | `logs/once-backtrace/windows/receipt.json` | `call1_frames`(1) + `call2_frames`(13) / 文件行匹配数 | 帧数: 14 / 行数: 14 | **一致 (PASS)** |
| **S6** | **Task-96 libvulkan.so.1 度量**| 帧数 0 帧 / 行数 0 行 | `logs/once-backtrace/windows/receipt.json` | `call1_frames`(0) + `call2_frames`(0) / 文件行匹配数 | 帧数: 0 / 行数: 0 | **一致 (PASS)** |
| **S7** | **Task-97 放行次数与地址** | 2 次 / 0x20102d440 & 0x20102d478 | `logs/reentry-release/comparison.json` | `release.bypass_count` / `release.bypasses[*].uaddr` | `2` / `0x20102d440` & `0x20102d478` | **一致 (PASS)** |
| **S8** | **Task-97 放行时间戳 (ts_us)** | 988508853966 / 988508854028 (相隔 62µs) | `logs/reentry-release/comparison.json` | `release.bypasses[0].ts_us` / `release.bypasses[1].ts_us` | `988508853966` / `988508854028` | **一致 (PASS)** |
| **S9** | **Task-97 高频自旋次数** | 528,990 次 | `logs/reentry-release/comparison.json` | `release.downstream_behavior.hang_point.total_once_calls_in_loop` | `528990` | **一致 (PASS)** |
| **S10**| **Task-97 运行退出码与有效性** | 实验组 124 (VALID) / 基线 124 (VALID) | `logs/reentry-release/comparison.json` | `release.exit_code` / `baseline.exit_code` | `124 (true)` / `124 (true)` | **一致 (PASS)** |
| **S11**| **Task-98 私有映射三条可达性** | (a)不可达, (b)条件可达, (c)可达; 估 600~900 行 | `reports/private-cow-decision.md` | 三条语义可达性与改动面估算 | (a)不可达, (b)条件可达, (c)可达; 600~900 行 | **一致 (PASS)** |
| **S12**| **Task-95 SHA 记录真实性核查** | `7b490795...` | 信箱交付消息 (无物理磁盘文件) | 信箱消息字面 | 无对应 logs 物理磁盘文件 | **标注空比对 (NOTE)** |

### 2. 关键专项对账说明
- **win32u.so 与 libvulkan.so.1 双维度度量**：
  - `win32u.so`：Call 1 命中 1 帧，Call 2 命中 13 帧，物理栈帧合计 14 帧；`receipt.json` 匹配行数严格为 14 行。排除此前误读的“6 帧”笔误，统一为 14 帧 / 14 行，完全自洽；
  - `libvulkan.so.1`：两轮调用栈中物理帧数 0 帧，文件匹配 0 行，严格为 0/0 一致，彻底排除其直接重入参与。
- **凭空比对与重复审计表消除**：
  - 明确标注 Task-95 SHA 系信箱消息记录而非独立物理磁盘日志，消除了空比对隐患；
  - `audit_table.json` 已完全收敛并作为指向 `audit_summary.json` (30 项) 的单一同源视图，杜绝双表演化分歧。

---

## 二、 新增技术缺项与跨架构对照 (Task-102 & Task-103 成果)

### 1. 新增技术缺项：x64 探针发生指令取指异常 (VA=0xf148)
在 Task-102 中，构建了零 CRT 依赖的最小 x64 PE 探针（`scripts/runtime/x64_vk/vk_enum_x64.exe`，SHA256: `d408405c...`），在同一套 once 监控下跑测：
- **运行收据**（`logs/x64-vk/receipt.json`）：`exit_code: 124`，`timed_out: true`，耗时 62.128s，`stdout_bytes: 0`，`has_step3: false`，`run_valid: false`（**未达硬性有效性门槛**）；
- **崩溃现场证据**（`logs/x64-vk/run-t9qrkmmc/stderr.log` 第 2435 行）：
  ```text
  src/syscall/proc.c:4571: elfuse: worker: unexpected exception EC=0x20 syndrome=0x82000007 VA=0xf148 PA=0xf148
  ## Translation diagnostics (PC=0xf148)
  L3[15]=0xf7e7 -> IPA 0xf148
  ```
- **严格原文归因**：**guest 进程在 elfuse 下发生指令取指异常 (VA=0xf148)**（`EC=0x20: Instruction Abort from a lower Exception level`），而非此前非正式推断的单一应用层崩溃。这是本次新暴露的**未定位技术缺项**（疑点：极低地址 `0xf148` 可能为错误跳转或 FEX 翻译层初始化异常），导致下游用户代码未能获得执行调度；
- **架构无关性终态判定**：因 x64 路径在上游启动期即被 `VA=0xf148` 取指异常阻断，物理上从未触达 `vkCreateInstance` 阶段，因此“`win32u.so` 重入自锁与架构无关”假说在 x64 上属于【**不可观测（Unobservable due to Upstream Block）**】，既未证实也未证伪；
- **可反驳条件**：修复 `VA=0xf148` 异常使 x64 探针成功推进至 Step 3 后，若在 `win32u.so` 同样捕获到 `0x20102d440` 二次重入则证实；若 Step 3 顺利通过则证伪。

### 2. 私有映射会话中继设计方案 (Task-103 成果)
针对 `ELFUSE_DIAG_SESSION_SHARED=1` 门禁破坏 COW 隔离且写回文件的安全风险，在 `reports/private-map-relay-design.md` 中交付了中继架构设计方案（**DESIGN ONLY，153 行，SHA256: `59572e19b6b58e0e3a3f3e677f9ae33ee794a038fc570df72a95aad380ae43b4`**）：
- **架构权衡**：论证了纯文件映射方案（方式 B）单独无法满足语义 (b)；设计了内存影子副本协议（1.29 MiB / 324 页，O(324) 脏页比对扫描），在感知活文件变更的同时阻断回写；
- **风险识别**：识别出非原子扫描导致的 TOCTOU 竞态，并给出了两套缓解策略；
- **性质定性**：该方案**仅交付设计，未在 elfuse 中落地实现，严禁宣称已修复**。

---

## 三、 终局状态声明 (The Quadripartite Taxonomy)

依据本会话迄今全部 100 项任务积累的真实物理工件，做出权威四分法终局划分：

### 1. 已确立事实 (Established Facts - 物理铁证支撑)
1. **Windows ARM64 Vulkan 实例创建重入自锁机理**：
   - 阻断点位于 guest glibc `pthread_once` 内部的 `FUTEX_WAIT_PRIVATE`（地址 `0x20102d440`, `val=1, word=1`）；
   - 指令级断点与 AArch64 X29 深度栈回溯证明：主 Wine 进程主线程（`gtid=1`）在调用 `vkCreateInstance` 展开 9.017 秒后，发生同线程深度递归重入（Call 2 Depth 18–26 与 Call 1 Depth 0–8 100% 完全重合）；首次进入的例程仍在栈上未退出，二次进入形成物理拓扑闭环，触发自锁；
   - **物理归属定位**：死锁发起点与重入点均确凿位于 Wine 核心 Unix 端图形库 **`win32u.so`**（`__wine_get_vulkan_driver+0x24` 与 `vulkan_instance_create+0x38`），彻底排除 `libvulkan.so.1` 直接重入。
2. **跨平台特异性 (Platform Specificity)**：
   - Linux ARM64 原生 Lavapipe 环境下 2,895 次 once 调用覆盖 254 个控制字，0 未完成项，无闭环死锁，成功完成图形队列提交与 256 字节图案回读（`closed_loop = false`）；
   - 确证重入闭环死锁系 **Wine / winevulkan 桥接层与 Wine 用户态状态机协同场景下特有**。
3. **私有文件映射 (MAP_PRIVATE) 物理缺陷**：
   - 无门禁下 `pread` 快照导致活文件更新完全不可见（exit=1, RED）；门禁下转 `MAP_SHARED` 破坏 COW 隔离且将客体写入回写底层文件（exit=6, RED）。
4. **guest 信号机制与可逆安装**：
   - 补齐 SIGCHLD `si_status` 贯通（7 项全绿）；建立了 lab 内部封闭式 plan/manifest/rollback 方案（63 项全绿）。

### 2. 已排除假设 (Falsified Hypotheses - 证伪留证)
1. 排除宿主虚拟化 futex 实现缺陷；
2. 排除单线程 pthread_once 通用缺陷；
3. 排除匿名页未零填充与跨进程 COW 内存穿透；
4. 排除子进程 49 退出锁遗留；
5. 排除 Khronos Loader 递归显式告警（匹配严格为 0）；
6. 排除 `libvulkan.so.1` 直接重入成因（调用栈出现严格为 0/0）；
7. 排除分支 A_alt（异常提前退出未置 2，调用栈证明例程处于激活态）。

### 3. 未决事项 (Unsettled Decisions - 待解架构难题)
1. **`win32u.so` 显示驱动初始化自递归解环方案**：在 Wine 显示驱动初始化链中阻断对自身的二次实例创建重入；
2. **泛化诊断放行导致的下游驱动桩死循环根治**：Task-97 证实强行置 2 放行导致 `lazydrv_map_instance_extensions` 陷入 52.8 万次尾调用死循环；必须实现真实驱动函数表的完整初始化；
3. **macOS/HVF 下 MAP_PRIVATE 规范语义替代架构设计**：如何将 Task-103 会话中继方案安全工程化落地。

### 4. 仍未实证事项 (Unverified Items - 绝对不可冒称通过)
1. **Vulkan 图形设备枚举与真实渲染流水线返回**（Windows 路径仍阻断在 `vkCreateInstance`，从未实证）；
2. **真实 Steam 客户端与 Steamworks API 通信**（仅在离线 fixture 根下验证，真实登录与启动从未实证）；
3. **Valve 官方直接签名**（仅在本地隔离沙箱签名）；
4. **正确且符合 POSIX/Linux 标准的原生全局 COW 内存实现**（生产级内存子系统仍缺失）；
5. **新增技术缺项：x64 guest 指令取指异常 (VA=0xf148 / EC=0x20) 的物理定位与修复**（x64 探针受阻于此，未能实证架构无关性）。

---

## 四、 终态权威判定语句 (The Definitive Declaration)

> ### ⚠️ 权威定论声明：  
> **本阶段实验目标【未完成】（TARGET NOT MET），严禁表述为已完成、已解决或已跑通！**  
> 虽然在指令级断点、AArch64 X29 深度栈回溯、模块物理归属（`win32u.so`）、跨架构对照以及信号语义完整性方面取得了决定性的诊断证据突破，但 Windows 侧 Vulkan 实例创建当前依然被 Wine 用户态驱动死锁阻断，x64 链路发生未定位的 `VA=0xf148` 取指异常，图形流水线返回与真实 Steam 客户端握手依然属于**仍未实证**状态。
