# 诊断性绕过 once 死锁以判定首个与唯一缺口实验报告 (Task-83)

**特别警示与定性声明 (DIAGNOSTIC / BORROWED ONLY)**：
> **本实验属于【借用诊断 / DIAGNOSTIC BORROWED ONLY】实验。严禁将本实验所用放行手段表述为“修复”或“解决方案”；严禁据此宣称 Vulkan 流水线已跑通、ABI 正确或 Windows ARM64 兼容性达成。本实验唯一目的是回答架构级核心疑问：“挂起的 `0x20102d440` 究竟是执行链条上的首个缺口，还是唯一缺口？”**

---

## 一、 实验设计与纪律执行矩阵 (Discipline & Design Matrix)

| 纪律与硬性要求 | 落实情况与证据 | 判定 |
| :--- | :--- | :---: |
| **(1) 明确标注 DIAGNOSTIC** | 源码、控制台输出、JSON 收据及本文档全量标注 `[DIAGNOSTIC] / BORROWED`，严禁作为默认产品路径。 | **PASS** |
| **(2) 严格对准目标地址与进程** | 仅当 `uaddr == 0x20102d440`, `op == FUTEX_WAIT_PRIVATE`, `val == 1`, `word == 1` 且进程确实单线程时放行一次。 | **PASS** |
| **(3) 必须提供关闭开关的对照组** | 统一二进制下执行关闭对照组（baseline），耗时 62.13s，成功捕获挂起于 `0x20102d440`，`run_valid = true (VALID)`。 | **PASS** |
| **(4) 记录绕过后的新行为与缺项** | 成功记录放行后主线程推进 45 微秒后遇到的全新死锁点（详见第二节），确证为“首个缺口而非唯一缺口”。 | **PASS** |
| **(5) 物理文件一致性硬性检查** | 收据与物理磁盘落盘数据 100% 逐字节一致，绝无跨轮复用旧值或虚标路径。 | **PASS** |

---

## 二、 核心发现：这是首个缺口，绝非唯一缺口 (The Critical Finding)

通过对比对照组（baseline）与实验组（bypass），获得了不可辩驳的物理证据：

### 1. 对照组（baseline，开关关闭）：稳定卡死于首个控制字
- **运行目录**：`logs/once-bypass/baseline/run-4fy5uahy`
- **物理大小**：`stderr.log` 严格为 **717,937 字节**，`stdout.log` 为 478 字节；
- **执行表现**：
  - 在系统调用事务 `id=855` 处，主线程进入：
    ```text
    THREAD_LIFETIME_ENTER ts_us=978623135338 pid=58076 gtid=1 nr=98 sc=futex x0=0x20102d440 x1=0x80 x2=0x1
    FUTEX_ARGS pid=58076 gtid=1 id=855 uaddr=0x20102d440 op=0x80 val=1 word=1 ...
    ```
  - 进程在此无限等待，耗尽 62s 预算超时退出（`exit: 124, seconds: 62.13s`）；
  - 全程对后续任何地址 **0 次调用**。

### 2. 实验组（bypass，开关开启）：放行首个控制字后，瞬间卡死于下一个控制字
- **运行目录**：`logs/once-bypass/bypass/run-myqxkcq3`
- **物理大小**：`stderr.log` 严格为 **666,550 字节**，`stdout.log` 为 478 字节；
- **执行表现与连续调用时序**：
  1. **首个控制字成功放行**：
     在 `id=855` 处，诊断钩子捕获并放行：
     ```text
     [DIAGNOSTIC] ONCE_DEADLOCK_BYPASSED uaddr=0x20102d440 old_val=1 new_val=2 tid=1 pid=58268
     THREAD_LIFETIME_RETURN ts_us=978694414095 pid=58268 gtid=1 nr=98 sc=futex result=0 elapsed_us=72
     FUTEX_OWNER_RETURN pid=58268 gtid=1 uaddr=0x20102d440 op=0x80 result=0 elapsed_us=51
     IO_TX_RETURN pid=58268 gtid=1 id=855 nr=98 result=0 elapsed_us=46
     ```
     系统调用正常返回 0（耗时 51 微秒），控制字被置为 2（`ONCE_COMPLETED`）。
  2. **执行流继续推进并在 45 微秒后撞上第二个死锁点**：
     仅相隔 **45 微秒**（`ts_us=978694414140`），主线程在事务 `id=856` 发起了下一个系统调用：
     ```text
     THREAD_LIFETIME_ENTER ts_us=978694414140 pid=58268 gtid=1 nr=98 sc=futex x0=0x20102d478 x1=0x80 x2=0x1 x3=0x0
     THREAD_FUTEX_DETAIL ts_us=978694414140 pid=58268 gtid=1 uaddr=0x20102d478 op=0x80 val=1 word=1 word_status=0
     FUTEX_ARGS pid=58268 gtid=1 id=856 uaddr=0x20102d478 op=0x80 val=1 timeout=0x0 uaddr2=0x20102d478 val3=8605904736 word=1 ...
     IO_TX_ENTER pid=58268 gtid=1 id=856 nr=98 fd=8606897272 arg2=1 fd_status=0x0 arg2_status=0x0
     ```
  3. **新死锁点属性分析**：
     - **新目标地址**：`uaddr = 0x20102d478`；
     - **相对偏移关系**：`0x20102d478 - 0x20102d440 = 0x38 = 56 字节`！
     - **空间属性**：完全处于同一个匿名私有映射区间 `[0x200ffe000, 0x20106e000)` 内部；
     - **锁状态**：入参 `val=1`，当前内存读取值亦为 `word=1`（`ONCE_IN_PROGRESS`）；
     - **返回与调用点**：`ELR=0x2000ce084`, `LR=0x2000ce048`（同样处于 `pthread_once` 慢路径内）。

---

## 三、 对照数据详表 (Comparison Data Table)

| 指标 / 字段 | 对照组 (Baseline / 开关关闭) | 实验组 (Bypass / 开关开启) | 差异与技术定性 |
| :--- | :--- | :--- | :--- |
| **诊断开关状态** | `ELFUSE_DIAG_ONCE_BYPASS` 未设置 | `ELFUSE_DIAG_ONCE_BYPASS=1` | 严格受控单一变量 |
| **运行时 SHA256** | `c1698c1046c86067c8d71b11a328d0db07cf46344dc84f1c10e3eee5a2c01ef8` | 同一二进制 | 同一编译产物验证 |
| **落盘目录 (run_dir)** | `logs/once-bypass/baseline/run-4fy5uahy` | `logs/once-bypass/bypass/run-myqxkcq3` | 独立运行隔离落盘 |
| **Stderr 大小** | 717,937 字节 (物理文件一致) | 666,550 字节 (物理文件一致) | 真实物理文件校准 |
| **Stdout 大小** | 478 字节 (含完整 Step 3) | 478 字节 (含完整 Step 3) | 均达门槛 Step 3 |
| **运行耗时 / 退出码** | 62.13s / exit 124 (超时) | 62.12s / exit 124 (超时) | 均在超时保护下退出 |
| **有效性判定** | `run_valid = true (VALID)` | `run_valid = true (VALID)` | 均满足门槛规范 |
| **放行事件计数** | 0 次 | 1 次 (0x20102d440) | 诊断放行精确命中 |
| **死锁地址 1 (0x20102d440)** | 阻塞挂起直至 62s 超时 | **成功放行，耗时 51us 返回 0** | **首个缺口被跨越** |
| **死锁地址 2 (0x20102d478)** | 未曾执行到该处 (0 次) | **45us 后立即陷入该处死锁** | **确立下一个技术缺项** |

---

## 四、 下一个技术缺项与归因假设 (Next Technical Defect & Hypotheses)

通过放行实验，本任务清晰揭示了底层的真实运行模式：

1. **核心结论**：
   - `0x20102d440` 是 Windows ARM64 Vulkan 在此阶段遭遇的**首个截断点，但绝不是唯一缺口**；
   - 底层初始化并非单点孤立的单例，而是具有**结构体级或表级连续级联特性**（首个在 `0x2f440`，第二个紧随其后在 `0x2f478`，偏移增量恰好为 56 字节）。
2. **初步归因假设 (Causal Hypotheses)**：
   - **假设 1（模块化单例表）**：该 448 KiB 匿名私有段是某个复合驱动或框架（如 Mesa Vulkan ICD 内部的单例管理器）的数据结构池，内部由多个结构体串联，每个子系统在进入时均通过自己的 `pthread_once_t` 进行首次初始化；
   - **假设 2（系统性重入/未置 2 链条）**：导致 `0x20102d440` 保持为 1 的根因机制（例如外层执行流尚未完成其庞大的级联初始化即再次调用同一模块，或者某种架构异常使得初始化例程未能完整走完置 2 流程）在整个初始化子系统链条中**普遍存在**，导致每个被触及的 once 变量都停留在状态 1；
3. **验证与后续攻坚方向**：
   - 单纯在运行时打补丁逐个绕过（0x20102d440, 0x20102d478, ...）属于典型的“打地鼠”临时手段，无法作为工业级解法；
   - 彻底解决死锁必须落实此前提案的**指令级 HVC 断点计数器（在 `0x8e1a0` 处）**，直接从调用深度、进入次数与寄存器 X0 追踪全局调用链，从根源上治愈该初始化级联死锁。
