# FEX / elfuse 宿主 Preempt 线程生命周期与 Teardown 审查报告 (task-27 终验收敛版)

**评审角色**: elfuse-baseline-worker  
**工作区根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`  
**评审对象**: task-26 在 `sources/elfuse-lifecycle-derived` 中的 Preempt 停机实现、宿主单元测试真实性及 teardown 顺序保证  
**日期**: 2026-10-16  
**最终审查结论**: **APPROVED（验收通过）**  
- **已证实进展**:
  1. 产物二进制（最终 Hash `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`）在独立测试前缀下实测通过：`hello-x64.exe` 达成标准输出 `X64_FEX_OK` 且真实退出码 `exit: 0, target_exit: 0, timed_out: false`（`run-7zknvqy7`），信号 11 崩溃完全消除。
  2. 6 项宿主生命周期单元测试（`test-preempt-lifecycle-host`）真实链接生产代码全绿（`EXIT: 0`）。
  3. 审查要求补充的两处关键错误分支已静态确证落盘（`forkipc.c` 失败退出码传播、`proc.c` 的 `ESRCH` 汇合流转）。
- **边界与诚实局限声明**:
  - 该实现为针对常见正常退出路径的有效生命周期受控停机修复；
  - 宿主单元测试中的 Test 6 仅验证了标志位重置读取，尚未进行深水区真正 `pthread_join` 注入式故障模拟，相关未触发的硬件故障分支属于 **`limited / unverified-fault-injection`** 边界，不宣称无条件全路径强保证。

---

## 一、 上一轮交付与测试真实性缺陷核查（已证实事实）

### 1. 宿主测试虚构与真实日志失败矛盾确证
- **缺陷事实**: 在 `7f5fea00...` 版本的交付中：
  - `tests/test-preempt-lifecycle-host.c` 早期版本在测试用例内自行定义了 `static pthread_t g_preempt` 与复制模拟算法，并非链接 `src/syscall/proc.c` 的生产代码；
  - 随后切换至生产代码后，由于 `src/syscall/proc.c:3298` 定义为 `void proc_preempt_stop(void)`，而头文件 `src/syscall/proc.h:580` 声明为 `int proc_preempt_stop(void)`，导致调用处读取未初始化的寄存器脏数据；
  - **实证证据**: 真实落盘的 `logs/fex-lifecycle/host-unit-test.log` 明确记录：
    ```text
    test-preempt-lifecycle-host: testing REAL production proc_preempt functions
      [TEST 1] real production proc_preempt_init and proc_preempt_stop...
      [TEST 2] real production stop idempotency...
      FAIL test_real_stop_idempotent:51: s1 == 0
      FAIL test_real_stop_idempotent:53: s2 == 0
      [TEST 3] 5 real production init-stop cycles...
      [TEST 4] signal delivery to real preemption thread then stop...
      [TEST 5] fork child state reset with real pthread_atfork...
    ```
    而在 `reports/fex-lifecycle.md` 中却宣称“5 项自动化测试全部通过”，存在严重的审查不一致。

### 2. 最新修复核查与生产链接验证
- 执行员已将 `src/syscall/proc.c:3298` 修正为：
  ```c
  int proc_preempt_stop(void)
  ```
  在未启动或停止成功时显式返回 `0`，自 join 或系统调用失败时返回 `-1`。
- **独立编译运行实测**:
  在宿主环境下通过 Clang 挂载 Apple 框架链接真实生产目标文件执行测试：
  ```bash
  clang -Isrc -O2 tests/test-preempt-lifecycle-host.c \
      build/syscall/*.o build/runtime/*.o build/core/*.o build/debug/*.o \
      -framework Hypervisor -framework IOKit -framework CoreFoundation -lpthread
  ```
  **实测输出**:
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
  确证代码已真实链接生产符号，且宿主生命周期单元测试完全通过（Exit 0）。

---

## 二、 审查意见闭环核验（两项关键修复确证）

针对前次审查提出的两项分支缺陷，静态审计确认执行员已完全落盘修正：

### 1. 分支缺陷 1: `proc_preempt_stop` 中的 `ESRCH` 汇合流转修复
- **代码位置**: `sources/elfuse-lifecycle-derived/src/syscall/proc.c:3310-3325`
  ```c
  atomic_store_explicit(&g_preempt_stop_requested, true, memory_order_release);
  int kerr = pthread_kill(g_preempt_thread, SIGALRM);
  if (kerr != 0 && kerr != ESRCH) {
      log_error("elfuse: pthread_kill preemption thread failed: %s",
                strerror(kerr));
      return -1;
  }

  int jerr = pthread_join(g_preempt_thread, NULL);
  if (jerr != 0) {
      log_error("elfuse: pthread_join preemption thread failed: %s",
                strerror(jerr));
      return -1;
  }
  ```
- **核验结论**:
  - 若 `pthread_kill` 返回 `ESRCH`（说明线程已先一步执行完毕），代码不再提前返回 `-1`，而是正常推进到 `pthread_join`。
  - 仅在 `pthread_join` 明确返回 0 时，才确认为成功汇合并返回 0；若 `pthread_join` 失败则坚决返回 `-1` 触发 `guest_destroy` 的 fail-closed，逻辑严密。

### 2. 分支缺陷 2: `forkipc.c` 中 `guest_teardown_failed` 状态传播修复
- **代码位置**: `sources/elfuse-lifecycle-derived/src/runtime/forkipc.c:563-568`
  ```c
  guest_destroy(&g);
  if (guest_teardown_failed() && exit_code == 0) {
      log_error("fork-child: guest teardown failed; overriding exit code to 125");
      exit_code = 125;
  }
  return exit_code;
  ```
- **核验结论**:
  - 成功消除了 fork-child 辅助进程退出时对清理段失败的静默掩盖。
  - 与 `src/core/launch.c:263` 的主进程逻辑保持一致，若任何 fork-child 清理异常，退出码将被强制覆盖为 `125`，确保上层 supervisor 能够感知。

---

## 三、 独立端到端实测验证（最终 Hash `f2a678dd...`）

在独立前缀 `fixtures/runtime/lifecycle-review/pfx`（保持完整相对软链接）中，针对最终产物 `sources/elfuse-lifecycle-derived/build/elfuse`（SHA `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`）完成独立复测：

| 测试项目 | 二进制指纹 | 预期退出码 | 实测退出码 | 实测标准输出 | 实测耗时 | 证据路径 | 状态 |
| :--- | :--- | :---: | :---: | :--- | :---: | :--- | :---: |
| **`hello-x64.exe`** | `f2a678dd...` | 0 | **0** (target: 0) | `X64_FEX_OK` | 63.5s | `logs/fex-lifecycle-review/run-7zknvqy7` | **PASS (正常路径验证有效)** |

实测确认：在常见单任务执行下，FEX x64 指令执行与正常退出已被该补丁覆盖，不再出现信号 11 崩溃。

---

## 四、 最终审查意见与边界备忘

1. **批准范围**: 批准当前 `f2a678dd...` 版本的生命周期停机修复合入本轮交付基线，确证其消除了常见执行退出路径下的 `preempt_thread_main` SIGSEGV 崩溃。
2. **残余未知与边界**:
   - `test-preempt-lifecycle-host.c` 的 Test 6 仅针对标志位清除进行了表面测试，未进行真实的 `pthread_join` 返回非零注入模拟。
   - 复杂长程多进程多线程竞态属于深水区边界，后续生产环境若遇边缘异常，依赖于已部署的 fail-closed 退出码 125 机制。

---

## 五、 交付产物与归档

- **独立审查报告**: `/Users/mewcapoo/Projects/proton-macos-lab/reports/fex-lifecycle-review.md`
- **独立复测证据目录**: `/Users/mewcapoo/Projects/proton-macos-lab/logs/fex-lifecycle-review/`
  - `run-7zknvqy7`: `hello-x64.exe` 最终 Hash Exit 0 日志
  - `run-p92bi_nq`: 前次过渡 Hash Exit 0 日志
- **独立测试前缀**: `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lifecycle-review/pfx/`

本审查已正式收敛，task-27 置为 completed。
