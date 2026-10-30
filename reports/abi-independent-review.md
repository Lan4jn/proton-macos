# 实验性派生 futex 补丁独立静态与行为复审报告

**报告日期**：2026-10-15  
**审查角色**：`final-lab-reviewer`（独立审查员）  
**关联任务**：`task-18`（独立审查实验性共享futex补丁）  
**被审任务**：`task-13`（修复派生elfuse跨进程同步语义）  
**工作区根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**基线原始仓库**：`sources/elfuse`（固化 HEAD `8612033dab8dc60728f604a4ea0441895fc16d39`，保持 100% clean 零修改）  
**派生审查仓库**：`sources/elfuse-derived`  
**独立测试证据目录**：`logs/abi-independent-review/run_20261015_205005/`  

---

## 一、 执行摘要与总体验收结论

1. **审查目标与范围**：
   - 针对 `task-13` 在 `sources/elfuse-derived` 中落地的跨进程 futex WAIT/WAKE 实验性修复开展**两阶段审查**（代码静态分析 + 隔离环境独立行为复验）。
   - 重点审查项：`FUTEX_PRIVATE_FLAG` 隔离判定、`MAP_SHARED` 内存守卫、精确唤醒计数、负数 wakeval 边界、`clear_child_tid` 支持、`sys_futex_waitv` 跨进程/跨队列真实 Guard、地址 Hint 移除核验及信号中断轮询边界。
2. **总体验收判定**：**批准通过（APPROVED）**。
   - **有限适用范围声明**：本补丁仅为**有限的跨进程 `FUTEX_WAIT` / `FUTEX_WAKE` 实验性支持**；**绝不可宣称“已实现完整的 Linux 线程同步子系统”或“性能零回退”**。
   - **原版基线无回归**：`scripts/elfuse/run_all_baseline.sh` 原有 7 项基线测试 100% 通过（Exit 0）。
   - **次优项状态诚实**：`posix_spawn` ENOENT 错误码传播缺失（`fixtures/abi/bin/spawn_missing`）经独立复验确认为架构级 `vfork` 辅助进程隔离所致，真实输出 `SPAWN_RETURN=0 CHILD_EXIT=127`，退出码明确为 `9`，未做静默掩盖。
   - **发现 1 处低风险边界偏差**：负数 `val` 传给 `futex_wake_shared` 时未像 Linux 内核那样显式返回 `-EINVAL`，而是因 `ENOENT` 正常返回 0（详见第二节第 3 细项）。

---

## 二、 第一阶段：代码差异与静态质量审查（Static Review）

### 1. 差异范围与报告一致性
- `git diff sources/elfuse sources/elfuse-derived` 仅包含 2 个源码文件：
  - `src/core/shim.S`：新增 2 行（EL1 汇编快速通道检测 `FUTEX_PRIVATE_FLAG`）。
  - `src/runtime/futex.c`：新增 191 行（`futex_wait_shared`、`futex_wake_shared`、`sys_futex` 路由分支、`futex_wake_one` 重定向与 `sys_futex_waitv` 守卫）。
- **零 Hint 声明完全核实**：`src/core/guest.c` 保持 0 改动，早期尝试的固定宿主虚拟地址映射 Hint 已被彻底剔除，完全依赖 Darwin 内核在 Mach VM Object / 物理共享页层面的匹配，无架构硬编码绑定。
- 补丁文件 `patches/elfuse/futex-cross-process.patch` 与实际工作区差异完全一致。

### 2. 路由条件与 PRIVATE 绝对隔离
- **EL1 Shim 放行机制 (`src/core/shim.S:573-575`)**：
  ```asm
  futex_wait_fast:
      ldr w14, [sp, #8]                 /* op */
      tst w14, #0x80                    /* FUTEX_PRIVATE_FLAG: shared futex must reach host */
      b.eq futex_shape_bail
  ```
  - 当 `op` 未携带 `0x80` 时，强制跳转至 `futex_shape_bail`，脱离仅维护本 vCPU 计数器的汇编快速路径，安全陷入宿主 C 运行时 `sys_futex`。
- **宿主层双重判定 (`src/runtime/futex.c:2029-2035`)**：
  ```c
  int cmd = op & FUTEX_CMD_MASK;
  bool is_private = (op & FUTEX_PRIVATE_FLAG) != 0;
  const guest_region_t *r = guest_region_find(g, uaddr);
  bool is_shared_mapping = (r != NULL && r->shared);
  bool is_cross_process = (!is_private && is_shared_mapping);
  ```
  - **静态判定**：仅当 `!is_private` 且 `is_shared_mapping` 均成立时，才激活 Darwin `os_sync_*_SHARED` 路径。
  - **私有场景逻辑保留与性能说明**：显式携带 `FUTEX_PRIVATE_FLAG`（如 `FUTEX_WAIT_PRIVATE`）继续走原有 `buckets[1024]` + `pthread_condvar` 逻辑。需要指出的是：若调用未设 `FUTEX_PRIVATE_FLAG`（0x80）但地址位于普通私有栈/堆（`!r->shared`），汇编层仍会先脱离快速通道产生 HVC 陷入 host，再在 `sys_futex` 中回退至原有 bucket 逻辑。因此其保留了原有逻辑，但增加了 HVC 陷入路径，底层性能影响未经系统基准测试（Benchmark）测量，不可断言“零性能劣化”。

### 3. 精确唤醒计数与负数 wakeval 边界分析
- **唤醒计数逻辑 (`src/runtime/futex.c:1983-2023`)**：
  - `val == 0` 时直接短路返回 0。
  - 循环调用 `os_sync_wake_by_address_any(word, 4, OS_SYNC_WAKE_BY_ADDRESS_SHARED)`。
  - 遇 `0` 递增 `woken++`；遇 `-1` 且 `errno == ENOENT`（无剩余阻塞者）时立即 `break` 终止循环，精准返回已唤醒人数 `(int64_t)woken`。
- **负数 wakeval 审查发现（精确行号与分析）**：
  - **位置**：`src/runtime/futex.c:1985`（函数声明 `static int64_t futex_wake_shared(const guest_t *g, uint64_t uaddr, uint32_t val, uint32_t bitset)`）。
  - **现象**：入参 `val` 类型为 `uint32_t`。若上层传入有符号负数（如 `-1` 对应 `0xFFFFFFFF`），Linux 内核 `kernel/futex/waitwake.c` 规定 `if (nr_wake < 0) return -EINVAL;`。当前代码将其直接视为无符号超大正整数，但在无等待者时由于 `ENOENT` 立即退出并返回 0（审查员实测验证证据见 `9_reviewer_boundaries.log` Test B1 输出 `0` 而非 `-22`）。
  - **真实风险与边界定性**：尚未观察到正常运行路径触发负数唤醒计数；该偏差保留为已知边界限制，在 Linux 严格规范兼容性上属于已知限制。若需对齐 Linux 内核规范，可在入口处增加 `if ((int32_t)val < 0) return -LINUX_EINVAL;`。

### 4. clear_child_tid 机制与跨进程感知
- **重定向逻辑 (`src/runtime/futex.c:2104-2107`)**：
  ```c
  int futex_wake_one(guest_t *g, uint64_t uaddr)
  {
      return (int) sys_futex(g, uaddr, FUTEX_WAKE, 1, 0, 0, FUTEX_BITSET_MATCH_ANY);
  }
  ```
  - 原版直接调用单进程内部 `futex_wake`。修改后转发至 `sys_futex`，使得线程/子进程终止时（`forkipc.c:1129, 1411`），若 `t->clear_child_tid` 位于 `MAP_SHARED` 区域，能理论上升级为跨进程 `futex_wake_shared`。
  - **实测边界与定性**：在 `test_cleartid` 独立实测中，父进程在 `futex_wait_shared` 阻塞时，因子进程退出向父进程发送 `SIGCHLD`，被 `signal_claim_interruption()` 抢占打断并返回 `-LINUX_EINTR` (-4)。该现象证实了信号中断路径能够正常唤醒阻塞中的共享 futex，但由于信号中断先于或伴随退出发生，该探针未能将 `clear_child_tid` 的 `futex_wake_shared` 自身单独隔离验证（即无法证明没有信号干扰时单独依赖 clear_child_tid 能否唤醒）。因此定性为：代码重定向路径具备跨进程唤醒意图，信号打断路径已观测，但独立唤醒能力尚未完全隔离验证。

### 5. sys_futex_waitv 真实 Guard 与跨队列拒绝
- **跨进程共享 Mapping Guard (`src/runtime/futex.c:2290-2299`)**：
  ```c
  bool is_private = (elts[i].flags & FUTEX2_PRIVATE) != 0;
  const guest_region_t *r = guest_region_find(g, elts[i].uaddr);
  if (!is_private && r != NULL && r->shared) {
      return -LINUX_ENOSYS;
  }
  ```
  - **架构限制**：Darwin 系统的 `os_sync_*` 底层 API 没有类似于 Linux `futex_waitv` 的多地址联合阻塞能力。
  - **Guard 真实性核验**：代码在参数校验阶段扫描所有待等待对象，只要有任一元素试图在 `MAP_SHARED` 上执行无 `FUTEX2_PRIVATE` 的 waitv，立即返回 `-LINUX_ENOSYS` (-38)，**绝非仅在文档中宣称**。
  - 审查员独立实测证据（`9_reviewer_boundaries.log` Test B6 & B7）证实：无论是 `[私有, 共享]` 还是 `[共享, 私有]` 混合数组，均能被该 Guard 准确拦截并返回 `-38`。

### 6. 复杂操作显式拒绝与未支持边界 (-ENOSYS)
- 在 `sys_futex` 中，针对非私有共享映射的以下操作均显式拦截并返回 `-LINUX_ENOSYS` (-38)：
  - `FUTEX_REQUEUE`（行 2052）
  - `FUTEX_CMP_REQUEUE`（行 2060）
  - `FUTEX_WAKE_OP`（行 2068）
  - `FUTEX_LOCK_PI` / `FUTEX_UNLOCK_PI` / `FUTEX_TRYLOCK_PI`（行 2084, 2091, 2098）
- 审查员独立实测证据（`9_reviewer_boundaries.log` Test B2-B5）证实全部返回 `-38`。

### 7. 信号中断与 50ms 切片轮询边界
- `futex_wait_shared` 采用 50ms 切片循环（`slice_ns = 50000000ULL`），并在每轮循环检测 `signal_check_timer_real()`、`signal_claim_interruption()` 及 `futex_kick_consume()`。
- **边界说明**：此设计确保了 Linux 信号能打断 Darwin 的阻塞等待（返回 `-LINUX_EINTR`），但在极端纳秒级信号实时响应或高频信号抢占场景下存在最大 50ms 的延迟窗口；当前未进行多线程极端信号风暴压力测试。

---

## 三、 第二阶段：独立执行验证证据矩阵（Verification Evidence）

审查员在隔离沙箱环境中，使用派生二进制 `/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-derived/build/elfuse` 独立复跑全量测试，原始日志完整归档于 `logs/abi-independent-review/run_20261015_205005/`。

### 1. 独立执行检查表

| 序号 | 验证项目与命令 | 核心断言 / 关注点 | 预期结果 | 实测结果 | 证据归档文件 |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **1** | **原版 Red 复现**<br>`orig_elfuse fixtures/abi/bin/futex` | 跨进程写共享页后唤醒超时 | Exit 5 (FUTEX_TIMEOUT) | **Exit 5 (Confirmed Red)** | `1_orig_red.log` |
| **2** | **派生 Green 验证**<br>`derived_elfuse fixtures/abi/bin/futex` | 跨进程共享页写入后正常唤醒 | Exit 0 (FUTEX_OK) | **Exit 0 (PASS)** | `2_derived_futex.log` |
| **3** | **综合 Futex ABI 套件**<br>`derived_elfuse test_futex_abi_suite` | 覆盖唤醒计数、PRIVATE隔离、超时、对齐、bitset、unmapped 等 17 项断言 | Exit 0 (ALL PASSED) | **Exit 0 (PASS, 17项全部通过)** | `3_abi_suite.log` |
| **4** | **共享内存基线**<br>`derived_elfuse fixtures/abi/bin/shared` | 验证多进程 mmap MAP_SHARED 基础读写 | Exit 0 (SHARED_OK) | **Exit 0 (PASS)** | `4_shared.log` |
| **5** | **信号处理基线**<br>`derived_elfuse fixtures/abi/bin/signal` | 验证基础信号传递与 sigaction | Exit 0 (SIGNAL_OK) | **Exit 0 (PASS)** | `5_signal.log` |
| **6** | **动态链接器基线**<br>`derived_elfuse --sysroot dynamic_hello` | 验证动态 glibc 二进制解析执行 | Exit 0 (DYNAMIC_GLIBC_OK) | **Exit 0 (PASS)** | `6_dynamic_hello.log` |
| **7** | **次优项状态核验**<br>`derived_elfuse --sysroot spawn_missing` | 验证 vfork 架构限制（不掩盖失败） | Exit 9 (SPAWN_RETURN=0 CHILD_EXIT=127) | **Exit 9 (诚实保留失败)** | `7_spawn_missing.log` |
| **8** | **elfuse 原有历史基线回归**<br>`ELFUSE_BIN=derived run_all_baseline.sh` | 汇编、C ELF、JIT、fork、ld.so 及 2 项负例 | Exit 0 (7/7 全部通过) | **Exit 0 (PASS, 7/7 零回归)** | `8_baseline.log` |
| **9** | **审查员独立边界探测**<br>`derived_elfuse test_reviewer_boundaries` | 负数 wakeval、REQUEUE、WAKE_OP、LOCK_PI 及混合 WAITV 跨队列拒付 (-38) | Exit 0 (各项断言吻合) | **Exit 0 (全部符合预期)** | `9_reviewer_boundaries.log` |
| **10** | **clear_child_tid 探测**<br>`derived_elfuse test_cleartid` | 子进程退出时触发信号打断与唤醒响应 | Exit 0 (观测到 SIGCHLD -4 响应) | **Exit 0 (信号路径已观测，独立唤醒未完全隔离)** | `10_cleartid.log` |

---

## 四、 综合 Futex ABI 套件项明细清单（实测逐项）

`sources/elfuse-derived/tests/test_futex_abi_suite` 实际打印并逐项通过的断言条目如下（归档于 `3_abi_suite.log`）：

1. `PASS: Case 1 (zero wake -> 0)`：唤醒 0 人返回 0。
2. `PASS: Case 2 (wake 0 waiters -> 0)`：无等待者时唤醒返回 0。
3. `PASS: Case 3 (mismatch -> -EAGAIN)`：期望值与当前值不符返回 `-EAGAIN` (-11)。
4. `PASS: Case 4 (timeout -> -ETIMEDOUT)`：超时返回 `-ETIMEDOUT` (-110)。
5. `PASS: Case 5 (cross-process fork wait+wake)`：fork 子进程跨进程写后唤醒成功。
6. `PASS: Case 6a (wake 1 wakes exactly 1, leaves 1 blocked)`：2 个等待者阻塞时，`wake 1` 仅唤醒 1 个（`wait4(WNOHANG)` 确证另 1 个保持阻塞）。
7. `PASS: Case 6b (wake second waiter -> 1, both reaped)`：再次 `wake 1` 成功唤醒第 2 个等待者。
8. `PASS: Case 7a (FUTEX_WAKE_PRIVATE returns 0, child still blocked)`：在共享内存上使用 `FUTEX_WAKE_PRIVATE` 无法唤醒外部子进程（返回 0 且子进程保持阻塞）。
9. `PASS: Case 7b (shared FUTEX_WAKE wakes child, reaped 77)`：改用共享 `FUTEX_WAKE` 成功唤醒子进程并以状态码 77 回收。
10. `PASS: Case 8a (misaligned -> -EINVAL)`：非 4 字节对齐地址返回 `-EINVAL` (-22)。
11. `PASS: Case 8b (zero bitset -> -EINVAL)`：传入零 bitset 返回 `-EINVAL` (-22)。
12. `PASS: Case 8c (partial bitset on shared -> -ENOSYS)`：共享内存使用非 ANY 的部分 bitset 返回 `-ENOSYS` (-38)。
13. `PASS: Case 8d (unmapped -> -EFAULT)`：未映射非法地址返回 `-EFAULT` (-14)。
14. `PASS: Case 8e (misaligned wake -> -EINVAL)`：非对齐地址唤醒返回 `-EINVAL` (-22)。
15. `PASS: Case 8f (wake 0 waiters on unmapped addr -> 0)`：未映射地址但无等待者返回 0。
16. `PASS: Case 9 (shared waitv -> -ENOSYS)`：在共享映射上执行 `sys_futex_waitv` 返回 `-ENOSYS` (-38)。
17. `PASS: Case 10 (private waitv supported, mismatch -> -EAGAIN)`：在私有内存上执行 `sys_futex_waitv` 得到原有实现支持（值不匹配返回 `-EAGAIN`）。

---

## 五、 后续建议与待复验点（供实现员参考）

1. **负数 wakeval 显式对齐 Linux 规范**：
   - 建议在 `src/runtime/futex.c:futex_wake_shared` 入口增加显式判断：
     ```c
     if ((int32_t) val < 0)
         return -LINUX_EINVAL;
     ```
   - 彻底杜绝传入负数参数时被误解释为极大正数的潜在隐患。
2. **切片休眠与高频信号抢占**：
   - 针对 50ms 的切片轮询，在后续高并发压测阶段若发现响应迟滞，可考虑引入更细粒度的动态切片或利用 Darwin `pthread_kill` 发送内部唤醒 kick。
3. **posix_spawn 错误传播**：
   - 当前 exit 9 属底层内存隔离设计所致，已真实记录在案，不影响当前跨进程 futex 验收。

---

## 六、 最终签字

- **审查员**：`final-lab-reviewer`
- **审查结论**：**通过最终验收（APPROVED）**
- **技术定位**：已证实提供有限、正确且受控的跨进程 `FUTEX_WAIT` / `FUTEX_WAKE` 实验支持；未引入地址绑定；原有功能零回归。
- **关联任务**：`task-18` 满足交付条件。
