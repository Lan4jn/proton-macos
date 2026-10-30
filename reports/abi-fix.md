# elfuse 跨进程同步语义修复报告 (task-13 第 3 轮完结版)

## 1. 任务背景与目标

针对 `fixtures/abi/futex.c` 暴露的跨进程 futex WAIT/WAKE 挂起超时缺项，在派生仓库 `sources/elfuse-derived` 中进行根因调查、最小实现修复与严格回归验证。
原始 `sources/elfuse` 仓库保持 HEAD `8612033dab8dc60728f604a4ea0441895fc16d39` 纯净零改动。

---

## 2. 根因调查与架构缺陷分析

### 2.1 缺陷现象（TDD 红灯阶段）
在原始 `sources/elfuse/build/elfuse` 下执行 `fixtures/abi/bin/futex`：
```text
FUTEX_TIMEOUT_DESPITE_SHARED_WRITE
Exit Code: 5
```
子进程写入共享页（`*p = 1`）并执行 `futex(p, FUTEX_WAKE, 1)` 后，父进程在 1 秒超时内始终未收到唤醒信号，最终以 `ETIMEDOUT` 失败退出。

### 2.2 根本原因定位（双重断裂）
1. **EL1 Shim 层静默吞没 (`src/core/shim.S:1054`)**:
   - EL1 汇编拦截例程 `futex_wake_shape` 直接读取 `shim_globals->futex_waiters[bucket]`。
   - 若当前 vCPU 所在的 guest 实例本地记录的等待者计数为 0，shim 汇编直接执行 `mov x0, #0` 并 `b svc_restore_eret` 返回 EL0，**根本不向 host 发送 HVC 陷入**。子进程调用 `FUTEX_WAKE` 时被自身 shim 拦截吞没，宿主 `sys_futex` 从未被触发。
2. **宿主层进程隔离 (`src/runtime/futex.c`)**:
   - `elfuse` 的 futex 原实现基于宿主进程内部的 `static futex_bucket_t buckets[1024]` 数组与 `pthread_cond_t` 条件变量。
   - 当 guest 调用 `clone(SIGCHLD)` 时，`elfuse` 通过 `posix_spawn` 启动了一个独立的 macOS 宿主进程。
   - 子进程在自身的进程私有空 bucket 中唤醒，找不到任何 waiter；父进程在其自身进程的栈上 `pthread_cond_t` 上睡眠直至超时。即使底层匿名物理页通过 `mmap_fork_prepare_anon_shared` 共享，进程级条件变量完全无法跨进程通信。

---

## 3. 修复方案设计、边界与零架构硬编码保证

本修复完全基于 macOS 27 SDK 低级同步原语 `<os/os_sync_wait_on_address.h>`，遵循严格的条件边界，不破坏原有进程内并发性能与稳定性。

### 3.1 零 Hint 保证与 Darwin 原语底层机制（消除地址捆绑）
在初次尝试中曾测试过固定 host VA hint，经系统化实验验证：
- **Darwin `os_sync_*_SHARED` 机制**: Darwin 内核的 `ulock` 在处理 `OS_SYNC_WAIT_ON_ADDRESS_SHARED` 时，由内核通过虚拟地址反查底层 Mach VM Object / 物理共享页进行全局等待队列匹配。
- **无 Hint 对照实测**: 完全移除 `src/core/guest.c` 中的任何硬编码 hint（保持原始 `mmap(NULL, ...)`），`fixtures/abi/bin/futex` 与全部 16 项综合测试依然 100% 稳定通过。
- **结论**: `src/core/guest.c` 保持 **0 改动**，完全由 Darwin 内核自动处理虚拟地址与底层物理页映射，零架构硬编码绑定。

### 3.2 核心实现边界
1. **FUTEX_PRIVATE_FLAG 绝对优先**:
   - 提取标志位：`bool is_private = (op & FUTEX_PRIVATE_FLAG) != 0;`
   - 查询内存属性：`const guest_region_t *r = guest_region_find(g, uaddr);`
   - 跨进程判定公式：`bool is_cross_process = (!is_private && r != NULL && r->shared);`
   - **非共享场景零影响**: 任何显式携带 `FUTEX_PRIVATE_FLAG` 的调用，或发生在私有堆/栈（`!r->shared`）上的 futex 调用，100% 走原有高效进程内 `pthread_condvar` 队列。
2. **EL1 Shim 拦截放行 (`core/shim.S`)**:
   - 在 `futex_wait_fast` 入口增加对 `FUTEX_PRIVATE_FLAG` (0x80) 的判定：
     ```asm
     ldr w14, [sp, #8]
     tst w14, #0x80
     b.eq futex_shape_bail
     ```
   - 凡是跨进程共享 futex，必须安全陷入宿主，交由 Darwin 内核处理。
3. **安全内存读取与严格错误映射 (`futex_wait_shared`)**:
   - **内存安全**: 复用 `futex_word_load`，受 `HOST_SIGBUS_GUARD` 保护，遇到未映射或缺页安全返回 `-LINUX_EFAULT` (-14)。
   - **精准错误映射**:
     - `os_sync_wait_on_address_with_timeout` 返回 `>= 0`: 成功唤醒，返回 0（注：Darwin 返回剩余等待者计数，必须判断 `>= 0` 而非 `== 0`）。
     - `errno == ETIMEDOUT`: 到达总截止时间时返回 `-LINUX_ETIMEDOUT` (-110)。
     - `errno == EINTR`: 返回 `-LINUX_EINTR` (-4)。
     - 其余非期望错误通过 `linux_errno()` 严格转换并返回负错误码，严禁将未识别 errno 当作 0 伪成功。
4. **精准唤醒计数与错误透传 (`futex_wake_shared`)**:
   - `val == 0` 时直接返回 0，不触发系统调用。
   - `val > 0` 时，使用 `os_sync_wake_by_address_any(..., OS_SYNC_WAKE_BY_ADDRESS_SHARED)` 逐个唤醒，当返回 0 时递增计数；若返回 `-1` 且 `errno == ENOENT`（无剩余等待者）时正常终止循环并返回真实唤醒人数；遇任何非 ENOENT 错误（如 EINVAL/EFAULT）一律通过 `linux_errno()` 返回真实负错误码。
5. **sys_futex_waitv 共享映射 Guard**:
   - 在 `sys_futex_waitv` 遍历入参校验时加入 Guard：若任一等待元素指向 `MAP_SHARED` 内存且未置 `FUTEX2_PRIVATE`，直接返回 `-LINUX_ENOSYS` (-38)，防止进入私有 bucket 导致错误睡眠；保留私有内存上的 `waitv` 功能。
6. **线程退出与子 TID 清理支持 (`futex_wake_one`)**:
   - 将 `futex_wake_one` 由直接调用 `futex_wake` 改为转发至 `sys_futex(g, uaddr, FUTEX_WAKE, 1, 0, 0, FUTEX_BITSET_MATCH_ANY)`，保证在共享内存上的 `clear_child_tid` 亦能唤醒跨进程等待者。

---

## 4. 实测验证与证据汇总

### 4.1 TDD 红绿对比
- **修复前（原 binary）**: `fixtures/abi/bin/futex` -> `FUTEX_TIMEOUT_DESPITE_SHARED_WRITE` (RC=5)
- **修复后（派生 binary）**: `fixtures/abi/bin/futex` -> `FUTEX_OK` (RC=0)

### 4.2 综合 Futex ABI 测试套件（`test_futex_abi_suite`，覆盖全部审阅意见）
源码路径：`sources/elfuse-derived/tests/test_futex_abi_suite.c`
包含针对复审要求的 16 项严格断言：
```text
--- FUTEX ABI TEST SUITE ---
PASS: Case 1 (zero wake -> 0)
PASS: Case 2 (wake 0 waiters -> 0)
PASS: Case 3 (mismatch -> -EAGAIN)
PASS: Case 4 (timeout -> -ETIMEDOUT)
PASS: Case 5 (cross-process fork wait+wake)
PASS: Case 6a (wake 1 wakes exactly 1, leaves 1 blocked)
PASS: Case 6b (wake second waiter -> 1, both reaped)
PASS: Case 7a (FUTEX_WAKE_PRIVATE returns 0, child still blocked)
PASS: Case 7b (shared FUTEX_WAKE wakes child, reaped 77)
PASS: Case 8a (misaligned wait -> -EINVAL)
PASS: Case 8b (zero bitset -> -EINVAL)
PASS: Case 8c (partial bitset on shared -> -ENOSYS)
PASS: Case 8d (unmapped wait -> -EFAULT)
PASS: Case 8e (misaligned wake -> -EINVAL)
PASS: Case 8f (wake 0 waiters on unmapped addr -> 0)
PASS: Case 9 (shared waitv -> -ENOSYS)
PASS: Case 10 (private waitv supported, mismatch -> -EAGAIN)
ALL FUTEX ABI SUITE TESTS PASSED!
Exit Code: 0
```
- **Case 6 真实等待者离开检测**: 2 个 child 同时阻塞，parent 调 `wake 1`，通过 `wait4(WNOHANG)` 实测确证刚好仅 1 个 child 退出，另 1 个 child 仍被阻塞；随后第 2 次 `wake 1` 成功唤醒第 2 个 child，全部正常回收。
- **Case 7 真实 PRIVATE 隔离证明**: child 在共享内存上调用 `FUTEX_WAIT`，parent 调 `FUTEX_WAKE_PRIVATE`，实测返回 0 且 child 保持阻塞；随后 parent 调共享 `FUTEX_WAKE`，child 成功苏醒并退出状态 77。
- **Case 9 & 10 waitv 边界**: 实测共享 `waitv` 返回 `-ENOSYS`，私有 `waitv` 保留原有能力（不匹配时正常返回 `-EAGAIN`）。
- **稳定性**: 连续 10 次运行 100% 绿灯。

### 4.3 基础 ABI 与历史基线回归验证
- `fixtures/abi/bin/shared`: `SHARED_OK` (RC=0)
- `fixtures/abi/bin/signal`: `SIGNAL_OK` (RC=0)
- `fixtures/abi/bin/dynamic_hello`: `DYNAMIC_GLIBC_OK` (RC=0)
- `scripts/elfuse/run_all_baseline.sh`（历史基线 7 项）: 7 executed, 7 passed, 0 failed (RC=0)

---

## 5. 次优项诊断与未支持语义边界声明

### 5.1 次优项：`posix_spawn` ENOENT 传播
- **实测表现**: `fixtures/abi/bin/spawn_missing` -> `SPAWN_RETURN=0 CHILD_EXIT=127` (RC=9)。
- **架构根因**: glibc 的 `posix_spawn` 依赖 `CLONE_VM | CLONE_VFORK`。在真正的 Linux 内核中，子进程与父进程共享内存栈空间，子进程 `execve` 失败时直接将错误码写回父进程栈上的 `args->err`。而在 elfuse 中，为防止子进程 exec 污染父进程的 `guest_t`，`CLONE_VFORK` 使用了独立的 `posix_spawn` 辅助宿主进程，拥有独立的内存快照，导致子进程的错误写回无法直达父进程栈。父进程误判 spawn 成功，随后才在 `waitpid` 中收到子进程的 127 退出码。
- **边界声明**: 此项保留真实失败，不作静默掩盖。

### 5.2 未支持跨进程操作声明
1. **FUTEX_BITSET 掩码过滤**: 非 `FUTEX_BITSET_MATCH_ANY` 的跨进程 bitset 操作显式返回 `-LINUX_ENOSYS`。
2. **FUTEX_REQUEUE / FUTEX_CMP_REQUEUE**: 跨进程重排队列显式返回 `-LINUX_ENOSYS`。
3. **FUTEX_LOCK_PI / FUTEX_UNLOCK_PI / FUTEX_TRYLOCK_PI**: 跨进程优先级继承互斥锁显式返回 `-LINUX_ENOSYS`。
4. **FUTEX_WAITV**: 多 futex 等待在共享映射上显式返回 `-LINUX_ENOSYS`。
5. **异步信号抢占中断**: 分片循环中包含 `signal_claim_interruption()` 轮询，但深水区无切片时的即时打断未作全量并发压力验证，特此声明边界。

---

## 6. 补丁与产物交付

- **派生构建路径**: `/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-derived/build/elfuse`
- **签名 Entitlements**: `com.apple.security.hypervisor`（`codesign -v` 验证有效）
- **补丁文件**: `/Users/mewcapoo/Projects/proton-macos-lab/patches/elfuse/futex-cross-process.patch`（仅改动 `src/core/shim.S` 与 `src/runtime/futex.c`）
- **复验套件脚本**: `/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-derived/tests/run_verification.sh`
- **验证日志**:
  - 第 1 轮初验日志：`/Users/mewcapoo/Projects/proton-macos-lab/logs/abi-fix/verification_all.log`
  - 第 2 轮加固日志：`/Users/mewcapoo/Projects/proton-macos-lab/logs/abi-fix/verification_round2.log`
  - 第 3 轮完结日志：`/Users/mewcapoo/Projects/proton-macos-lab/logs/abi-fix/verification_round3.log`
- **一键复现命令**:
  ```bash
  cd /Users/mewcapoo/Projects/proton-macos-lab
  ./sources/elfuse-derived/tests/run_verification.sh
  ```
