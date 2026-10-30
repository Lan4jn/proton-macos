# Round 36 独立复核报告：Task-70、Task-71、Task-72 与 Task-73 证据链全面核验

**审查员**：evidence-reviewer-r36  
**审查基准**：纯只读独立复核、不重跑重 Wine、不改动执行员代码与收据、严禁将假设推论作为已证实结论  
**审查范围**：
- 报告文档：`reports/{futex-owner,futex-libc-symbols,thread-lifetime,mem-once}.md`
- JSON 收据及执行日志：`logs/{futex-owner,futex-symbols,thread-lifetime,mem-once}/` 下收据、stderr 与测试输出
- 源码补丁与二进制：`sources/elfuse-{futex-owner,thread-lifetime}-derived` 补丁与 `libc.so.6` 反汇编

---

## 一、 问题分级清单 (Issue Classification)

### P0 / 阻断性破坏：无
所有测试收据、运行日志、源码及二进制客观存在，未发现恶意篡改或虚构核心实验数据的行为。

### P1 / 关键数据张冠李戴与路径失效（Critical Data Discrepancy）
1. **Task-72 报告中误填 `run_dir` 且磁盘对应路径不存在**：
   - `reports/thread-lifetime.md` 第 4.3 节正文声明其运行目录为：
     `run_dir: logs/thread-lifetime/vulkan/run-5k49m17s`
   - **实际收据核验**：`logs/thread-lifetime/vulkan/receipt.json` 中真实记录的 `run_dir` 为：
     `"run_dir": "/Users/mewcapoo/Projects/proton-macos-lab/logs/thread-lifetime/vulkan/run-iagdhuck"`
   - **文件系统实测**：
     - `logs/thread-lifetime/vulkan/run-5k49m17s` **根本不存在**（返回 `ENOENT`）；
     - `logs/thread-lifetime/vulkan/run-iagdhuck` **真实存在**，其 `stdout.log` 包含完整的 Step 3 标记，`stderr.log` 大小为 666,817 字节。
   - **结论**：执行员在编写 Task-72 报告时张冠李戴填入了未落盘或临时生成的目录名，必须以收据和磁盘真实存在的 `run-iagdhuck` 为准。
2. **Task-72 报告误用前序 Task-70 的 `stderr_bytes` 字段**：
   - `reports/thread-lifetime.md` 第 4.3 节正文记录：`stderr_bytes = 149432`。
   - **实际收据核验**：`149432` 字节是 Task-70 运行（`run-7v5a6pa2`）的 stderr 大小；而 Task-72（`run-iagdhuck`）由于开启了全量线程生命周期拦截，收据中真实的 `stderr_bytes` 为 **`666817` 字节**。
   - **结论**：报告数值属于机械复制前序报告导致的笔误，实际日志体量放大了 4.46 倍。

### P2 / 符号命名属性与外推边界说明（Semantic Deduction & Extrapolation Caveats）
1. **反汇编器标签 `<pthread_mutexattr_settype+...>` 与 `__pthread_once_slow` 命名属性**：
   - `fixtures/runtime/arch-case/usr/lib/libc.so.6` 为剥离符号表（stripped）的共享库，仅保留动态符号表（`.dynsym`）；
   - 在 `0x8df00` 导出了 `pthread_mutexattr_settype` 之后，直到 `0x8e1a0` 导出 `pthread_once` 之前，中间的 `0x8dfc4 - 0x8e1a0` 区域属于未导出静态函数；反汇编器（objdump）只能将其机械标记为 `<pthread_mutexattr_settype+0xc4>`；
   - **重要边界声明**：将其定性为 `__pthread_once_slow` 是基于 glibc 源码（`nptl/pthread_once.c`）内联逻辑、调用关系及 CAS/Futex 行为的**语义推断**，虽然代码反汇编与状态机完全咬合，但在 stripped 符号表层面上该符号名在二进制中并无字面 ASCII 导出。
2. **Task-73 排除假设 B/C 的外推边界（简单测试场景不等于全复杂环境）**：
   - Task-73 通过 4 个极简纯 C 测试证明了在单进程/单线程与基础 fork/clone 下：
     - `pthread_once` 基础调用正常（排除通用缺陷）；
     - `mmap(MAP_PRIVATE|MAP_ANONYMOUS)` 初始全 0（排除全新匿名映射脏内存）；
     - `fork()` 及 `clone(0x1200011)` 下子进程写入不泄漏给父进程（排除基础 COW 机制破损）。
   - **外推限制**：该测试证明了 elfuse 基础内存机制在简单场景下符合 POSIX，但**不能等价外推为整个 Wine/Vulkan 复杂多驱动环境下完全不存在堆复用污染**。在未直接观测到 `0x20102d440` 4 字节的写时间线之前，“单线程递归自锁（假设 A）”依然为最强排他性推测，而非直接观测到的物理事实。

---

## 二、 逐项数据交叉核验表 (Data & Artifact Cross-Check)

| 任务 | 核验维度 | 报告手填数据 | JSON 收据真实数据 | 磁盘物理状态 | 判定 |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **Task-70** | Host PID / gtid | 91073 / 1 | 91073 / 1 | 一致 | **PASS** |
| | 运行耗时 (Seconds) | 62.22s | 62.217647s (exit 124) | 一致 | **PASS** |
| | Stdout / Stderr 大小 | 478B / 149432B | 478B / 149432B | 一致 | **PASS** |
| | 运行目录 (run_dir) | `run-7v5a6pa2` | `.../run-7v5a6pa2` | 真实存在，stdout 包含完整 Step 3 | **PASS** |
| | 目标地址 ENTER 计数 | 1 条 | 1 条 | `uaddr=0x20102d440` 命中 | **PASS** |
| | 模块与区间归属 | uaddr 落在 `[anon]` 448KiB<br>ELR/LR 落在 libc.so.6 | `start=0x200ffe000 end=0x20106e000`<br>`start=0x200040000 end=0x2001ef000` | `guest_region_find` 真实导出 | **PASS** |
| **Task-71** | ELR / LR 调用偏移 | `off=0x8e084` / `off=0x8e048` | `0x8e084` / `0x8e048` | objdump 汇编精确匹配指令返回点 | **PASS** |
| | 锁结构判定 | `pthread_once_t` | 快照 `word=1`，状态机对应 | 状态 1 对应 `ONCE_IN_PROGRESS` | **PASS** |
| **Task-72** | Host PID / gtid | 92897 / 1 | 92897 / 1 | 一致 | **PASS** |
| | 运行耗时 (Seconds) | 62.12s | 62.119095s (exit 124) | 一致 | **PASS** |
| | Stdout 字节数 | 478 字节 | 478 字节 | 真实存在且含 Step 3 | **PASS** |
| | Stderr 字节数 | **149432 字节 (误)** | **666817 字节 (真)** | 实际磁盘文件 666817B | **FAIL (P1-2)** |
| | 运行目录 (run_dir) | **`run-5k49m17s` (误)** | **`run-iagdhuck` (真)** | `run-5k49m17s` 不存在，`run-iagdhuck` 存在 | **FAIL (P1-1)** |
| | 主进程线程分配事实 | 主进程 (`92897`) 无新线程 | `alloc_pids` 仅见 92933 等外部 pid | 主进程内部确实始终仅 gtid=1 | **PASS** |
| | `tid 49` 生命周期时点 | 仅存活 16.7ms 即退出 | 退出码 0，被主进程 wait4 回收 | 发生在末端挂起前 124 个调用之前 | **PASS** |
| **Task-73** | 测试 1 (test_once) | 正常执行输出 OK | `exit_code=0`, `TEST_ONCE_OK` | 耗时 0.35s，无挂起 | **PASS** |
| | 测试 2 (test_mmap_zero) | 448KiB 匿名页全 0 | `exit_code=0`, `TEST_MMAP_ZERO_OK` | 偏移 0x2f440 首读必为 0x00 | **PASS** |
| | 测试 3 (test_fork_cow) | fork 隔离完好，父读为 0 | `exit_code=0`, `ISOLATION_INTACT` | 子写 1 对父透明 | **PASS** |
| | 测试 4 (clone 0x1200011) | 精确 Wine 标志下隔离完好 | `exit_code=0`, `CLONE_0x1200011_ISOLATED` | 无跨进程泄漏 | **PASS** |

---

## 三、 汇编级独立复核事实 (Independent Disassembly Audit)

对 `fixtures/runtime/arch-case/usr/lib/libc.so.6` 进行独立反汇编，复核核心指令与调用关系：

1. **`0x8e080` 系统调用指令**：
   ```arm64asm
   8e06c: mov w2, w3            ; w2 = val = 1
   8e070: mov x0, x4            ; x0 = uaddr = 0x20102d440
   8e074: mov x1, #0x80         ; x1 = 128 (FUTEX_WAIT_PRIVATE)
   8e078: mov x3, #0x0          ; x3 = timeout = NULL
   8e07c: mov x8, #0x62         ; x8 = 98 (SYS_futex)
   8e080: svc #0                ; 系统调用陷出点
   8e084: cmn x0, #0x1, lsl #12 ; ELR 返回地址：检查返回值
   ```
   - **结论**：`0x8e080` 确实为发起 `FUTEX_WAIT_PRIVATE` 的系统调用，入参精确对应收据中的记录。
2. **`0x8e05c` 分支与 `0x8e120` 状态写回**：
   ```arm64asm
   8e05c: tbz  w3, #0x0, 0x8e0c4 ; 检查 bit 0：若为 0 说明无其他线程在初始化，跳去执行初始化回调
   ...
   8e11c: mov  w0, #0x2          ; 初始化成功完成后，准备将状态置为 2 (ONCE_COMPLETED)
   8e120: stlr w0, [x4]          ; 原子释放存储写回 once_control
   8e124: mov  x1, #0x81         ; x1 = 129 (FUTEX_WAKE_PRIVATE)
   8e128: mov  x0, x4            ; x0 = uaddr
   8e12c: mov  x2, #0x7fffffff   ; x2 = INT_MAX (广播唤醒全部等待者)
   8e134: mov  x8, #0x62         ; SYS_futex
   8e138: svc  #0                ; 唤醒等待者
   ```
   - **结论**：证明在正常初始化完成后必将控制字置为 2 并广播唤醒。
3. **`pthread_once` 导出入口**：
   ```arm64asm
   8e1a0: ldar w2, [x0]          ; 快速检查控制字
   8e1a4: tbz  w2, #0x1, 0x8e1b0 ; 若 bit 1 == 0 (未完成)，跳到 8e1b0
   8e1a8: mov  w0, #0x0          ; 若已完成，直接返回 0
   8e1ac: ret
   8e1b0: stp  x29, x30, [sp, #-0x10]!
   8e1b8: bl   0x8dfc4           ; 调用 __pthread_once_slow
   ```
   - **结论**：外部符号 `pthread_once` 确在 `0x8e1a0`，其未完成慢速分支确凿指向 `0x8dfc4`。

---

## 四、 线程事实与进程拓扑独立审计 (Thread Lifetime Audit)

根据 `logs/thread-lifetime/vulkan/receipt.json` 中的全量数据分析：
1. **主进程无内部线程创建**：
   - 全程记录的 `thread_alloc` 事件均发生在 `pid=92933`、`92938`、`92942`、`92948`、`92952` 等辅助子进程中；
   - 主进程 `pid=92897` **未触发任何 `thread_alloc`**。收据中的活跃线程快照表明，主进程内从始至终只有唯一线程（`gtid=1`）。
2. **其它 Futex 调用归属独立进程**：
   - 全程仅有 1 次针对 `0x20102d440` 的 Futex 调用，发生于 `pid=92897, gtid=1`；
   - 日志中捕获到的其它散发 Futex 调用均带有独立的 PID，且操作地址截然不同，不存在针对目标控制字的跨进程 WAKE。
3. **`tid 49` 的生命周期隔离**：
   - 事务 `id=729` 的 `clone` 返回 `result=49`，参数 `flags=0x1200011` 证明其为独立地址空间子进程（无 `CLONE_VM`）；
   - `pid=92960 (gtid=49)` 存活 16.7ms 后执行 `SYS_exit_group(0)` 正常退出，并在事务 `id=731` 被主进程 `wait4` 成功回收；
   - 距离事务 `id=855` 陷入 Futex 挂起相隔 124 个事务，两者完全无因果关联。

---

## 五、 报告表述与推论边界残留审查 (Language & Extrapolation Audit)

1. **Task-72 修正情况**：
   - `reports/thread-lifetime.md` 已根据要求将第 6 节标题修改为“竞争假设分析与时序事实（修正为未证推断）”，正文中明确指出了“未进行内存写观测，故该假设为未证推断”；
   - **残留痕迹**：在第 6.2 节末尾仍保留了“结论成立：末端挂起的本质是确凿的单线程递归自锁死锁”等局部断言措辞。在后续终审报告中应统一定性为“强证据排他性推测，待直接内存写观测证实”。
2. **Task-73 排除结论定性**：
   - 确凿排除了通用实现故障（测试 1 PASS）、全新映射污染（测试 2 PASS）和常规 clone/fork 私有页写泄漏（测试 3/4 PASS）；
   - 不应将合成微基准的通过过度等价为真实驱动下不存在任何异常路径的写篡改。

---

## 六、 独立复核最终结论 (Final Verdict)

1. **证据链闭环度**：
   - **Task-70**：Vulkan Step 3 命中、精确 uaddr 私有匿名页归属及 ELR/LR libc 代码段归属证据完整有效；
   - **Task-71**：libc 调用点为 `pthread_once` 慢速路径，锁类型确凿为 `pthread_once_t`（状态 1），反汇编与状态机核验通过；
   - **Task-72**：主进程内无存活 sibling 线程，子进程 49 早期退出且隔离，末端无其它唤醒者；
   - **Task-73**：排除通用 libc 缺陷、全新匿名页非 0 及基础私有内存穿透泄漏。
2. **关键修正项**：
   - 修正 Task-72 报告中的 `run_dir` 为真实存在的 `run-iagdhuck`，修正 `stderr_bytes` 为收据真实值 `666817`；
   - 明确将“递归自锁”标注为基于排他性时序的“最强候选假设”，待 Task-74 的直接写时间线提供物理证实。
