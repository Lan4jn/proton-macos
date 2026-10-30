# FEX / elfuse 宿主清理段崩溃保护候选独立审查报告 (task-24 终审收敛版)

**评审角色**: elfuse-baseline-worker  
**工作区根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`  
**评审对象**: task-22 提交的 `sources/elfuse-crash-derived` 崩溃防护候选补丁及相关 teardown 生命周期实现  
**日期**: 2026-10-16  
**审查核心裁定**:
1. **有限保护有效性确认**: Candidate (`f83455b0...`) 在当前 `hello-x64.exe` 场景下确证能避免 `SIGSEGV -11` 并达成真实 `Exit 0`。
2. **严正声明**: **当前补丁仅为特定时序下的症状级防御，不等于生命周期根竞态得到根治！**
3. **架构隐患未消**: 存在 `munmap` 并发 TOCTOU 竞态、5 处 `cache_base` 遗漏判空、`preempt_thread_main` 后台脱缰存活、全局单例悬垂 UAF 等 4 项实质性结构缺陷。

---

## 一、 双端独立环境实测与全量证据链

本次复核彻底摒弃外部推测，基于本执行员与 Team Lead 双端各自主管进程下的四个独立 owned 运行记录，形成无可置疑的闭环因果证据：

### 1. 红灯现场双端独立复现（Instrumentation-Only 观测版，SHA `f9327955...`）
- **本执行员独立复现 (`logs/fex-teardown-review/run-6l0hzzis`)**:
  - 输出：`X64_FEX_OK`，退出码：`-11 (SIGSEGV)`
  - 宿主异常捕获：`[HOST_CRASH] Phase: BEFORE_GUEST_DESTROY, PC: 0x10223f19c, FAR: 0x000000fcffe00000`
  - 崩溃调用链：`preempt_thread_main + 156 -> drain_external_guest_signal + 332 -> signal_queue + 184 -> shim_globals_raise_attention + 24`
- **Lead 独立实测证据 (`logs/lead-round5/run-k2pfdau5/stderr.log`)**:
  - 输出：`X64_FEX_OK`，退出码：`-11 (SIGSEGV)`
  - 宿主崩溃 FAR：`0x000000fcffe00000`（精确对齐）
  - 崩溃现场与调用栈完全一致（`signal_queue + 184 -> preempt_thread_main + 156`）

### 2. 绿灯候选双端独立复现（Candidate 修复版，SHA `f83455b0...`）
- **本执行员独立复测 (`logs/fex-teardown-review/run-glj60rhe`)**:
  - 标准输出：`X64_FEX_OK`
  - 实测退出：`exit: 0, target_exit: 0, timed_out: false`，耗时 44.2s
  - 宿主状态：`NO HOST CRASH`
- **Lead 独立复测证据 (`logs/lead-round5/run-54af6nhn`)**:
  - 二进制 SHA 校验：`f83455b073611030d388e1f7c4be1dfee26af34106a373b3a6713497790f3e26`
  - 实测退出：`exit: 0, target_exit: 0, timed_out: false`
  - 崩溃完全消除，双端实测一致确认有限场景成功通过。

---

## 二、 已证实事实 vs 候选推测分类

| 序号 | 事实 / 推测项 | 属性 | 依据与证据 |
| :---: | :--- | :---: | :--- |
| **1** | `hello-x64.exe` 在 FEX 翻译下已成功执行并输出 `X64_FEX_OK` | **已证实事实** | 双端共 4 次独立运行 stdout 均完整捕获该字符串 |
| **2** | 目标输出完成并请求退出，host teardown 阶段已观测，崩溃发生于清理段而非 FEX 指令翻译中 | **已证实事实** | 目标输出完成并由 `NtTerminateProcess` 请求退出，崩溃发生于随后的宿主清理阶段 |
| **3** | 崩溃地址 `0xfcffe00000` 是 guest 的 `shim_data` 内存页 | **已证实事实** | 对应 `g->shim_data_base`，在 `guest_destroy()` 中由 `munmap(g->host_base, g->guest_size)` 回收 |
| **4** | 崩溃线程是后台 `preempt_thread_main`，主线程处于 `guest_destroy()` | **已证实事实** | 双端 backtrace 表明主线程正处于 `guest_destroy` 的 `close()` 循环，后台线程在 `sigwait` 唤醒处理中 |
| **5** | `cache_base` 判空即可彻底根治 teardown 多线程生命周期竞态 | **候选推测（不成立）** | 判空仅在特定调度顺序下避免解引用，无法解决并发 unmap 的 TOCTOU 竞态与后台线程残留 |

---

## 三、 Candidate Guard 的实质性架构风险审计清单

经对 `sources/elfuse/src/core/shim-globals.c`、`sources/elfuse/src/core/guest.c`、`sources/elfuse/src/core/launch.c` 及 `sources/elfuse/src/syscall/proc.c` 的跨模块静态审查，确认存在以下 4 项实质性风险：

### 风险 1: TOCTOU 竞态导致防御穿透（时序致命伤）
- **涉及代码**: `src/core/guest.c:862-866` 与 `src/core/shim-globals.c:112`
  ```c
  // guest_destroy()
  if (g->host_base) {
      munmap(g->host_base, g->guest_size);  // [T1] 物理映射与页表已解除！
      // ======= 漏洞窗口：此时 g->host_base 仍是非空的原始指针！ =======
      g->host_base = NULL;                  // [T3] 指针才被置空
  }
  ```
- **分析**: `munmap` 是耗时的系统调用。如果 `preempt_thread_main` 在 `[T1]` 与 `[T3]` 之间的窗口被调度，执行 `cache_base(g)`：
  ```c
  if (!g || !g->host_base) return NULL; // [T2] 检查通过！g->host_base 依然非空
  return (uint8_t *) g->host_base + g->shim_data_base; // 返回已解映射的非法地址
  ```
  随后的原子写入依然会触发硬件页异常 `EXC_BAD_ACCESS`。**仅靠读后判空无法防护并发 unmap。**

### 风险 2: `cache_base` 的其余 Caller 存在严重漏判（隐性崩溃源）
在 `shim-globals.c` 中，`cache_base` 共有 11 处调用点，Candidate 补丁仅在其中 4 处加了判空，以下 5 处直接使用 `cache_base` 返回值且未做判空：
1. **`shim_globals_rescan_urandom_fds` (`src/core/shim-globals.c:280`)**:
   ```c
   memset(cache_base(singleton_g) + SHIM_URANDOM_OFF_BITMAP, 0, SHIM_URANDOM_BITMAP_BYTES);
   ```
   若 `cache_base` 返回 NULL，此处执行 `memset(0x38, ...)` 直接引发空指针写入崩溃。
2. **`shim_globals_refill_urandom_ring` (`src/core/shim-globals.c:303`)**:
   ```c
   uint8_t *base = cache_base(g);
   _Atomic uint32_t *head_p = (_Atomic uint32_t *) (base + SHIM_URANDOM_OFF_RING_HEAD);
   ```
   未对 `base` 判空，后续指针解引用崩溃。
3. **`shim_globals_futex_waiters_get` (`src/core/shim-globals.c:539`)**:
   未判空，直接在 `cache_base(g) + 0x1168` 上原子读取。
4. **`shim_globals_futex_waiters_add` (`src/core/shim-globals.c:550`)**:
   未判空，直接在 `cache_base(g) + 0x1168` 上原子加减。
5. **`shim_globals_publish_stats_enabled` (`src/core/shim-globals.c:572`)**:
   未判空，直接在 `cache_base(g) + 0x10` 上写入。

### 风险 3: `preempt_thread_main` 线程完全未管理，脱缰存活
- **涉及代码**: `src/syscall/proc.c:3096-3160` 及 `src/core/launch.c:220-255`
- **缺陷分析**:
  - `preempt_thread_main` 是在启动期由 `pthread_create` 创建的宿主线程，其内部为一个死循环 `for (;;) { sigwait(...); }`。
  - 在 `elfuse_launch` 清理流程中，调用了 `thread_join_workers()`，但该函数**仅回收 guest vCPU worker 线程，从未回收宿主内部的 `preempt_thread`**！
  - 整个代码库中**没有任何停止、取消或 join `g_preempt_thread` 的机制**。
  - 当 `guest_destroy()` 释放所有 VM、内存、IPC 管道后，该后台线程依然驻留。任何后续信号都会唤醒它执行 `drain_external_guest_signal()`，访问全局已被部分释放的宿主进程状态，与系统的 `atexit()` 进程退出发生不可控的并发竞争。

### 风险 4: 全局单例 `singleton_g` 与 `attention_guest` 悬垂 UAF
- **涉及代码**:
  - `src/core/shim-globals.c:230`: `static guest_t *singleton_g;`
  - `src/syscall/signal.c:495`: `static guest_t *_Atomic attention_guest;`
- **缺陷分析**:
  - 这两个全局指针分别在启动时记录了当前的 `guest_t *g` 指针。
  - 在 `elfuse_launch()` 中，`guest_t g;` 往往是栈上局部变量；即使在堆上，调用 `guest_destroy(&g)` 后该实例也已失效。
  - 检索全工程发现：**`guest_destroy` 期间从未调用 `shim_globals_reset_singleton()` 或将 `attention_guest` 置空！**
  - 这导致全局变量成为指向已销毁对象的悬垂指针，为后台线程或其他清理回调留下了严重的 Use-After-Free 隐患。

---

## 四、 彻底根治建议方案（最小下一步）

为从根本上杜绝该时序竞争，推荐在后续正式补丁中采取“**先停线程，再清指针，最后解映射**”的标准顺序：

1. **引入 Preempt 线程受控退出机制 (`src/syscall/proc.c`)**:
   - 增加原子退出标志：`static _Atomic bool g_preempt_stop = false;`
   - 提供外部调用函数 `proc_preempt_teardown(void)`：
     ```c
     void proc_preempt_teardown(void) {
         if (!g_preempt_started) return;
         g_preempt_stop = true;
         pthread_kill(g_preempt_thread, SIGUSR2); // 打断 sigwait
         pthread_join(g_preempt_thread, NULL);   // 确保后台线程完全退出
         g_preempt_started = false;
     }
     ```
   - 在 `preempt_thread_main` 循环中增加检查：
     ```c
     if (sigwait(&wait_set, &sig) != 0 || g_preempt_stop)
         break;
     ```
2. **在 `elfuse_launch` 中提前执行 Preempt 停机 (`src/core/launch.c:230`)**:
   - 在 `thread_join_workers()` 之后、`guest_destroy(&g)` 之前，显式调用 `proc_preempt_teardown()`。
   - 确保在主线程执行 `munmap(g->host_base)` 之前，任何能够触发 `attention_raise` 的异步后台线程均已终止。
3. **在 `guest_destroy` 开头清理全局单例 (`src/core/guest.c:785`)**:
   - 在销毁前显式断开全局引用：
     ```c
     atomic_store_explicit(&attention_guest, NULL, memory_order_release);
     shim_globals_reset_singleton();
     ```
4. **底层防御性补丁完善**:
   - 将 `shim-globals.c` 中遗漏的 5 处 Caller 补齐判空检查，作为兜底防线。

---

## 五、 交付物清单与归档

- **独立审查报告**: `/Users/mewcapoo/Projects/proton-macos-lab/reports/fex-teardown-review.md`
- **独立复现日志目录**: `/Users/mewcapoo/Projects/proton-macos-lab/logs/fex-teardown-review/`
  - `run-6l0hzzis/stderr.log`: 本执行员独立捕获的 HOST_CRASH 原始堆栈日志（Exit -11，FAR `0xfcffe00000`）
  - `run-glj60rhe/stdout.log`: 本执行员独立验证 Candidate 成功 Exit 0 日志（`X64_FEX_OK`）
- **Lead 独立实测证据关联**:
  - `logs/lead-round5/run-k2pfdau5/stderr.log`: Lead 独立红灯捕获现场
  - `logs/lead-round5/run-54af6nhn`: Lead 独立绿灯验证现场
- **独立复现测试前缀**: `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/teardown-review/pfx/`

本任务已按规范完成只读审查，未修改任何生产代码与二进制，结论已向 Team Lead 汇报。
