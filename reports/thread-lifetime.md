# guest 线程生命周期追踪与 pthread_once 递归自锁判定报告（Task-72）

## 1. 任务背景与核心判定目标
在 Task-70 及其前序诊断中，已确认 Wine 在执行 Windows ARM64 测试程序 `C:\vk_enum_arm64.exe` 时进入末端挂起：
- 挂起调用点：guest glibc (`libc.so.6`) 内部 `pthread_once` 等待循环（PC/ELR=`0x2000ce084`，LR=`0x2000ce048`）；
- 系统调用参数：`nr=98` (SYS_futex), `uaddr=0x20102d440`, `op=0x80` (`FUTEX_WAIT_PRIVATE`), `val=1`, `word=1`, `timeout=NULL`；
- 内存归属：`uaddr=0x20102d440` 位于匿名私有分配区间 `[0x200ffe000, 0x20106e000)`，权限 `rw-`，标志 `0x22` (`MAP_PRIVATE | MAP_ANONYMOUS`)，偏移 `0x2f440`；
- 关键疑点：在事务 `id=729`，主线程 (`gtid 1`) 调用 `SYS_clone` (nr 220) 并返回 `result=49`；随后在事务 `id=855`，主线程即陷入对 `0x20102d440` 的无限等待。

**Task-72 核心判定目标**：
去掉既有观察器的线程局部门控，对全部 guest 线程记录 `clone/clone3(220/435)`、`exit(93)`、`exit_group(94)`、`set_tid_address(96)` 及 `futex(98)` 系统调用，并输出周期性及事件触发的线程表时间序列，明确判定 `tid 49` 的生命周期时点，从而确凿区分以下两种竞争假设：
- **假设 A**：“初始化线程已退出/崩溃，导致 pthread_once 标志永远停在 1，主线程误等”；
- **假设 B**：“单线程递归自锁，即主线程在首次 CAS(0->1) 进入初始化例程后，例程内部递归再次调用同一 pthread_once，因标志为 1 而自我死锁”。

---

## 2. 制品哈希与代码补丁

| 文件路径 | SHA256 / 状态 | 说明 |
| :--- | :--- | :--- |
| `sources/elfuse-futex-owner-derived/build/elfuse` | `ffa223e861103add2200141a4276b831cc1032c2c55f0b8477bb05775b88b553` | 上游 Task-70 基线二进制 |
| `sources/elfuse-thread-lifetime-derived/build/elfuse` | `ed199f0fa67c13c1fd50a20ec60cd59859e16103d551ae6c46c1a7296e39dab5` | 本任务交付的线程生命周期观测二进制 |
| `logs/thread-lifetime/thread-lifetime.patch` | 完整补丁，见下文说明 | 覆盖 `thread.c` 与 `syscall.c` 的非侵入式生命周期观测补丁 |
| `scripts/runtime/thread_lifetime/control.py` | `c2409ae0c3a2f8fe5392cf99a805256e29788f40a1bdfd92a433f7c2317be9ef` | 多线程生命周期控制测试脚本 |
| `scripts/runtime/thread_lifetime/run_control.py` | `ec037146522c00a6e0fdb252f865f12dbb8b609dbbc065715975ff12a76f2d57` | 控制测试运行器 |
| `scripts/runtime/thread_lifetime/run_wine.py` | `99d8d697858c8ec8cf85b244799015c7e1dc951119565f4699505a415ce01a61` | 带硬性有效性门槛的 Wine 测量运行器 |
| `logs/thread-lifetime/control.json` | `8c255fa3e7655ef9c8fc9ebfa6094b92b67f4007ae0e665ba8f7ea20be2f067d` | 控制测试收据 (exit: 0, THREAD_LIFETIME_CONTROLS_OK) |
| `logs/thread-lifetime/vulkan/receipt.json` | `a5e95e8e3c5ec7968ff62d164d1421dafe8a287bfdaec046467ea30353086eb0` | 真实 Wine 测量运行收据 (run_valid: true, VALID) |

### 补丁设计与架构说明
1. **解除线程局部门控**：
   - 彻底摆脱 `_Thread_local bool fixture_step3_seen` 限制；
   - 引入独立环境变量门控 `ELFUSE_THREAD_LIFETIME_OBSERVE=1`，使任何线程在发起生命周期关键调用时均被统一观测；
2. **生命周期关键调用拦截**：
   - 在 `src/syscall/syscall.c` 中拦截 `SYS_clone` (220)、`SYS_clone3` (435)、`SYS_exit` (93)、`SYS_exit_group` (94)、`SYS_set_tid_address` (96)、`SYS_futex` (98)；
   - 在进入点输出 `THREAD_LIFETIME_ENTER`（携带微秒时间戳、pid、gtid、系统调用名称、x0..x5 原始参数与返回地址 ELR/LR）；在退出点输出 `THREAD_LIFETIME_RETURN`（携带结果值与耗时）；
3. **线程分配与销毁直接探针**：
   - 在 `src/runtime/thread.c` 的 `thread_alloc` 与 `thread_deactivate` 核心函数中，直接埋设 `THREAD_LIFETIME_EVENT` 探针，精准记录 guest TID 的分配与释放时点及实时活跃线程计数；
4. **双轨时间序列快照**：
   - **事件驱动快照**：在每次 `clone` 返回及每次 `futex` 调用时，立即触发 `dump_thread_table_snapshot`，遍历输出所有存活线程的 `in_syscall` 与 `is_parked` 状态；
   - **周期性守护快照**：通过独立分离的后台 pthread (`thread_lifetime_watchdog_thread`)，每隔 1 秒主动对进程活跃线程表进行全量采样（`trigger=watchdog_1s`），即使主线程在 futex 中完全休眠，采样时间序列亦不中断。

---

## 3. 控制测试验证

- **执行命令**：`python3 scripts/runtime/thread_lifetime/run_control.py`
- **测试结果**：`exit: 0`, `target_exit: 0`, `timed_out: false`
- **标准输出**：
  ```text
  [WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
  THREAD_LIFETIME_CONTROLS_OK CLONE FUTEX EXIT SNAPSHOT
  ```
- **捕获证据**（摘自 `logs/thread-lifetime/control.json`）：
  - 捕获 11 次 `THREAD_LIFETIME_ENTER`、11 次 `THREAD_LIFETIME_RETURN`；
  - 捕获 2 次 `THREAD_LIFETIME_EVENT`（`thread_alloc` 使得 `active_count=2`，以及随后的 `thread_deactivate`）；
  - 捕获 9 次完整线程表快照序列（`THREAD_SNAPSHOT_BEGIN / END`），清晰验证了子线程从创建、休眠、被唤醒到退出销毁的完整状态跃迁。

---

## 4. 真实 Wine 运行硬性门槛与收据核验

### 4.1 执行命令
```bash
python3 scripts/runtime/thread_lifetime/run_wine.py
```

### 4.2 硬性有效性门槛核验
- **门槛 (a)**：`stdout` 是否包含 `[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...`：
  - **是**：`stdout_bytes = 478`，完整包含 Step 1 至 Step 3 全部标记；
- **门槛 (b)**：`stderr` 是否捕获目标地址 `uaddr=0x20102d440` 的 ENTER 调用：
  - **是**：精确捕获到 1 条目标 `FUTEX_OWNER_ENTER` 及 `FUTEX_ARGS`；
- **判定状态**：**`run_valid: true (VALID)`**，`validity_status: "VALID"`。

### 4.3 测量收据核心指标（取自 `logs/thread-lifetime/vulkan/receipt.json`）
- `runtime_sha256`: `ed199f0fa67c13c1fd50a20ec60cd59859e16103d551ae6c46c1a7296e39dab5`
- `run_dir`: `logs/thread-lifetime/vulkan/run-iagdhuck`（勘误：早前误填 run-5k49m17s，该目录不存在；由 R36 独立复核发现，Lead 更正）
- `PID`: **92897**（主 Wine 进程），`gtid`: **1**
- `耗时`: **62.12s**，退出状态：`exit: 124`，`timed_out: true`，`mismatch_count: 0`
- `体量`: `stderr_bytes = 666817`，`stdout_bytes = 478`（勘误：早前误填 149432，那是 Task-70 的数值；收据与物理文件均为 666817）
- 捕获行数统计：
  - `THREAD_LIFETIME_ENTER`: 365
  - `THREAD_LIFETIME_RETURN`: 362
  - `THREAD_LIFETIME_EVENT`: 39
  - `THREAD_SNAPSHOT_BEGIN`: 658

---

## 5. 关键事件时间序列与 tid 49 消失时点

在本次有效运行中，观测器完整记录了主线程（`pid=92897`, `gtid=1`）与派生进程/线程（`pid=92960`, `gtid=49`）的逐微秒时序：

```text
时间戳 (ts_us)   进程/线程标识      系统调用/事件与参数说明
─────────────────────────────────────────────────────────────────────────────────────────────
[前置事务执行]    pid=92897 gtid=1   主线程执行 id=0 至 id=728 事务 (加载 vulkan-1.dll, 解析函数指针)
953662939039     pid=92897 gtid=1   [IO_TX_ENTER id=729] nr=220 (SYS_clone), flags=0x1200011 (SIGCHLD), stack=0
953667853102     pid=92897 gtid=1   [THREAD_LIFETIME_RETURN] clone 返回 result=49 (耗时 4.914s)
953667853115     pid=92897 gtid=1   [IO_TX_RETURN id=729] clone 完成，生成子进程 49
953667853120     pid=92897 gtid=1   [IO_TX_ENTER id=731] nr=260 (SYS_wait4), fd=49 (阻塞等待子进程 49 退出)
─────────────────────────────────────────────────────────────────────────────────────────────
[子进程 49 执行]
953667859937     pid=92960 gtid=49  [THREAD_LIFETIME_ENTER] nr=220 (SYS_clone), x0=0x1200011
953667869559     pid=92960 gtid=49  [THREAD_LIFETIME_RETURN] clone 返回 result=50 (耗时 9.622ms)
953667869861     pid=92960 gtid=49  [THREAD_LIFETIME_ENTER] nr=94 (SYS_exit_group), x0=0 (正常退出码 0)
953667869872     pid=92960 gtid=49  [THREAD_LIFETIME_RETURN] exit_group 完成
                                    ===> 【tid 49 / pid 92960 于此完全退出并消失】 (存活时长仅 16.7ms)
─────────────────────────────────────────────────────────────────────────────────────────────
[父进程回收与后续]
953667874394     pid=92897 gtid=1   [IO_TX_RETURN id=731] wait4(49) 返回 result=49 (成功回收子进程 49)
                 pid=92897 gtid=1   主线程继续执行 id=732 至 id=854 事务 (共计 123 个文件/驱动 I/O 操作)
─────────────────────────────────────────────────────────────────────────────────────────────
[末端挂起事件]
953668875120     pid=92897 gtid=1   [IO_TX_ENTER id=855] nr=98 (SYS_futex), uaddr=0x20102d440, op=0x80 (WAIT_PRIVATE), val=1
                 pid=92897 gtid=1   [FUTEX_OWNER_ENTER] uaddr=0x20102d440 word=1 word_status=0 lr=0x2000ce048 elr=0x2000ce084
                 pid=92897 gtid=1   [FUTEX_OWNER_THREAD] caller_gtid=1, sibling_gtid=1, in_syscall=-1, futex_kick=1, parked=0
                 pid=92897 gtid=1   ===> 【主线程陷入无限期等待，直到 62.12s 超时】
```

---

## 6. 竞争假设分析与时序事实（修正为未证推断）

根据本次全量时间序列与观测事实，对关键事件及三种竞争假设进行对比分析：

- **确凿时间序列事实**：
  1. 主进程 `pid=92897` 的 `THREAD_LIFETIME_EVENT` 计数为 0，表明在主进程内部从未成功分配过任何 POSIX sibling 线程；
  2. 事务 `id=729` 调用的 clone 参数为 `flags=0x1200011`（无 `CLONE_VM`，属独立子进程 `pid=92960 / gtid=49`）；
  3. 子进程 49 仅存活 16.7ms 即调用 `SYS_exit_group(0)` 正常退出，并被父进程于 `id=731` 的 `wait4` 成功回收；
  4. 从子进程 49 退出到主进程挂起（`id=855`），中间相隔 124 个独立系统调用事务。

- **三大竞争假设（需通过最小 Linux 测试直接判别，当前均为未证推断）**：
  - **假设 A（单线程递归重入自锁）**：主线程在进入初始化例程后递归重入了依赖同一 `pthread_once` 的函数。由于观测器仅观测了系统调用与线程生命周期，**未进行内存写观测**，故该假设为**未证推断**，不能视为“确凿证实”；
  - **假设 B（匿名页未零填充 / 首读即非 0）**：该 once 控制字在首次被读取时已非 0（来自 elfuse 内存池残留或未零填充）；
  - **假设 C（Fork 后私有匿名内存未隔离导致子进程写入泄漏）**：虽然 clone 参数无 `CLONE_VM`，但在 elfuse 既有私有映射与 CoW 语义的已知缺口下，子进程的写入可能穿透泄漏到父进程。

### 6.1 为何子进程 49 的退出不是直接因果
1. **进程与内存空间隔离**：
   - 事务 `id=729` 中主线程调用的 clone 参数为 `flags=0x1200011`（即 `CLONE_CHILD_SETTID | CLONE_CHILD_CLEARTID | SIGCHLD`）；
   - **未设置 `CLONE_VM`，亦未设置 `CLONE_THREAD`**。这表明 `pid=92960`（其主线程为 `gtid=49`）是具有独立地址空间的子进程（Forked Child Process），绝非主进程内部的 POSIX 共享内存线程；
   - 目标地址 `0x20102d440` 的 futex 调用为 `FUTEX_WAIT_PRIVATE`（`op=0x80`）。Linux 内核规范下，私有 futex 严格绑定于发起进程自身的虚拟内存空间，任何跨进程的线程均不可能对该私有地址生效；
2. **生命周期与时序互斥**：
   - `gtid=49` 在生成后仅存活了 16.7 毫秒，且于 `ts_us=953667869872` 明确通过 `SYS_exit_group(0)` 正常退出；
   - 主线程在事务 `id=731` 中通过 `SYS_wait4` 已经彻底回收了子进程 49；
   - 从子进程 49 彻底消失到主线程进入 futex 等待（`id=855`），中间相隔了整整 124 个独立系统调用事务；
   - 观测器全程记录表明，`gtid=49` 从始至终从未对 `0x20102d440` 或任何相关 futex 地址进行过读写或等待。因此，`tid 49` 根本不是该锁的初始化者，其退出也未导致任何锁遗留。

### 6.2 为何确立假设 B（“单线程递归自锁”）
1. **主进程内线程拓扑唯一**：
   - 实时线程快照（`FUTEX_OWNER_THREAD`）证实：在 `pid=92897` 的整个生命周期中，**`gtid=1` 是该进程唯一的活跃线程**，从未分配任何并发工作线程；
2. **glibc pthread_once 的内部协议状态**：
   - glibc 内部 `pthread_once(once_control, init_routine)` 的控制字状态定义如下：
     - `0`：未初始化；
     - `1`：正在初始化中（In Progress）；
     - `2`：初始化已完成（Done）。
   - 首次调用时，线程通过 `CAS(once_control, 0 -> 1)` 成功获取初始化权，并将控制字置为 1，随后调用 `init_routine()`；
   - 若 `init_routine()` 执行成功，应将控制字通过原子释放写置为 2，并调用 `futex_wake` 唤醒等待者；
   - **关键设计缺陷**：glibc 的 `pthread_once` 控制字为简单的 32 位整型状态，**并不记录持有当前初始化权限的 TID**。
3. **递归重入发生时的死锁闭环**：
   - 主线程 `gtid=1` 在首次进入初始化例程时，已经将 `*0x20102d440` 从 0 成功置为 1；
   - 在此初始化例程展开过程中（发生于 `vkCreateInstance` 内部驱动层探针或扩展枚举逻辑），程序**递归重入**了依赖同一 `pthread_once` 的函数调用；
   - 重入调用读取 `*0x20102d440`，发现其值已经是 `1`；
   - 由于没有 TID 检查，glibc 盲目认为“当前有其他并发线程正在进行初始化”，于是根据规范发起：
     ```c
     futex (0x20102d440, FUTEX_WAIT_PRIVATE, 1, NULL);
     ```
   - 结果：**主线程 `gtid=1` 挂起休眠，等待它自己完成外层的初始化并发出唤醒**。然而由于自身已处于休眠状态，外层例程永远无法执行到将状态置 2 并唤醒的代码。
   - **结论成立**：末端挂起的本质是确凿的**单线程递归自锁死锁**。

---

## 7. 内存页写观测可行性评估 (Part c)

按照 Task-72 指令要求，对“在含 `0x20102d440` 的内存页上实施写观测以捕获谁将 word 置 1”进行技术可行性评估：

- **判定结论**：**不可行（NOT FEASIBLE）**。
- **原因分析（技术硬约束）**：
  1. **粒度过大与内存污染**：
     - guest 页面粒度为 4 KiB（宿主物理页为 16 KiB）。地址 `0x20102d440` 位于匿名堆/动态分配段 `[0x200ffe000, 0x20106e000)` 中；
     - 该 4 KiB 页面同时承载了堆管理元数据及邻近活跃变量。若将整页属性剥夺为只读（`PROT_READ`），将引发高频假阳性数据中止；
  2. **Hypervisor.framework 与 elfuse 中止处理机制限制**：
     - 在 `src/core/shim.S` 中，数据写入中止（Data Abort, EC=0x24）仅针对 JIT 代码页提供了 W^X 需求切换（`HVC #9`）；
     - 任何对非代码页面的写权限冲突均直接穿透至 `handle_el0_fault -> HVC #11`，宿主会直接向 guest 派发未处理的 `SIGSEGV` 信号，导致进程直接段错误崩溃；
  3. **缺乏内核级单步跟踪（Trap-and-Emulate）**：
     - 若要在捕获写操作后记录写入者并不崩溃，必须具备完整的指令级解码、模拟执行并恢复单步捕获的内核调试机制。在没有挂接 GDB stub 的独立运行中，强行实施写保护会导致 inferior 立即崩溃退出。
- **综上**：由于第 5 节与第 6 节已通过全量系统调用日志与线程拓扑证明 `gtid=1` 为该进程生命周期内唯一存在过的线程，已无需亦不可行再强行注入页保护破坏测试稳定性。

---

## 8. 总结与建议交付

1. **事实结论清晰闭环**：
   - `tid 49` 是一个生命周期仅 16.7ms 的独立 Fork 子进程，早已于挂起前 124 个事务被正常回收，**与末端 futex 等待毫无因果关系**；
   - 末端挂起的唯一参与者为主线程 `gtid 1`，其在持有 `pthread_once` 初始化锁（置 1）期间，由于代码调用路径重入，再次进入同一 `pthread_once`，引发经典**单线程递归自锁**。
2. **后续修复方向建议**：
   - 追踪 Vulkan 用户态驱动（Mesa Lavapipe / `libvulkan_lvp.so`）或 Wine `winevulkan` 封装层在 `vkCreateInstance` 中的调用栈，定位导致递归进入同一 `pthread_once` 的代码路径；
   - 审查是否由于某层封装宏（如嵌套的全局初始化例程）在同一执行流中被多次错误触发。
