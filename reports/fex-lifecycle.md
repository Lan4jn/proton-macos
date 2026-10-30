# FEX 宿主后台线程生命周期根治与全量验证报告

**任务编号**: task-26  
**执行角色**: proton-integration-worker  
**工作区根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`  
**完成时间**: 2026-10-16  
**状态**: **已完成宿主后台线程先停机再解映射之生命周期根治；Fail-Closed 错误传播闭环；双端交叉验证通过；hello-x64.exe 实测稳定输出 X64_FEX_OK 且纯净 Exit 0**  

---

## 一、 执行摘要与突破结论

本任务针对 task-22/task-24 审查识别的宿主清理段竞争缺陷（`preempt_thread_main` 在 `guest_destroy` 解映射后仍并发访问已释放内存导致的 host SIGSEGV），在 `sources/elfuse-lifecycle-derived` 中实现了纯净的**线程生命周期停机顺序治理与 Fail-Closed 错误传播闭环**。

### 核心结论与关键指标
1. **生命周期停机 Happens-Before 严格确立与 Fail-Closed 机制**：
   - 治理时序：在 `guest_destroy` 中，首先等待并回收全部工作 vCPU 线程，确认无存活 worker 后，显式执行 `proc_preempt_stop()`；
   - `proc_preempt_stop()` 签名改为 `int proc_preempt_stop(void)`：若发生自 join 或 `pthread_join` 异常，严格返回 `-1`，且由 `guest_destroy` 立即**中断解映射流程 (fail-closed)**，防止在线程存活状态下释放内存；
   - `launch.c` 与 `forkipc.c` (L566) 全面监听清理状态，若 teardown 失败且原本为 exit 0，强制覆盖为非 0 退出码 `125`，彻底杜绝清理失败变“假绿”；
   - 彻底消除了依赖局部 NULL guard 掩盖时序竞态的架构隐患，`src/core/shim-globals.c` 与 `src/syscall/syscall.c` **100% 还原为原始代码，不含任何防御性 NULL guards，不含任何伪造 prctl**。
2. **生产源码级 Host TDD 单元测试通过**：
   - `sources/elfuse-lifecycle-derived/tests/test-preempt-lifecycle-host.c` 直接链接生产 `proc.o` 及全套生产目标对象，直接调用真实的 `proc_preempt_init()` 与 `proc_preempt_stop()` 生产函数；
   - 覆盖单次停机、多次停机幂等性、5 次连续重初始化循环、信号唤醒后停机、真实 `pthread_atfork` 在子进程的状态复位、以及 teardown failure 标志检测，**6 项自动化测试全部通过**（日志落盘于 `logs/fex-lifecycle/host-unit-test-round2.log`，Lead 独立端验证见 `logs/lead-round7/production-lifecycle-test.log`）。
3. **双端交叉验证全绿通过**：
   - **`hello-x64.exe` 双端 100% 达成纯净 Exit 0**：
     * 执行员端 Round 2 (`run-dyoqcrtf`, 37.6s)：`exit: 0, target_exit: 0, stdout: 'X64_FEX_OK'`！
     * 执行员端 Round 1 (`run-az4m5m_s` & `run-9wj8g8dk`)：`exit: 0, target_exit: 0, stdout: 'X64_FEX_OK'`！
     * **Lead 独立端 (`run-iszksvgi`)**：基于 `3ace7bdc...` 独立复验，`exit: 0, target_exit: 0, stdout: 'X64_FEX_OK\n', seconds: 49.0s, cleanup_errors: []`（记录于 `logs/lead-round7/lifecycle-hello.json`）！
   - **`minimal-x64.exe` (`run-yt1pcwrd`)**：精确返回 `exit: 43, target_exit: 43`！
   - **`minimal-arm64.exe` (`run-g1kjvrvd`)**：精确返回 `exit: 37, target_exit: 37`！
   - **底层四大基线保持全通**：静态汇编 hello、动态 glibc `dynamic_hello`、MAP_SHARED `shared`、`wine --version` 全数通过。
4. **测试边界与组合路径审计说明**:
   - **Direct Wine CLI 路径**: 无论直接调 Wine 还是带 LOADDLL 追踪，均已 100% 达成纯净 Exit 0 与 `X64_FEX_OK`；
   - **组合 Launcher 路径未通过**: Lead 新增全套组合执行测试（`elfuse -> Linux Python -> 原版 proton runinprefix hello`，见 `logs/lead-round7/run-rkbehni4`），实测 110s 超时且 stdout 为空；此路径涉及 Proton Python 包装器状态机与前缀兼容，**本轮 Lead 独立测试未通过，已正式移交 task-30 开展独立 prefix old/new 对照审计（proton-package-worker）**；
   - 本报告严格限制结论于 direct Wine 与基础运行环境，避免泛化全路径纯净成功。

---

## 二、 架构根因与生命周期时序机制

### 1. 缺陷时序重现 (历史崩溃机制)
```text
[主线程: guest_destroy]                      [后台线程: preempt_thread_main]
        |                                                 |
  thread_join_workers()                               sigwait(SIGUSR2/SIGALRM)
  (仅等待 vCPU 线程, 忽略了 preempt)                          |
        |                                                 |
  munmap(g->host_base, g->guest_size)                    |
  g->host_base = NULL;                                    |
        |                                            收到子进程退出信号 (SIGUSR2)
        |                                            drain_external_guest_signal()
        |                                            signal_queue()
        |                                            shim_globals_raise_attention()
        |                                            cache_base(g) -> 0 + 0xFCFFE00000
        |                                            ldsetal [0xFCFFE00000] -> SIGSEGV!
```

### 2. 根治方案时序 (Fail-Closed Happens-Before)
```text
[主线程: guest_destroy]                      [后台线程: preempt_thread_main]
        |                                                 |
  thread_wake_all_blocked()                               |
  thread_join_workers()                                   |
  (首先确保全部 vCPU 线程完成退出与信号注销)                     |
        |                                                 |
  proc_preempt_stop() ----------------------------> 设置 g_preempt_stop_requested = true
  (发送 SIGALRM 唤醒 sigwait)                        pthread_kill(SIGALRM)
        |                                                 |
  pthread_join(g_preempt_thread) <----------------- 线程退出 loop 并终止 (return NULL)
  [HAPPENS-BEFORE 屏障达成: 线程物理死亡]                    X (线程已死)
        |
  若 join 失败 -> 记录 g_guest_teardown_failed=true 并 return (中止 munmap)
        |
  signal_set_shim_globals_guest(NULL)
  shim_globals_reset_singleton()
  (单例引用安全解绑)
        |
  hv_vm_destroy()
  munmap(g->host_base, g->guest_size)
  (此时没有任何并发线程存活，绝不可能发生 UAF 访存!)
```

---

## 三、 核心代码修改与真实 Diff (Lifecycle-Derived)

### 1. 二进制 SHA-256 指纹
- **最终交付二进制路径**: `sources/elfuse-lifecycle-derived/build/elfuse`
- **SHA-256**: `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`
- **代码纯洁性验证**:
  * `sources/elfuse-lifecycle-derived/src/core/shim-globals.c` 相对 `sources/elfuse-derived` 为 **0 diff**（无任何 NULL guards）；
  * `sources/elfuse-lifecycle-derived/src/syscall/syscall.c` 相对 `sources/elfuse-derived` 为 **0 diff**（无任何伪造 prctl）。

### 2. 真实源代码 `diff -u` (相对于 `sources/elfuse-derived`)
完整补丁文件位于 `logs/fex-lifecycle/lifecycle-derived-round2.diff`：
```diff
--- sources/elfuse-derived/src/core/guest.c
+++ sources/elfuse-lifecycle-derived/src/core/guest.c
@@ -44,6 +44,7 @@
 #include "proved/align.h"
 #include "proved/gva.h"
 #include "core/startup-trace.h"
+#include "core/shim-globals.h"
 #include "debug/log.h"
 #include "utils.h"
 #include "runtime/futex.h"  /* futex_interrupt_request */
@@ -537,10 +538,14 @@
         if (size > 0 && try_size > size)
             continue;
 
-        /* Re-derive the layout for this slab size. */
+        /* Re-derive the layout for this slab size.
+         * Shift interp_base down by 12 GiB (0x300000000) and mmap_limit by 16 GiB (0x400000000)
+         * so Wine's top-of-memory 4 GiB reservation [0xfeffff0000, 0xffffff0000)
+         * does not collide with the 16 MiB infrastructure reserve or the dynamic linker load base.
+         */
         g->guest_size = try_size;
-        g->interp_base = try_size - 0x100000000ULL;
-        g->mmap_limit = try_size - 0x200000000ULL;
+        g->interp_base = try_size - 0x300000000ULL;
+        g->mmap_limit = try_size - 0x400000000ULL;
         g->overflow_ipa_next = try_size;
         if (!compute_infra_layout(g))
             continue;
@@ -641,9 +646,9 @@
     g->guest_size = size;
     g->ipa_bits = ipa_bits;
 
-    /* Compute layout limits (same formula as guest_init) */
-    g->interp_base = size - 0x100000000ULL;
-    g->mmap_limit = size - 0x200000000ULL;
+    /* Compute layout limits (same formula as guest_init: interp at size-12GiB, mmap_limit at size-16GiB) */
+    g->interp_base = size - 0x300000000ULL;
+    g->mmap_limit = size - 0x400000000ULL;
         g->overflow_ipa_next = size;
         if (!compute_infra_layout(g)) {
             /* Layout computation may reject a malformed header (impossible
@@ -776,8 +781,20 @@
         m->size = 0;
     }
     g->n_mappings = 0;
+}
+
+static bool g_guest_teardown_failed = false;
+
+bool guest_teardown_failed(void)
+{
+    return g_guest_teardown_failed;
 }
 
+void guest_teardown_clear_failure(void)
+{
+    g_guest_teardown_failed = false;
+}
+
 void guest_destroy(guest_t *g)
 {
     /* Quiesce worker vCPUs before unmapping stage-2. thread_destroy_all_vcpus
@@ -826,6 +843,7 @@
          * reclaim them atomically, the one operation that safely stops a
          * foreign vCPU. The leaked fds and heap are reclaimed the same way.
          */
+        g_guest_teardown_failed = true;
         log_warn(
             "guest_destroy: worker vCPU still live past join cap; "
             "deferring HVF teardown to process exit");
@@ -843,6 +861,20 @@
     g->vcpu_valid = false;
     g->vcpu = 0;
 
+    /* Quiesce host preemption thread and join it BEFORE unmapping guest memory!
+     * If preemption thread stop fails, fail closed: defer memory unmap to process exit
+     * to prevent any potential use-after-free, and record failure!
+     */
+    if (proc_preempt_stop() < 0) {
+        g_guest_teardown_failed = true;
+        log_error(
+            "guest_destroy: failed to stop preemption thread; "
+            "deferring memory unmap to process exit to prevent UAF");
+        return;
+    }
+    signal_set_shim_globals_guest(NULL);
+    shim_globals_reset_singleton();
+
     /* Unmap each HVF segment. hv_vm_destroy releases all stage-2 state
      * regardless, but unmapping explicitly keeps invariants clean for
      * downstream tools (Instruments, leak detectors).

--- sources/elfuse-derived/src/core/guest.h
+++ sources/elfuse-lifecycle-derived/src/core/guest.h
@@ -864,6 +864,10 @@
 }
 
 /* API */
+
+/* Teardown failure status queries. */
+bool guest_teardown_failed(void);
+void guest_teardown_clear_failure(void);
 
 /* Allocate guest memory, create VM, map to hypervisor. size: primary buffer

--- sources/elfuse-derived/src/core/launch.c
+++ sources/elfuse-lifecycle-derived/src/core/launch.c
@@ -258,8 +258,13 @@
      */
     proc_pty_release_process_slaves();
 
-    if (guest_initialized)
+    if (guest_initialized) {
         guest_destroy(&g);
+        if (guest_teardown_failed() && exit_code == 0) {
+            log_error("elfuse: guest teardown failed; overriding exit code to 125");
+            exit_code = 125;
+        }
+    }

--- sources/elfuse-derived/src/runtime/forkipc.c
+++ sources/elfuse-lifecycle-derived/src/runtime/forkipc.c
@@ -58,6 +58,7 @@
 #include "hvutil.h"
 #include "utils.h"
 
+#include "core/guest.h"
 #include "core/shim-globals.h"
 
 #include "runtime/forkipc.h"
@@ -562,6 +563,10 @@
     proc_pty_release_process_slaves();
 
     guest_destroy(&g);
+    if (guest_teardown_failed() && exit_code == 0) {
+        log_error("fork-child: guest teardown failed; overriding exit code to 125");
+        exit_code = 125;
+    }
     return exit_code;
 }

--- sources/elfuse-derived/src/syscall/mem.c
+++ sources/elfuse-lifecycle-derived/src/syscall/mem.c
@@ -2993,8 +2993,14 @@
          * runtime fields rather than compile-time low-memory constants.
          */
         uint64_t fix_end = off + length;
-        if (guest_range_hits_infra(g, off, fix_end))
+        if (guest_range_hits_infra(g, off, fix_end)) {
+            uint64_t lo = 0, hi = 0;
+            guest_infra_window(g, &lo, &hi);
+            log_warn("mmap MAP_FIXED rejected by infra reserve: [0x%llx, 0x%llx) overlaps infra [0x%llx, 0x%llx)",
+                     (unsigned long long) off, (unsigned long long) fix_end,
+                     (unsigned long long) lo, (unsigned long long) hi);
             return -LINUX_EINVAL;
+        }
 
         result_off = off;

--- sources/elfuse-derived/src/syscall/proc.c
+++ sources/elfuse-lifecycle-derived/src/syscall/proc.c
@@ -3085,6 +3085,7 @@
 
 static pthread_t g_preempt_thread;
 static bool g_preempt_started;
+static _Atomic bool g_preempt_stop_requested;
 
 static void drain_external_guest_signal(void);
 
@@ -3104,9 +3105,13 @@
     sigaddset(&wait_set, SIGALRM);
 
     for (;;) {
+        if (atomic_load_explicit(&g_preempt_stop_requested, memory_order_acquire))
+            break;
         int sig = 0;
         if (sigwait(&wait_set, &sig) != 0)
             continue;
+        if (atomic_load_explicit(&g_preempt_stop_requested, memory_order_acquire))
+            break;
         if (sig == SIGUSR2) {
             atomic_store_explicit(&g_external_guest_signal, 1,
                                   memory_order_release);
@@ -3215,6 +3220,12 @@
     }
     flock_retry(fd, LOCK_UN);
     close(fd);
+}
+
+static void proc_preempt_atfork_child(void)
+{
+    g_preempt_started = false;
+    atomic_store_explicit(&g_preempt_stop_requested, false, memory_order_relaxed);
 }
 
 /* Call once from the main thread before any vCPU thread is created; the
@@ -3253,6 +3264,16 @@
         return -1;
     }
 
+    static bool atfork_registered = false;
+    if (!atfork_registered) {
+        int aerr = pthread_atfork(NULL, NULL, proc_preempt_atfork_child);
+        if (aerr != 0) {
+            log_error("elfuse: pthread_atfork failed: %s", strerror(aerr));
+            return -1;
+        }
+        atfork_registered = true;
+    }
+
     int err =
         pthread_create(&g_preempt_thread, NULL, preempt_thread_main, NULL);
     if (err != 0) {
@@ -3266,7 +3287,42 @@
         return -1;
     }
     g_preempt_started = true;
-    atexit(unlink_own_transport);
+    static bool atexit_registered = false;
+    if (!atexit_registered) {
+        atexit(unlink_own_transport);
+        atexit_registered = true;
+    }
     return 0;
 }
 
+int proc_preempt_stop(void)
+{
+    if (!g_preempt_started)
+        return 0;
+
+    /* Prevent self-join deadlock */
+    if (pthread_equal(pthread_self(), g_preempt_thread)) {
+        log_error("elfuse: proc_preempt_stop called from preemption thread itself");
+        return -1;
+    }
+
+    atomic_store_explicit(&g_preempt_stop_requested, true, memory_order_release);
+    int kerr = pthread_kill(g_preempt_thread, SIGALRM);
+    if (kerr != 0 && kerr != ESRCH) {
+        log_error("elfuse: pthread_kill preemption thread failed: %s",
+                  strerror(kerr));
+        return -1;
+    }
+
+    int jerr = pthread_join(g_preempt_thread, NULL);
+    if (jerr != 0) {
+        log_error("elfuse: pthread_join preemption thread failed: %s",
+                  strerror(jerr));
+        return -1;
+    }
+
+    g_preempt_started = false;
+    atomic_store_explicit(&g_preempt_stop_requested, false, memory_order_relaxed);
+    return 0;
+}

--- sources/elfuse-derived/src/syscall/proc.h
+++ sources/elfuse-lifecycle-derived/src/syscall/proc.h
@@ -577,6 +577,7 @@
  * this process).
  */
 int proc_preempt_init(void);
+int proc_preempt_stop(void);
 ```

---

## 四、 真实生产代码宿主单元测试 (`test-preempt-lifecycle-host`)

直接链接生产目标文件 `proc.o`、`thread.o` 及全套系统运行框架，实测执行 `sources/elfuse-lifecycle-derived/tests/test-preempt-lifecycle-host.c`（执行员端日志见 `logs/fex-lifecycle/host-unit-test-round2.log`，Lead 独立端验证见 `logs/lead-round7/production-lifecycle-test.log`）：
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

> **故障注入与测试边界诚实说明**:
> - Test 6 验证的是 `guest_teardown_failed` 标志的设置、查询与清零逻辑，以及生产静态代码中增加的中断 `munmap` 与退出码 125 覆盖分支；
> - 实际运行中并未动态注入让 `pthread_kill` 或 `pthread_join` 返回错误的 hook，因此**残余故障注入的动态执行状态标定为 UNKNOWN**，不作已完成完整故障注入测试的过度夸大。

---

## 五、 端到端双端验证全绿矩阵 (严格区分运行时版本)

测试在全新独立隔离前缀 `fixtures/runtime/fex-lifecycle/pfx` 中执行，以下表格按各自实际运行的**具体二进制 SHA-256 哈希值**严格分别标定，绝不混淆版本数据：

| 测试项目 | 运行二进制版本与哈希 | 执行员端实测 | Lead 独立端实测 | 判定 |
| :--- | :--- | :--- | :--- | :--- |
| **`hello-x64.exe` (Round 2)**| `elfuse-lifecycle-derived` (`f2a678dd...` 最终版) | **Exit 0, `X64_FEX_OK`** (`run-dyoqcrtf`, 37.6s) | - | **PASS (Fail-Closed 强化后纯净 Exit 0)** |
| **`hello-x64.exe` (Round 1)**| `elfuse-lifecycle-derived` (`3ace7bdc...` 首版) | **Exit 0, `X64_FEX_OK`** (`run-az4m5m_s`) | **Exit 0, `X64_FEX_OK\n`** (`run-iszksvgi`, 49.0s) | **PASS (双端绿灯交叉印证)** |
| `hello-x64.exe` (复验重跑) | `elfuse-lifecycle-derived` (`3ace7bdc...` 首版) | **Exit 0, `X64_FEX_OK`** (`run-9wj8g8dk`) | - | **PASS (可重复性绿灯)** |
| **`minimal-x64.exe`** | `elfuse-lifecycle-derived` (`3ace7bdc...` 首版) | **Exit 43** (`run-yt1pcwrd`) | - | **PASS (FEX 指令翻译)** |
| `minimal-x64.exe` (对照) | `elfuse-fex-derived` (`0079fc5d...` layout-only) | Exit 43 (`run-5g8b1rkf`) | **Exit 43** (`run-3uc3xfl0`) | **PASS (双端纯布局对照)** |
| **`minimal-arm64.exe`** | `elfuse-lifecycle-derived` (`3ace7bdc...` 首版) | **Exit 37** (`run-g1kjvrvd`) | - | **PASS (Wine 原生基线)** |
| `minimal-arm64.exe` (对照)| `sources/elfuse/build/elfuse` (原始基线版本) | Exit 37 (`run-z5ilwjrt`) | **Exit 37** (`run-tdsalxey`) | **PASS (底层基线对照)** |
| 静态 / 动态 / fork / wine | `elfuse-lifecycle-derived` (`f2a678dd...` 最终版) | 全部 Exit 0 / PASS | - | **PASS (系统回归全绿)** |
| **Proton Launcher 组合执行** | `elfuse-lifecycle-derived` (`f2a678dd...` 最终版) | - | **110s 超时, stdout 空** (`run-rkbehni4`) | **FAIL (本轮未通，移交 task-30 审计)** |

### 双端证据数据对应
- **执行员端 Round 2 结果**: `logs/fex-lifecycle/run-dyoqcrtf` (exit: 0, target_exit: 0, stdout: `'X64_FEX_OK'`)
- **执行员端 Round 1 汇总**: `logs/fex-lifecycle/lifecycle_verification.json`
- **Lead 独立端 Round 1 结果**: `logs/lead-round7/lifecycle-hello.json` (SHA `3ace7bdc...`)
- **Lead 独立端运行目录**: `logs/lead-round7/run-iszksvgi` (exit: 0, target_exit: 0, cleanup_errors: [])

---

## 六、 交付物清单与 Lead 独立复验指引

### 1. 产出物清单（严格在 writeScopes 内部）
- `sources/elfuse-lifecycle-derived/`: 纯净生命周期治理源码（最终 SHA-256 `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`）
- `sources/elfuse-lifecycle-derived/tests/test-preempt-lifecycle-host.c`: 真实生产函数宿主单元测试
- `fixtures/runtime/fex-lifecycle/pfx/`: 独立克隆前缀（保持冻结，供 Lead clone）
- `scripts/runtime/fex_lifecycle/run_lifecycle_verification.py`: 全量验证脚本
- `logs/fex-lifecycle/lifecycle-derived-round2.diff`: 完整真实源码补丁
- `logs/fex-lifecycle/host-unit-test-round2.log`: 生产函数宿主测试日志
- `logs/fex-lifecycle/run-dyoqcrtf/`: Round 2 hello-x64 Exit 0 成功运行记录
- `reports/fex-lifecycle.md`: 本报告

### 2. Lead 独立复验编译与测试命令
```bash
# 1. 编译生产二进制与宿主测试 (编译命令精确归档)
make -C sources/elfuse-lifecycle-derived elfuse

OBJS_NO_MAIN=$(find sources/elfuse-lifecycle-derived/build -name "*.o" ! -name "main.o" ! -name "test-*.o")
clang -I sources/elfuse-lifecycle-derived/src -I sources/elfuse-lifecycle-derived/include \
  sources/elfuse-lifecycle-derived/tests/test-preempt-lifecycle-host.c \
  $OBJS_NO_MAIN \
  -framework Hypervisor -framework CoreFoundation -framework IOKit -lpthread \
  -o sources/elfuse-lifecycle-derived/build/test-preempt-lifecycle-host
codesign -s - --entitlements sources/elfuse-lifecycle-derived/entitlements.plist sources/elfuse-lifecycle-derived/build/test-preempt-lifecycle-host

# 2. 校验交付二进制 SHA-256 指纹
shasum -a 256 sources/elfuse-lifecycle-derived/build/elfuse
# 预期输出: f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a

# 3. 运行生产函数宿主单元测试 (6项全绿)
sources/elfuse-lifecycle-derived/build/test-preempt-lifecycle-host

# 4. 执行 hello-x64.exe 独立复验
python3 -c "
import sys; from pathlib import Path; LAB = Path('/Users/mewcapoo/Projects/proton-macos-lab'); sys.path.insert(0, str(LAB))
from scripts.backend.process import run_isolated
elfuse = LAB / 'sources/elfuse-lifecycle-derived/build/elfuse'
root = LAB / 'fixtures/runtime/arch-case'
bundle = LAB / 'fixtures/runtime/proton-derived'
prefix = LAB / 'fixtures/runtime/fex-lifecycle/pfx'
argv = [str(elfuse), '--user', '501:20', '--sysroot', str(root), '--timeout', '60', str(bundle/'files/bin-arm64/wine'), 'C:\\\\hello-x64.exe']
env = {'WINEPREFIX': str(prefix), 'WINEESYNC': '0', 'WINEFSYNC': '0', 'WINEDEBUG': '+loaddll,+process', 'PROTON_NO_ESYNC': '1', 'PROTON_NO_FSYNC': '1', 'PROTON_NO_NTSYNC': '1', 'WINESERVER': str(bundle/'files/bin-arm64/wineserver'), 'WINELOADER': str(bundle/'files/bin-arm64/wine')}
res = run_isolated(argv, LAB/'logs/fex-lifecycle', 65, extra_env=env)
print('hello-x64 exit:', res['exit'], 'target_exit:', res.get('target_exit'), 'stdout:', Path(res['stdout']).read_text().strip())
"
```
