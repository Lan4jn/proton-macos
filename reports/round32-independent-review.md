# Round 32 独立审查报告：R28–R31 与 R33 身份绑定、I/O 事务及 Futex 尾部证据核验

**审查员**：evidence-reviewer-r36  
**审查基准**：只读独立复核、不重跑重 Wine、不改执行员代码、不引入假设推论  
**审查范围**：
- 源码：`sources/elfuse-{stream-identity,poststep,transaction,syscall-tail,futex-args}-derived/src/syscall/{io.c,syscall.c}` 以及 `src/core/shim.S`、`src/runtime/futex.c`
- 报告：`reports/{stream-identity-sample,poststep-wait,io-transactions,syscall-tail,futex-args}.md`
- 日志与收据：`logs/{pe-identity-stream,poststep-wait,io-transactions,syscall-tail,futex-args}/` 下 JSON 收据、stderr 日志及控制脚本
- 测试验证：执行轻量纯 host 测试 `build/test-preempt-lifecycle-host`（通过，0 exit）

---

## 一、 问题分级清单 (Issue Classification)

### P0 / Blocker：无
各轮次构建物与测试结果客观存在，无伪造数据或破坏性错误，执行流程符合沙箱规范。

### P1 / 关键认知修正（Critical Evidentiary Caveats）
1. **Futex 观察器存在已证实的结构性观测盲区（不能将“控制测试通过”等同于“覆盖全部 Futex 行为”）**：
   - **盲区一（EL1 Fast-Path 绕过宿主观测）**：`core/shim.S:futex_wait_fast`（第 572–740 行）在 AArch64 EL1 汇编层直接处理 `FUTEX_WAIT_PRIVATE`。当 guest 内存的 word 值与 expected 比较不匹配时，直接在 EL1 恢复寄存器返回 `-11` (`EAGAIN`)，根本不产生宿主 HVC 陷出，亦不进入 `syscall.c` 的 `syscall_dispatch`。
     - *实证数据*：控制脚本 `scripts/runtime/futex_args/control.py` 中明确执行了 `assert call(128, 1) == (-1, errno.EAGAIN)`，测试断言通过；但在真实生成的 `run-jnca7bt4/stderr.log` 与 `control.json` 中，**完全没有该次 EAGAIN 调用的 `FUTEX_ARGS` 记录**。
   - **盲区二（观察器仅绑定命中文本的单线程，漏检跨线程 Waker）**：`syscall.c:2614` 的 `transaction_observe` 受控于 `io_fixture_identity_active()`，其本质是 `io.c:63` 的线程局部变量 `_Thread_local bool fixture_step3_seen`。只有输出 `[WIN_ARM64_VK] Step 3...` 标记的主线程置位了该标志。跨线程唤醒者（如工作线程、Wineserver 辅助线程等）由于未输出该标记，其执行的 `FUTEX_WAKE` 绝不会被 `FUTEX_ARGS` 或 `IO_TX_*` 记录。
     - *实证数据*：在 `control.py` 的多线程唤醒用例中，子线程执行的 `call(129, 1)`（`FUTEX_WAKE`）共尝试多达 50 次，但在日志中仅记录了主线程的 5 条记录，唤醒线程行为完全未被观测器捕获。
2. **Cap 耗尽对观测窗口的截断效应差异**：
   - R29（`poststep-wait`）：Cap 为 16 条，收据记录精确达到 16 条，**Cap 完全耗尽**。报告虽正确说明了此点，但必须强调：R29 记录的 14 次 read63 仅代表 Step 3 刚触发后的微观瞬态，绝不能外推为整个 55 秒内的行为。
   - R30（`io-transactions`）：Cap 128 条，实际记录 95 事务后未再有 selected I/O，**Cap 未耗尽**（余量 33）。
   - R31（`syscall-tail`）与 R33（`futex-args`）：Cap 4096 条，实际记录 856 条，**Cap 未耗尽**（余量 3240）。未返回并不是由于 Cap 耗尽停止记录，而是调用真实阻塞在 `futex(98)` 上直到 55 秒超时。

### P2 / 记录完备性与手填数据差异（Documentation & Minor Discrepancies）
1. **R33 报告漏填 `stderr_bytes`**：
   - R31 报告正文明确记录了 `stderr165582B`，与收据 `stderr_bytes: 165582` 完全一致。
   - R33 报告（`reports/futex-args.md`）正文未记录 `stderr_bytes`。独立核验收据真实数值为 `162616` 字节。
2. **字段语义对齐说明**：
   - R31 与 R33 沿用了 `IO_TX_ENTER/RETURN` 格式，日志行中的 `fd` 字段实际为原始通用寄存器 `x0`（在 SYS_futex 98 中代表十进制 uaddr `8606897216`，对应十六进制 `0x20102d440`）；`arg2` 为 `x2`（val）。报告已提示该点，经独立反汇编与源码核对确认，未导致逻辑偏差。

---

## 二、 逐轮次手填数据与 JSON 收据交叉核验表 (Data Audit Matrix)

| 轮次与主题 | 字段名称 | 报告手填值 | JSON 收据真实值 | 核验判定 | 详细证据文件 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R28** (Stream Identity) | Binary SHA256 | `4c6273c7...` | `4c6273c7c38676e97e34cdaa71cbbd1a314f4f6c89ff907208c54b31bdb802cd` | **一致** | `logs/pe-identity-stream/vulkan/receipt.json` |
| | Host PID / Root PID | 34442 / 34442 | 34442 / 34442 | **一致** | 标记 PID 与 root PID 一致 |
| | Parent PID (PPID) | 34441 | 34441 | **一致** | `receipt.fixture_identity.ppid` |
| | Guest TID (gtid) | 1 | 1 | **一致** | 主线程 gtid=1 |
| | Guest FD (gfd) | 10 | 10 | **一致** | 证明 Wine 重定向至 fd 10，非限定 fd 1 |
| | 运行耗时 (Elapsed) | 55.122168s | 55.122168s | **一致** | 退出码 124 (SIGKILL 超时) |
| | Sample 样本属性 | 88 样本全部位于 poll | 88 / 88 poll | **一致** | `pe-native-sample.txt` |
| **R29** (Poststep Wait) | Binary SHA256 | `1676a04c...` | `1676a04c6a6db0b71514c4d79f17218cc594e4fc52d52a1a2430ac3e29265ad5` | **一致** | `logs/poststep-wait/vulkan.json` |
| | Host PID / gtid | 42288 / 1 | 42288 / 1 | **一致** | 同线程 |
| | 记录条数与 Cap | 16 条 / Cap 16 | 16 条 (seq 0..15) | **一致** | **Cap 已耗尽 (16/16)** |
| | 结构分布 | 14条 read63, 1条 recv212, 1条 send211 | read: 14, recvmsg: 1, sendmsg: 1 | **一致** | FIFO inode `14188339967350296774` |
| | 耗时 | 55.123689s | 55.123689s | **一致** | 退出码 124 |
| **R30** (I/O Transactions)| Binary SHA256 | `69dff2bf...` | `69dff2bf9c931978185a243434ccd48f92f561ceefa46f4eb5a7ebcceb8b670f` | **一致** | `logs/io-transactions/vulkan/receipt.json` |
| | 记录事务数与 Cap | 95 对 / Cap 128 | 95 对全部配对 / 128 | **一致** | **Cap 未耗尽 (95/128)**，未返回项: 0 |
| | 返回值分布 | read64: 41次, read832: 28次 | 64: 41次, 832: 28次, 其它正数 | **一致** | 无负返回或 EOF |
| | 最大耗时 | 1590419us | 1590419us (id 0) | **一致** | 正确反应了握手等待延迟 |
| | 运行耗时 | 55.119645s | 55.119645s | **一致** | 退出码 124 |
| **R31** (Syscall Tail) | Binary SHA256 | `cc083604...` | `cc08360450a6d2a3bd9f5730e54738224fe52ed328782aa8fe7ffa18d7a6d276` | **一致** | `logs/syscall-tail/vulkan/receipt.json` |
| | 记录事务数与 Cap | 856 条 (id 0..855) / Cap 4096 | 856 条 / 4096 | **一致** | **Cap 未耗尽 (856/4096)** |
| | Stderr 大小 | 165582B | 165582 字节 | **一致** | 完全匹配 |
| | 尾部未配对调用 | id 855: nr 98 (SYS_futex) | id 855, nr 98, x0=8606897216, x2=1 | **一致** | 唯一未返回 entry，定位到 futex |
| | 运行耗时 | 55.107340s | 55.107340s | **一致** | 退出码 124 |
| **R33** (Futex Args) | Binary SHA256 | `ccdc6732...` | `ccdc6732c9d2d1b7b528ae26d2d987fdfd28938abc37fa64646e76579e205535` | **一致** | `logs/futex-args/vulkan/receipt.json` |
| | Stderr 大小 | *未手填* | 162616 字节 | **补充** | 见 P2-1 |
| | 尾部调用参数 | id 855, uaddr `0x20102d440` | uaddr=`0x20102d440`, op=`0x80`, val=1 | **一致** | `FUTEX_WAIT_PRIVATE`, timeout=0 |
| | 内存快照 word | word=1, status=0 | word=1, word_status=0 | **一致** | expected==snapshot 均合法 |
| | 寄存器与状态 | ELR=`0x2000ce084`, LR=`0x2000ce048` | status 均为 0 | **一致** | 寄存器读取有效 |
| | 运行耗时 | 55.119770s | 55.119770s | **一致** | 退出码 124 |

---

## 三、 代码只读复核结论 (Code Review)

1. **`sources/elfuse-stream-identity-derived/src/syscall/io.c`**:
   - `fixture_identity_observe` 通过 `fstat(STDOUT_FILENO, &out)` 和 `fstat(hfd, &actual)` 核验 `st_dev` 与 `st_ino`，不仅捕获 fd 1，还成功捕获了指向同一 host 终端/管道的 fd 10。
   - 扫描窗口限制为单线程最多 64 KiB，全局原子发射一次标记，开销极小且杜绝了日志泛滥。
2. **`sources/elfuse-transaction-derived` 与 `syscall-tail-derived`**:
   - 在 `syscall.c` 的 common dispatch 入口和 `fast_done` 出口放置配对时间戳戳记，覆盖了大部分 fast/slow 路径，事务配对准确率在 R30 达到 100%（95/95），在 R31 达到 855/856（唯独末端未返回）。
3. **`sources/elfuse-futex-args-derived`**:
   - 在 `nr == SYS_futex` 分支补足了 `x0..x5` 的寄存器捕获，并通过 `guest_read_small` 读取了 uaddr 处的 uint32 snapshot word。
   - **设计合规性**：未修改任何 futex 等待/唤醒语义，未修改返回值，未侵入式修改寄存器，属于纯观测性衍生。

---

## 四、 纯轻量测试验证 (Pure Lightweight Tests)

审查员在隔离环境中直接执行了构建产物中的宿主纯测试：
- **测试程序**：`/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-futex-args-derived/build/test-preempt-lifecycle-host`
- **测试结果**：
  ```text
  test-preempt-lifecycle-host: testing REAL production proc_preempt functions
    [TEST 1] real production proc_preempt_init and proc_preempt_stop...
    [TEST 2] real production stop idempotency...
    [TEST 3] 5 real production init-stop cycles...
    [TEST 4] signal delivery to real preemption thread then stop...
    [TEST 5] fork child state reset with real pthread_atfork...
    [TEST 6] guest_teardown_failed flag and recovery...
    ALL REAL PRODUCTION PREEMPT LIFECYCLE CHECKS PASSED
  ```
- **耗时**：< 0.1s，退出码 0。证明衍生源码中的真实核心调度与抢占生命周期未受破坏。

---

## 五、 可支持结论 (Supported Findings)

1. **进程与线程归属铁证成立**：
   - Step 3 触发时，hostPID 34442（后续轮次分别为 42288, 45108, 52883, 55012）均为执行 Wine `vk_enum_arm64.exe` 的唯一目标容器进程，ppid 均为其 wrapper 进程，gtid 均为 1。
   - 证明阻塞确实发生在此特定主探针线程，排除了多进程错位或僵尸进程干扰。
2. **I/O 阻塞假说被明确推翻**：
   - R30 的 95 次 selected transactions 全部正常返回，且 read64 多次成功读取数据（例如来自 wineserver 通信通道的数据）；R31 尾部在进入 futex 之前，read63 同样返回了 64 字节。因此，阻塞点并非卡死在某次管道 read/write。
3. **最终挂起边界收敛于 `SYS_futex`**：
   - R31 和 R33 的尾部第 855 号系统调用一致指向 `SYS_futex`（uaddr `0x20102d440`, op `0x80 = FUTEX_WAIT_PRIVATE`, val `1`）。该调用进入后直至 55 秒超时均未产生返回。
   - 参数核验显示 `word == 1` 且 `val == 1`，根据 Linux futex 语义，当前线程进入休眠等待属于正常行为；其未能被唤醒是因缺少后续 WAKE 信号。

---

## 六、 剩余未知与后续建议 (Remaining Unknowns & Recommendations)

1. **uaddr `0x20102d440` 的对象归属未知**：
   - 该地址是 Wine 内置的 `pthread_once_t`、critical section 还是特定驱动加载锁？需结合进程 maps 或 ELF 符号表定位。
2. **Waker 行为完全未知（关键盲区导致）**：
   - 到底是持有该锁的另一线程因死锁未发 WAKE？还是发了 WAKE 但因 elfuse futex 的 hash/bucket 机制丢失（lost-wake）？还是对端线程早先发生了异常崩溃？
   - **建议**：下一步应解除针对单一线程的 `io_fixture_identity_active` 限制，专门对 `uaddr == 0x20102d440` 开启跨线程的全进程 Futex 观测（包括针对该地址的所有 `FUTEX_WAKE` 与 `FUTEX_WAIT`），并记录执行线程的 tid。
3. **环境硬化状态**：
   - 当前所有衍生构建均继承了 PRIVATE→SHARED 的诊断性干预，并非生产级 COW 实现；生产后端与全局 Proton 依然保持未修改。
