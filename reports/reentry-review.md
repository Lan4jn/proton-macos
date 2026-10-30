# Round 37 独立复核报告：Task-79 写入者模块归属与重入判据独立审查（更正版）

**审查员**：evidence-reviewer-r36  
**审查基准**：纯只读独立复核、不重跑重 Wine、不改执行员代码与收据、严禁将假设推论作为已证实结论  
**审查对象**：
- 报告文档：reports/reentry.md
- JSON 收据：logs/reentry/vulkan/receipt.json、logs/reentry/control.json
- 物理日志：logs/reentry/vulkan/run-c9cit7bo/stderr.log 与 stdout.log
- 补丁源码：sources/elfuse-reentry-derived/src/syscall/syscall.c

---

## 一、 问题分级清单 (Issue Classification)

### P0 / 阻断性破坏：无
执行员在收据中如实记录了 `run_valid = false / NOT_REPRODUCED`，控制测试通过，未伪造测试结果。

### P1 / 关键数据错填与路径失效（第四次复发流程缺陷）
1. **运行目录 (run_dir) 再次虚标失效**：
   - reports/reentry.md 第 4.2 节记录：run_dir: logs/reentry/vulkan/run-x960682y；
   - **磁盘物理核验**：run-x960682y 在磁盘上**根本不存在**（返回 ENOENT）；
   - **实际收据核验**：receipt.json 中记载的真实 run_dir 为 logs/reentry/vulkan/run-c9cit7bo，物理落盘目录真实存在。
2. **stderr_bytes 再次机械复用前序旧值**：
   - reports/reentry.md 第 4.2 节记录：stderr_bytes: 685764；
   - **实际收据核验**：685764 是 Task-74 的特定收据大小；本轮 Task-79 的真实 stderr_bytes 严格为 **629191 字节**（物理文件 run-c9cit7bo/stderr.log 亦为 629,191 字节）。执行员第四次在报告手填中复用了上一轮的数值。

### P2 / 门槛状态与归因边界说明（依据 Lead 交叉核验更正）
1. **门槛达成状态勘误（Step 3 已达成，未达成的是目标 ENTER）**：
   - 审查员此前曾误将门槛未达表述为“未达 Step 3”，经 Lead 交叉核对收据更正：
   - **收据第 50 行事实**：`logs/reentry/vulkan/receipt.json` 的 `stdout` 字段明确记录了 478 字节输出，完整包含 `[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...`。**门槛 (a) Step 3 实际已成功达成**；
   - **未达成项**：仅门槛 (b) 未达成（在 62.12s 预算耗尽时，进程推进到了动态链接晚期但尚未触及末端 `uaddr=0x20102d440` 的 `FUTEX_OWNER_ENTER`，`target_futex_enters = []`）；
   - 执行员如实评定 `run_valid = false / NOT_REPRODUCED` 符合双门槛必须同时达成的规范。
2. **跃迁时刻寄存器归属因果解读限定为“未定”（陈旧镜像，非有效调用者）**：
   - 逐字映射事实：在本次运行捕获的 `ONCE_TRANSITION` 中，`transition_elr=0x10040580` 与 `transition_lr=0x100291cc` 在物理映射上落在 `ld-linux-aarch64.so.1` 代码段；
   - **因果结论降级为“未定”**：
     - 同一对地址在上一轮未复现运行中被映射为 `/usr/bin/sh`，在本次运行中被映射为 `ld-linux`。两轮归属不一致充分证明该寄存器镜像极可能是此前系统调用或动态链接执行留下的**陈旧快照**；
     - 本次运行同样未能复现末端挂起，**不能将未复现运行中的快照据此推断为“写入发生在 dlopen 路径”**；
     - 故关于控制字首次写 1 的真实调用者与模块归属，在当前证据下必须定性为【未定】，仅保留逐字映射事实本身。

---

## 二、 逐项数据交叉核验表 (Data Audit Matrix)

| 核验项目 | 报告手填数据 | JSON 收据真实记录 | 磁盘物理文件状态 | 审查判定 |
| :--- | :--- | :--- | :--- | :---: |
| **有效性判定** | run_valid=false / NOT_REPRODUCED | false / NOT_REPRODUCED | 门槛未达如实定性 | **PASS** |
| **运行时 SHA256** | b33af4b62a6f... | b33af4b62a6fe1ca86619452ff31eb08a26ffece1ad4c581896d6090427b92bc | 一致 | **PASS** |
| **Step 3 探针标记** | 声明达成 Step 3 | stdout 包含完整 Step 3 | 真实存在于 stdout.log (486B) | **PASS** |
| **目标 Futex ENTER** | 0 条 | 0 条 (target_enters = []) | 确实未抵达挂起点 | **PASS** |
| **运行目录 (run_dir)** | **run-x960682y (误)** | **run-c9cit7bo (真)** | run-x960682y 不存在<br>run-c9cit7bo 存在 | **FAIL (P1-1)** |
| **Stderr 字节数** | **685764 字节 (误)** | **629191 字节 (真)** | 物理文件严格为 629191B | **FAIL (P1-2)** |
| **Stdout 字节数** | 478 字节 | 478 字节 | 一致 | **PASS** |
| **运行耗时 (Seconds)** | 62.12s | 62.116102s (exit 124) | 一致 | **PASS** |
| **跃迁 ELR 模块归属** | ld-linux-aarch64.so.1 off=0x1c580 | ld-linux-aarch64.so.1 off=0x1c580 | 逐字映射事实，因果定性降级为未定 | **PASS** |
| **跃迁 LR 模块归属** | ld-linux-aarch64.so.1 off=0x51cc | ld-linux-aarch64.so.1 off=0x51cc | 逐字映射事实，因果定性降级为未定 | **PASS** |
| **分类时间线记录条数** | 114 条 | 114 条 | 一致 | **PASS** |

---

## 三、 核心技术结论汇总

1. **写 1 的发起上下文与因果边界**：
   - 逐字映射记录了 `0x10040580` 与 `0x100291cc` 在当前进程空间落于 `ld-linux`，但鉴于前序轮次曾归属于 `sh`，两轮不一致确证其为陈旧快照，不能构成“写入由 dlopen 触发”的因果证据，调用者定性为未定。
2. **时序与采样开销定性**：
   - 300us 高频采样对执行时序带来显著滞后，使进程在 62s 预算内虽进入 Step 3 但未触及末端 futex。报告按规范记为 `NOT_REPRODUCED`，定性客观。
