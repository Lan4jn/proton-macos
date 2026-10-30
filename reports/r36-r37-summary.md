# R36 至 R37 证据汇总与综合验收报告

**交付汇总员**：evidence-reviewer-r36  
**审查与编制基准**：纯只读证据核验、逐条标注收据来源与验收状态、严格区分实证事实与推论边界  
**覆盖轮次与任务**：
- **Task-70 (Round 36)**：末端 private futex 模块归属与唤醒关系实测（`reports/futex-owner.md`）
- **Task-71 (Round 36)**：末端 futex 调用点 libc 符号与匿名区间角色分析（`reports/futex-libc-symbols.md`）
- **Task-72 (Round 36)**：guest 线程生命周期与 tid 49 消失时点追踪（`reports/thread-lifetime.md`）
- **Task-73 (Round 36/37)**：once 控制字为 1 成因判别四项测试（`reports/mem-once.md`）
- **Task-74 (Round 37)**：once 控制字 0x20102d440 值跃迁时间线（`reports/once-transition.md`）
- **Task-75 (Round 36)**：独立复核 R36 证据链（`reports/r36-independent-review.md`）
- **Task-76 (Round 37)**：独立核验 Task-74 once 跃迁时间线与自洽性（`reports/once-transition-review.md`）

---

## 一、 已验收确凿事实清单 (Verified Facts & Evidence Matrix)

以下条目均为各专职队员实测、收据 JSON 校验且经独立复核员双端核验通过的硬性技术事实：

### 1. 末端挂起位置与锁结构判定
- **挂起调用点**：处于 guest `libc.so.6`（glibc 2.43 aarch64）只读代码段 `[0x200040000, 0x2001ef000)` 中；
  - `ELR = 0x2000ce084`（段内偏移 `0x8e084`，紧随系统调用指令 `0x8e080 svc #0` 后的返回地址）；
  - `LR = 0x2000ce048`（段内偏移 `0x8e048`，紧随原子 CAS 探测 helper 后的返回地址）。
- **汇编控制流与锁类型**：
  - 偏移 `0x8e080` 发起系统调用：`SYS_futex` (nr=98), `x0 = 0x20102d440`, `op = 0x80` (`FUTEX_WAIT_PRIVATE`), `val = 1`, `timeout = NULL`；
  - 外部符号入口位于 `0x8e1a0 <pthread_once@@GLIBC_2.34>`（`call_once` @ 0x92380 跳转至此）；
  - `0x8e05c tbz w3, #0, 0x8e0c4`：当控制字 bit 0 为 1 时进入 `futex_wait`；在正常完成路径上，`0x8e120 stlr w0, [x4]` 存入 `2`，随后发起 `x1=0x81 (FUTEX_WAKE_PRIVATE), x2=INT_MAX` 广播唤醒；
  - **锁类型定性**：确凿判定为 **`pthread_once_t`（单次初始化控制字）**，当前内存值为 `1`，对应状态机中的 **`ONCE_IN_PROGRESS`（正在初始化中）**。
  - *证据来源*：`reports/futex-libc-symbols.md`、`logs/futex-symbols/pthread_once_disasm.txt`，已由 Lead 及审查员独立反汇编复核。

### 2. 内存归属与区间属性
- **目标地址**：`uaddr = 0x20102d440`；
- **内存映射属性**：确切位于匿名私有映射区间 `[0x200ffe000, 0x20106e000)`，大小为 `0x70000`（448 KiB），权限 `rw-`，标志位 `0x22` (`MAP_PRIVATE | MAP_ANONYMOUS`)，区间内相对偏移 `off = 0x2f440`；
- **排他性判定**：该地址**不在任何驱动 `.so`（如 `libvulkan_lvp.so`）的代码段或数据段中**，亦不在只读文件映射区，属于用户态堆/内存池动态分配的单例或结构体。
  - *证据来源*：`logs/futex-owner/vulkan/receipt.json`（FUTEX_OWNER_MAP tag=uaddr 逐字导出）。

### 3. 进程与线程拓扑事实
- **主 Wine 进程拓扑唯一**：在执行测试的 Wine 主进程（Task-70 PID 91073、Task-72 PID 92897、Task-74 PID 98953）中，**从始至终只有唯一活跃线程 `gtid=1`**；
  - 进程内部从未调用 `thread_alloc` 创建并发子线程；
  - 在全运行周期内，针对 `0x20102d440` 的 Futex 系统调用有且仅有 1 次（即末端本次挂起）；
  - 主进程内部无任何其他线程发起过 `FUTEX_WAKE`。
- **子进程 49 的生命周期与因果解耦**：
  - 事务 `id=729` 调用的 clone 参数为 `flags=0x1200011`（无 `CLONE_VM`，独立地址空间子进程）；
  - 子进程 49 仅存活 16.7ms 即通过 `SYS_exit_group(0)` 正常退出，并在事务 `id=731` 被主进程 `wait4` 彻底回收；
  - 发生于末端 Futex 挂起（`id=855`）前 124 个系统调用之前，**与末端锁状态无因果关联**。
  - *证据来源*：`logs/thread-lifetime/vulkan/receipt.json`（tid49_records 全量时序）。

### 4. 关键竞争假设的实验排除证据
通过 Task-73 的四项最小 ARM64 Linux 实测（在真实 elfuse 运行时下执行）：
1. **排除通用实现缺陷**：单线程下 `pthread_once(PTHREAD_ONCE_INIT)` 正常执行返回 0，未挂起（`test_once`, exit 0）；
2. **排除初值污染 / 堆复用残留（假设 B / 假设 A2）**：`mmap(MAP_PRIVATE|MAP_ANONYMOUS)` 分配 448 KiB 区间后，包括目标偏移 `0x2f440` 在内的全部采样点首读均为 `0x00`（`test_mmap_zero`, exit 0）；
3. **排除私有内存穿透 / 泄漏（假设 C）**：常规 `fork()` 以及与 Wine 实际调用完全一致的 `clone(flags=0x1200011)` 下，子进程对私有页写入 1，父进程 wait 后重读严格保持为 0x0，COW 隔离完好（`test_fork_cow`、`test_clone_variants`, exit 0）。
- *证据来源*：`logs/mem-once/summary.json`，已由 Lead 复跑确认。

### 5. 控制字 0x20102d440 的值跃迁时间线
低频内存状态采样器（1.0ms 轮询）捕获到的状态跃迁事实：
1. **未映射期**：`ts_us = 955474027498`: `val = 0x0`, `mapped = 0`（区域未建立）；
2. **首次建立映射首读**：`ts_us = 955523381988`: `val = 0x0`, `mapped = 1`, `reason = first_mapped`（段建立时首读**严格为 0x0**，进一步物理证实排除 A2）；
3. **数值单向写 1 跃迁**：`ts_us = 955523706195`: `val = 0x1`, `prev_val = 0x0`, `mapped = 1`, `reason = val_change`；
   - 跃迁发生于 `vkCreateInstance` 早期 ICD 打开与加载阶段；
   - **两事件采样检出间隔**：$$955523706195 - 955523381988 = 324,207 	ext{ µs} = mathbf{324.207 	ext{ ms}}$$
4. **末端挂起**：随后在事务 `id=855` 处，主线程再次到达该控制字，读取值为 1，陷入 `FUTEX_WAIT_PRIVATE` 休眠直到 62s 超时。
- *证据来源*：`logs/once-trace/vulkan/receipt.json`（once_transitions 记录）。

---

## 二、 未证推测与排他性假设边界 (Unproven Hypotheses & Limits)

必须严格区分“有物理证据的观测”与“基于逻辑反推的推论”：

1. **“主线程 CAS(0->1)”属于语义推断，非直接指令观测**：
   - 采样器为 1.0ms 周期被动轮询，记录了数值在某一采样周期内变为 1；
   - **未捕获到指令瞬间**：观测器从未在指令级直接捕获 `casa` / `stxr` 汇编指令执行时的 PC 与寄存器快照。因此，“由主线程执行 CAS(0->1)”是基于其为唯一存活线程和 glibc 源码控制流的强推断。
2. **“单线程递归重入自锁”属于强证据排他性推测，非绝对证实事实**：
   - 虽然已排除多线程 waker 丢失、排除子进程泄漏、排除初值非 0，使“递归重入”成为解释力最强的候选模型；
   - **残留盲区**：在未捕获到第 1 次置 1 与第 2 次 futex wait 的两次完整用户态调用栈（Userland Backtrace）之前，**依然不能完全排除“初始化例程在置 1 后因某些非致命返回/长跳转未能置 2，导致单例遗留在脏状态 1，后续正常调用到达时被误锁”的异常退出分支**。
   - **定性准则**：在后续交付中一律表述为**“强证据排他性推测”**，撤销“确凿证实”的断言。

---

## 三、 全局仍未实证项清单 (Open Gaps)

以下高层目标在当前研究阶段依然明确未达成，严禁过度宣称：
1. **Windows Vulkan 图形设备与渲染流水线未实证**：当前测试仅推进到 `vkCreateInstance` 内部加载阶段，Vulkan 物理设备枚举、队列创建及帧缓冲区渲染未见返回；
2. **原生 Steam 客户端与 Steamworks 运行未实证**：仅完成了离线无 Steam 的最小控制台与环境准备，点击 Steam Play、Steamworks API 通信未验证；
3. **Valve 官方直接签名未实证**：当前运行的 ARM64 Proton 包来源于经过校验的公开二次分发镜像，非独立 Valve 签名源；
4. **正确的 COW（写时复制）实现未完成**：当前所有衍生诊断运行时均继承了 `ELFUSE_DIAG_SESSION_SHARED=1` 诊断门禁，牺牲了真正的进程隔离以换取特定共享映射可见性，并非产品级 COW 机制。

---

## 四、 本轮独立复核暴露的系统性流程教训 (Lessons Learned)

在 R36–R37 连续四轮独立复核中，审查员连续纠正了三类高发性系统缺陷，应作为团队后续开发的硬性警示：

1. **单位量级错误（1000 倍混淆）**：
   - *教训事实*：Task-74 报告将真实物理差值 324207 微秒（324.207 毫秒）除以 1000 得到 324.2 后，直接错标为微秒（“324.2 微秒”），导致理论上与 1.0ms 采样周期直接冲突；
   - *规范改进*：所有数值引用必须严格区分秒（s）、毫秒（ms）与微秒（µs/us），严禁手工换算时不核对物理量纲。
2. **跨轮次机械复用旧数值（张冠李戴）**：
   - *教训事实*：`stderr_bytes = 149432` 是 Task-70 的特定日志大小；在 Task-72 中因日志扩增至 666817 字节，报告却抄袭旧值 149432 被勘误；而在 Task-74 中，日志进一步扩增至 685764 字节，报告第三次照搬 149432！
   - *规范改进*：所有运行度量指标必须直接从当次运行的 `receipt.json` 中脚本化提取，禁止从历史报告模板中手工复制粘贴。
3. **运行目录 (`run_dir`) 路径失效与虚标**：
   - *教训事实*：Task-72 填写的 `run-5k49m17s` 与 Task-74 填写的 `run-d19x74b_` 在磁盘上完全不存在（ENOENT），而真实有效数据分别落盘于 `run-iagdhuck` 与 `run-rx848drl`；
   - *规范改进*：交付报告中的 `run_dir` 必须是实际落盘且通过 `ls / stat` 校验的绝对路径，严禁使用重试过程中被废弃的临时目录名称。

---

## 五、 最终统一勘误核验表 (Reconciliation Matrix)

| 轮次 / 任务 | 报告原记录（错误/失效） | 收据及磁盘真实值（正确） | 勘误核验状态 |
| :--- | :--- | :--- | :---: |
| **Task-72** `reports/thread-lifetime.md` | `run_dir = run-5k49m17s` (ENOENT) | `run_dir = run-iagdhuck` (真实存在) | **已修正** |
| | `stderr_bytes = 149432` | `stderr_bytes = 666817` | **已修正** |
| | “确凿证实假设 B（递归自锁）” | 修正为“未证推断 / 强候选推测” | **已修正** |
| **Task-74** `reports/once-transition.md` | `run_dir = run-d19x74b_` (ENOENT) | `run_dir = run-rx848drl` (真实存在) | **已修正** |
| | `stderr_bytes = 149432` | `stderr_bytes = 685764` | **已修正** |
| | 跃迁差值 “324.2 微秒” | 真实差值 **324.207 毫秒 (ms)** | **已修正** |
| | “确凿证实假设 A” | 修正为“强证据排他性推测” | **已修正** |
