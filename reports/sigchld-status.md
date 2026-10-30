# SIGCHLD si_status 字段贯通修复与信号套件转绿报告 (Task-90)

**责任人**：evidence-reviewer-r36 (执行员)  
**遵循规范**：`test-driven-development`（Red-First 真实缺陷驱动、绿化验证、0回归）  
**关联任务**：Task-90（修复 SIGCHLD 的 si_status 缺口并让信号测试转绿）  
**交付制品**：
1. 修复源码与独立二进制：`sources/elfuse-sigchld-status-derived/build/elfuse` (SHA256: `459e44b0850797bbf0fd5777e34fcdb697da27a2dbb22ecab823b699fbef55ab`)
2. 修复前后对比补丁：`logs/sigchld-status/sigchld_status.patch`
3. 绿化验证测试收据：`logs/sigchld-status/receipt.json`
4. 综合验收总结报告：`reports/sigchld-status.md`

---

## 一、 修复前基线复核 (Red Baseline Verification)

执行既有测试套件 `scripts/runtime/signals/test_signals` 对基线运行时（`sources/elfuse-once-count-derived/build/elfuse`, SHA256: `24b488983f4c1be058657355c4ce894e446451e2dfa902a1fd5b618b81fe9b16`）进行全量跑测：
- **测试收据**：`logs/signals/signals_receipt.json`
- **进程退出码**：`exit = 32` (`failure_mask = 0x20`)，耗时 0.700s
- **基线实测输出**：
  ```text
  STARTING GUEST SIGNAL SEMANTIC SUITE (ARM64 LINUX)
  === Test 1: Basic Delivery & errno / sa_mask ===
  [TEST 1 PASS] Basic signal delivery and sa_mask verified
  === Test 2: SA_RESTART vs EINTR on blocking read ===
  [TEST 2a PASS] Blocking read returned EINTR without SA_RESTART (g_got_sig=14)
  [TEST 2b PASS] Blocking read successfully restarted with SA_RESTART and read data
  === Test 3: SA_SIGINFO siginfo_t Validation ===
  [TEST 3 PASS] SA_SIGINFO correctly delivered (si_signo=10, si_pid=1, si_code=0)
  === Test 4: sigaltstack Execution ===
  [TEST 4 PASS] Handler ran on altstack: SP=0x1042dd0 in [0x1034020, 0x1044020)
  === Test 5: sigprocmask Blocking & Pending Delivery ===
  [TEST 5 PASS] Signal held while blocked and delivered immediately upon unblock
  === Test 6: SIGCHLD & waitpid Interaction ===
  [TEST 6 FAIL] SIGCHLD si_status not populated: got 0 (expected 42)
  === Test 7: Timer Signals (setitimer & ITIMER_REAL) ===
  [TEST 7 PASS] setitimer ITIMER_REAL delivered 3 timer ticks
  SIGNAL_TESTS_FAILED failure_mask=0x20
  ```
- **根因确认**：测试 1、2a、2b、3、4、5、7 均全绿，仅测试 6 报红，确凿证实 `siginfo_t.si_status` 为 0 的未填充缺陷。

---

## 二、 修复方案设计与端到端贯通路径 (Minimal Architectural Fix)

### 1. 根因与缺口定位
在原代码中：
1. **结构体定义缺位**：`src/syscall/signal.h` 中的 `linux_siginfo_t` 仅定义了 `si_value`（8字节），未对 AArch64 Linux 的 `_sigchld` 联合体字段（`si_status`, `si_utime`, `si_stime`）进行声明；`signal_rt_info_t` 中亦无 `si_status` 槽位（被 `_pad` 占位）；
2. **信号分发零填充**：`src/syscall/signal.c` 的 `deliver_signal_locked` 与 `sigtimedwait` 在装配 `rt_sigframe` 时直接由 `memset` 留零，从未写入 `si_status`；
3. **跨进程 IPC 通信丢失**：子进程在 `src/syscall/proc.c` 的 `proc_process_exit` 中持有退出状态 `wait_status`，但在通过 `proc_send_guest_signal` 向父进程传输信号时，仅通过管道写入 `"%llu %lld %d
"`，未序列化子进程退出状态码与 `si_code`。

### 2. 最小改动贯通设计 (Minimal Surface Changes)
在独立派生目录 `sources/elfuse-sigchld-status-derived` 中进行针对性修复：
1. **数据结构对齐** (`src/syscall/signal.h`)：
   - 在 `linux_siginfo_t` 的联合体中显式增加 `_sigchld` 结构（包含 `int32_t si_status` 及 `si_utime` / `si_stime`），严守 `sizeof(linux_siginfo_t) == 128` 与 `offsetof(..., _sigchld.si_status) == 24` 静态断言；
   - 在 `signal_rt_info_t` 中将原 `uint32_t _pad` 替换为 `int32_t si_status`，严守 32 字节大小断言；
2. **跨进程序列化贯通** (`src/syscall/proc.c` / `proc.h`)：
   - 新增 `proc_send_guest_signal_info`，在管道通信行中附加信号元数据：
     `"%llu %lld %d %d %d %u %d
"`（依次传递 namespace, target_pid, signum, si_code, si_pid, si_uid, si_status）；
   - 在 `proc_process_exit` 中，解析 `wait_status`：
     - 若 `WIFEXITED(wait_status)`：设置 `si_code = CLD_EXITED (1)`，`si_status = WEXITSTATUS(wait_status)`；
     - 若 `WIFSIGNALED(wait_status)`：设置 `si_code = WCOREDUMP ? CLD_DUMPED (3) : CLD_KILLED (2)`，`si_status = WTERMSIG(wait_status)`；
     - 随信号行发往父进程，包括直接父进程与重新父进程化（reparented）的领养进程；
3. **接收端反序列化与入队** (`src/syscall/proc.c` & `src/syscall/signal.c`)：
   - 在 `sig_drain_cb` 中解析可选的附加参数，若存在则调用新增的 `signal_queue_chld_status`，将 `si_code`、`si_pid`、`si_status` 完整存入标准信号的 `std_info[signum - 1]`；
   - 保持向后兼容：若仅有基础 3 参数行，则平滑降级为常规 `signal_queue`；
4. **帧装配与用户态交付** (`src/syscall/signal.c`)：
   - 在 `deliver_signal_locked`（针对信号处理器入口）与 `sigtimedwait`（针对同步等待）中，当 `signum == LINUX_SIGCHLD` 时，明确将 `rt_info.si_status` 复制到 `frame.info._sigchld.si_status`（偏移 24 处）。

---

## 三、 修复后全量绿化实测 (Green Verification Results)

在同一测试套件 `scripts/runtime/signals/test_signals` 下，使用新编译的 `sources/elfuse-sigchld-status-derived/build/elfuse` 执行全量回归验证：
- **测试收据**：`logs/sigchld-status/receipt.json`
- **进程退出码**：`exit = 0` (全量 7 项测试 100% 通过)
- **执行时间**：0.732 秒，无超时
- **实测完整标准输出**：
  ```text
  STARTING GUEST SIGNAL SEMANTIC SUITE (ARM64 LINUX)

  === Test 1: Basic Delivery & errno / sa_mask ===
  [TEST 1 INFO] Handler observed outer errno=42, outer errno after handler=99
  [TEST 1 PASS] Basic signal delivery and sa_mask verified

  === Test 2: SA_RESTART vs EINTR on blocking read ===
  [TEST 2a PASS] Blocking read returned EINTR without SA_RESTART (g_got_sig=14)
  [TEST 2b PASS] Blocking read successfully restarted with SA_RESTART and read data

  === Test 3: SA_SIGINFO siginfo_t Validation ===
  [TEST 3 PASS] SA_SIGINFO correctly delivered (si_signo=10, si_pid=1, si_code=0)

  === Test 4: sigaltstack Execution ===
  [TEST 4 PASS] Handler ran on altstack: SP=0x1042dd0 in [0x1034020, 0x1044020)

  === Test 5: sigprocmask Blocking & Pending Delivery ===
  [TEST 5 PASS] Signal held while blocked and delivered immediately upon unblock

  === Test 6: SIGCHLD & waitpid Interaction ===
  [TEST 6 PASS] SIGCHLD received with si_status=42 and waitpid matched

  === Test 7: Timer Signals (setitimer & ITIMER_REAL) ===
  [TEST 7 PASS] setitimer ITIMER_REAL delivered 3 timer ticks

  =======================================================
  ALL_7_SIGNAL_TESTS_PASS
  ```

**验收指标达成**：
1. **测试 6 顺利转绿**：`si_status=42` 被 `SIGCHLD` 处理器准确捕获，且与 `waitpid` 状态码完全匹配；
2. **其余 6 项保持全绿**：1 (基本投递/sa_mask), 2a (EINTR), 2b (SA_RESTART), 3 (SA_SIGINFO), 4 (sigaltstack), 5 (sigprocmask), 7 (setitimer) 均继续稳定通过；
3. **回归风险评估**：0 回归，完全符合预期。

---

## 四、 改动差异统计与影响评估 (Diffstat & Impact Assessment)

### 1. Diffstat 统计
补丁文件：`logs/sigchld-status/sigchld_status.patch`
```text
 src/syscall/proc.c   |  107 +++++++++++++++++++++++++++++++++++++++++++++------------------
 src/syscall/proc.h   |    7 ++++
 src/syscall/signal.c |   34 ++++++++++++++++++++
 src/syscall/signal.h |   15 +++++++-
 4 files changed, 131 insertions(+), 32 deletions(-)
```

### 2. 二进制 SHA256 指纹
- **基线二进制** (`sources/elfuse-once-count-derived/build/elfuse`):  
  `24b488983f4c1be058657355c4ce894e446451e2dfa902a1fd5b618b81fe9b16`
- **修复后二进制** (`sources/elfuse-sigchld-status-derived/build/elfuse`):  
  `459e44b0850797bbf0fd5777e34fcdb697da27a2dbb22ecab823b699fbef55ab`

### 3. 对其他信号路径的影响评估
- **普通信号与 RT 信号**：非 `SIGCHLD` 信号仍走原有的 `si_value` / `si_addr` 复制分支，不受任何干扰；
- **`si_code` 与 `si_pid` 语义**：
  - 普通信号默认走 `LINUX_SI_USER`，发送者 PID 仍正确填充；
  - `SIGCHLD` 的 `si_code` 升级为标准的 `CLD_EXITED (1)` 或 `CLD_KILLED (2)`，`si_pid` 升级为真实子进程的 guest PID，行为更贴近原生 Linux 内核；
- **既有环境兼容性**：未修改任何已接受（accepted）二进制与既有历史收据，纯净保留在独立派生树中。
