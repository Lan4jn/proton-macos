# Wine 初始化防重入 Guard v2 深度审查与 Callback 层失败注入验证报告 (v2 修复与缺陷定性版)

- **任务编号**：task-112
- **执行角色**：wine-guard-verifier (Team Teammate)
- **审查与修订目标**：
  1. 修复 task-111 候选补丁的确定性语法与头顺序缺陷；
  2. 响应 Team Lead 审查意见，补测真实应用源码 Callback 控制流；
  3. 通过失败注入揭露并定性 **Once-Poisoning（单次初始化污染）** 架构死结；
  4. 消除测试用例中一切 `usleep` 违例，基于 POSIX `pthread_cond` 与 `pthread_join` happens-before 确立零睡眠同步；
  5. 客观收紧裁定边界，坚决杜绝在集成门禁上冒充整体成功。
- **实验工件根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`
- **关联工件与物理哈希**：
  - 机器可读综合收据：`logs/wine-guard-v2/receipt.json`
  - v1 10 项编译阻断日志：`logs/wine-guard-v2/v1_compile_failure.log`
  - v2 标准候选补丁：`sources/wine-init-guard-v2/wine_vulkan_reentrancy_guard_v2.patch` (5,797 字节, SHA256: `9d7670a8ac9fbfd8bff8e3b96861925c44047d6188c3af0ade3b7436f8eea866`)
  - 自动提取 real 源码与 callback 流：`sources/wine-init-guard-v2/extracted_guard.c` (SHA256: `100d2b9f948d255fd22249882eab4866b803ed4938eaa5bb3d9e66c7c9850d48`)
  - 自动化提取脚本：`scripts/runtime/wine_guard_v2/extract_guard.py`
  - 端到端验证与收据套件：`scripts/runtime/wine_guard_v2/run_guard_v2_suite.py`
  - 8 大场景原生测试执行器：`sources/wine-init-guard-v2/test_guard_v2`
  - 测试套件全量日志：`logs/wine-guard-v2/test_guard_v2.log`

---

## 1. 全局判定矩阵与审查定性 (Scope Verdicts)

根据 Team Lead 代码审查与最新回调层失败注入测试，对 Guard v2 形成分层裁定：

| 检验层次 / 维度 | 裁定结果 | 详细依据与技术边界 |
| :--- | :---: | :--- |
| **v1 补丁语法与头文件顺序** | **CONFIRMED_DEFECTIVE** | v1 在 `vulkan.c` 首行注入代码，先于 `config.h` 与 `<pthread.h>`，引发 `pthread_key_t` 等 10 项编译阻断（`v1_compile_failure.log`）。 |
| **v2 Guard 基础 Helper 语法** | **PASS** | Guard 代码移至 `WINE_DEFAULT_DEBUG_CHANNEL` 之后，`query/enter/exit/cleanup` 全集齐备；标准 `a/dlls/win32u/` 路径，`patch -p1` 零错误应用。 |
| **Helper 级基础状态与隔离** | **PASS** | 同线程状态平衡、两线程隔离、早退清理均通过；全部使用 `pthread_cond_t/mutex` 同步，**实现真正的 0 sleep**。 |
| **Helper 级资源失败拦截** | **PASS** | `key_create` 失败拒绝读取未创建 key，不假装成功；`setspecific` 失败返回 FALSE 拦截进入。 |
| **嵌套调用 (Nested Enter) 契约** | **RESTRICTED_PREMISE** | **不支持深度计数**。布尔型 TLS 标记在嵌套退出时会将 TLS 归零，导致外层作用域失保。严正声明架构前提：**严禁同线程嵌套 enter**，重入点必须依赖 `query` 分支规避。 |
| **真实 Wine 源码取消点覆盖** | **UNKNOWN** | 补丁虽定义了 `vulkan_init_guard_cleanup`，但 **Wine 上游源码从未在 `vulkan_init_once` 或 `d3dkmt_init_vulkan` 中注册 `pthread_cleanup_push`**；且上游无显式禁用取消源码证据，实际运行时取消覆盖定性为 **UNKNOWN**。 |
| **Callback 层 Once-Poisoning** | **FAIL (RED_CONFIRMED)** | **核心架构缺陷暴露**：当 `d3dkmt_init_vulkan` 因瞬时资源不足 `guard_enter` 失败提前 return 时，外层 `pthread_once` 仍将其标记为完成（done）。资源恢复后后续调用永不重试，实例永久为 NULL。 |
| **Wine 完整构建 (Full Build)** | **NOT_RUN** | 隔离实验环境中无完整 Wine SDK 及 `configure` 生成配置，恪守规则标记 **`full_build=not_run`**。 |
| **Wine 死锁解决与调用链打通** | **UNKNOWN** | 不将 Helper 层的局部测试冒充为 Wine 死锁已被修复，整体状态维持 **UNKNOWN**。 |

---

## 2. Callback 层 Once-Poisoning 架构死结与 RED 测试确证

### 2.1 缺陷机理分析
在 POSIX 标准（IEEE Std 1003.1）中：
```c
int pthread_once(pthread_once_t *once_control, void (*init_routine)(void));
```
- `pthread_once` 仅在 `init_routine` 被线程取消（cancellation）或异常终止时，才允许保持未初始化状态；
- 若 `init_routine` 执行了普通的 `return;`（即使其内部因资源分配失败、Guard 进入失败而提前返回），POSIX `pthread_once` 均判定该例程已**顺利执行完毕**，并将控制字永久置为完成态（`word = 2`）。

在当前 v2 补丁的 `d3dkmt.c` 回调控制流中：
```c
static void d3dkmt_init_vulkan(void)
{
    ...
    if (!d3dkmt_init_guard_enter())
    {
        WARN( "Failed to enter d3dkmt init guard\n" );
        d3dkmt_vulkan_instance = NULL;
        return; /* 此处正常 return 导致 pthread_once 标记为完成！ */
    }
    d3dkmt_vulkan_instance = vulkan_instance_create( &extensions );
    d3dkmt_init_guard_exit();
}

static struct vulkan_instance *get_d3dkmt_vulkan_instance(void)
{
    static pthread_once_t once = PTHREAD_ONCE_INIT;
    if (is_d3dkmt_init_in_progress()) return NULL;
    pthread_once( &once, d3dkmt_init_vulkan );
    return d3dkmt_vulkan_instance;
}
```

**暴露的严重后果**：
若系统在首次调用时遭遇瞬时 TLS 资源紧张（`pthread_key_create` 返回 `EAGAIN`），`d3dkmt_init_vulkan` 提前 `return`。外层 `once` 控制字被永久置为完成。随后系统资源恢复，上层再次调用 `get_d3dkmt_vulkan_instance()` 时，`pthread_once` 直接跳过回调，函数永久返回 `NULL`，导致整个进程生命周期内 Vulkan 彻底瘫痪（**Once Poisoning**）。

### 2.2 RED 测试执行证据 (Scenario 8)
为忠实反映真实行为，从打补丁后的 `d3dkmt.c` 真实截取上述回调流注入测试（用例 8）：
1. 步骤 1：注入瞬时 `key_create` 失败（`EAGAIN`），首次调用 `get_d3dkmt_vulkan_instance()`，返回 `NULL`；
2. 步骤 2：恢复系统资源（`fault_inject_key_create = 0`）；
3. 步骤 3：再次调用 `get_d3dkmt_vulkan_instance()` 试图重试恢复；
4. 真实结果：`inst2` 依然为 `NULL`！`assert(inst2 != NULL)` 触发断言崩溃（Exit 134 / SIGABRT）：

```text
--- Running [8. Callback Once-Poisoning On Resource Failure (RED Test)] ---
  [S8] Testing callback-level once-poisoning from real patched d3dkmt control flow...
  [S8] Step 1: Inject transient resource failure (fault_inject_key_create = 1)...
  [S8] First call returned inst1 = 0x0 (expected NULL due to resource failure)
  [S8] Step 2: System resources recover (fault_inject_key_create = 0)...
  [S8] Step 3: Subsequent call attempting recovery...
  [S8] Second call returned inst2 = 0x0
  [S8] [RED DEFECT PROVEN] Once-poisoning confirmed: pthread_once permanently poisoned as NULL!
Assertion failed: (inst2 != NULL), function scenario_callback_once_poisoning, file test_guard_v2.c, line 490.
[RESULT: RED_CONFIRMED] 8. Callback Once-Poisoning On Resource Failure (RED Test) (Deliberate failure reproduced architectural limitation)
```
**结论**：该测试已被确立为 **RED 测试**，证实单纯在 `d3dkmt_init_vulkan` 内做 `return NULL` 无法抵御瞬时资源失败，构成了架构层面的恢复阻塞。

---

## 3. 同步机制修正与取消模型定性

### 3.1 彻底清除 `usleep` 违规，确立纯条件变量同步
此前测试中用例 6 在取消轮询循环中遗留了 `usleep(1000)`，与“0 处 sleep”的声明冲突。本次修订彻底重构该测试：
```c
    pthread_cleanup_push(test_cancel_cleanup, NULL);
    sync_advance_to(ctx->sync, 1);

    /* POSIX 规范标准取消点：pthread_cond_wait */
    pthread_mutex_lock(&ctx->cancel_mutex);
    while (1) {
        pthread_cond_wait(&ctx->cancel_cond, &ctx->cancel_mutex);
    }
    pthread_mutex_unlock(&ctx->cancel_mutex);
    pthread_cleanup_pop(0);
```
- 工作线程进入 Guard 后在 `pthread_cond_wait` 处挂起，该函数为 POSIX 标准取消点；
- 主线程接收到进入就绪通知后直接调用 `pthread_cancel`，线程立刻响应取消进入清理栈；
- **实现 100% 真正的零睡眠（0 sleep）条件同步**。

### 3.2 内存可见性与 Join Happens-Before 核验
- 标志位 `cleanup_executed` 的更新发生在被取消线程的清理处理程序 `test_cancel_cleanup` 中；
- 主线程通过 `pthread_join(thread, &res)` 同步等待工作线程退出；
- **内存模型保证**：根据 IEEE Std 1003.1 (POSIX) 规范，`pthread_join()` 的成功返回在终止线程执行的所有内存写入（包括取消清理程序中的写入）与主线程后续读取之间建立了严格的 **happens-before** 偏序关系，从而消除了乱序读取风险。

### 3.3 真实 Wine 取消机制定性：UNKNOWN
- **补丁现状**：补丁中虽导出了 `vulkan_init_guard_cleanup` 函数，但 **`vulkan.c` 与 `d3dkmt.c` 上游源码本身没有任何一处调用 `pthread_cleanup_push`**；
- **上游现状**：检索 `dlls/win32u` 上游源码，既无 `pthread_cleanup_push`，亦无 `pthread_setcancelstate(PTHREAD_CANCEL_DISABLE)`；
- **裁定结论**：在没有明确上游源码凭证的情况下，不得妄称“Wine 运行时已实现取消覆盖”，亦不得妄称“Wine 已完全禁用取消”。其实际取消覆盖状态定性为 **`UNKNOWN`**。

---

## 4. 边界约束：非嵌套（Non-nested）布尔标记契约

当前 Guard v2 实现基于单布尔值 TLS 指针：
```c
pthread_setspecific( vulkan_init_key, (void *)(intptr_t)1 );
```
在测试用例 7（`scenario_nested_enter_limitation`）中实测证明：
1. 若同一线程执行嵌套 `enter()`，TLS 依然保持为 1（无深度计数器）；
2. 内层作用域退出执行 `exit()` 时，TLS 被重置为 `NULL`；
3. 此时外层作用域尚未结束，但 `is_vulkan_init_in_progress()` 已变为 `FALSE`，导致外层临界区失保！

**架构操作前提 (Operational Premise)**：
本 Guard 严格建立在 **“单次非嵌套进入（non-nested single-entry）”** 契约之上。任何调用者在存在重入可能性的路径上，**必须先调用 `is_..._in_progress()` 判定并走 fallback 分支，绝对严禁无条件嵌套调用 `enter()`**。若未来需要支持同线程合法嵌套递归，必须升级为递归计数深度模型。

---

## 5. 8 大场景全景测试凭据 (test_guard_v2)

执行命令：`clang -Wall -Wextra -pthread -I. test_guard_v2.c -o test_guard_v2 && ./test_guard_v2`  
输出凭据（落盘于 `logs/wine-guard-v2/test_guard_v2.log`）：

```text
============================================================
Wine Win32u Reentrancy Guard v2 & Callback Suite
Running 8 isolated scenarios via fork()...
============================================================

--- Running [1. Same-thread State Balance] ---
  [S1] Checking initial query states...
  [S1] Entering vulkan init guard...
  [S1] Entering d3dkmt init guard...
  [S1] Exiting d3dkmt init guard...
  [S1] Exiting vulkan init guard...
  [S1] Secondary re-entrance test...
  [S1] Passed same-thread state balance.
[RESULT: PASS] 1. Same-thread State Balance

--- Running [2. Two-thread Isolation (Barrier/Cond Sync)] ---
  [S2] Monitor observed vulkan guard state: 0 (expected 0 / FALSE)
  [S2] Passed two-thread isolation (0 sleep cond sync).
[RESULT: PASS] 2. Two-thread Isolation (Barrier/Cond Sync)

--- Running [3. Early Exit Error Cleanup] ---
  [S3] Simulating early exit on vulkan failure...
  [S3] Simulating early exit on d3dkmt failure...
  [S3] Passed early exit error cleanup.
[RESULT: PASS] 3. Early Exit Error Cleanup

--- Running [4. Resource Error: pthread_key_create Failure] ---
  [S4] Injecting pthread_key_create failure (EAGAIN)...
  [S4] Querying guard when key creation fails...
  [S4] Attempting guard enter when key creation fails...
  [S4] Guard exit when key uncreated must be safe no-op...
  [S4] Passed pthread_key_create failure handling.
[RESULT: PASS] 4. Resource Error: pthread_key_create Failure

--- Running [5. Resource Error: pthread_setspecific Failure] ---
  [S5] Initializing key successfully first...
  [S5] Injecting pthread_setspecific failure on enter (EINVAL)...
  [S5] Testing setspecific(NULL) cleanup failure path...
  [S5] Observed: if setspecific(NULL) fails, guard cannot clear TLS (contract limitation).
  [S5] Passed pthread_setspecific failure handling & boundary check.
[RESULT: PASS] 5. Resource Error: pthread_setspecific Failure

--- Running [6. Reachable Cancellation Point Cleanup] ---
  [S6] Testing cancellation point cleanup...
  [S6] Note: Real Wine vulkan_init_once does NOT register pthread_cleanup_push in upstream.
  [S6] Verifying POSIX cleanup handler behavior upon thread cancellation (0 sleep)...
  [S6] Cleanup handler executed: 1 (via join happens-before)
  [S6] Passed cancellation point cleanup (0 sleep cond wait).
[RESULT: PASS] 6. Reachable Cancellation Point Cleanup

--- Running [7. Nested Enter Limitation (No Depth Counter)] ---
  [S7] Demonstrating non-nested boolean marker boundary...
  [S7] Inner exit cleared marker; outer scope unprotected: 1 (expected 1)
  [S7] Architectural premise established: Guard strictly requires non-nested invocation.
[RESULT: PASS] 7. Nested Enter Limitation (No Depth Counter)

--- Running [8. Callback Once-Poisoning On Resource Failure (RED Test)] ---
Assertion failed: (inst2 != NULL), function scenario_callback_once_poisoning, file test_guard_v2.c, line 490.
  [S8] Testing callback-level once-poisoning from real patched d3dkmt control flow...
  [S8] Step 1: Inject transient resource failure (fault_inject_key_create = 1)...
  [S8] First call returned inst1 = 0x0 (expected NULL due to resource failure)
  [S8] Step 2: System resources recover (fault_inject_key_create = 0)...
  [S8] Step 3: Subsequent call attempting recovery...
  [S8] Second call returned inst2 = 0x0
  [S8] [RED DEFECT PROVEN] Once-poisoning confirmed: pthread_once permanently poisoned as NULL!
[RESULT: RED_CONFIRMED] 8. Callback Once-Poisoning On Resource Failure (RED Test) (Deliberate failure reproduced architectural limitation)

============================================================
Summary: Total=8, Green_Passed=7, Red_Defects_Confirmed=1, Unexpected_Failed=0
============================================================
```

---

## 6. 处置结论与下一步建议

1. **当前补丁保留状态**：按 Lead 指令，**保留 v2 补丁原样，不立即改动生产候选**；
2. **集成裁定正式降级**：
   - 基础 Helper 接口与头顺序：**PASS**；
   - 真实源码提取与失败注入防御：**PASS**；
   - Callback 层重试与恢复性（Once-Poisoning）：**FAIL (RED_CONFIRMED)**；
   - 整体集成门禁裁定：**`ARCHITECTURAL_BLOCKER_ONCE_POISONING`**（存在架构级阻断，不可作为最终修复合入）；
3. **架构演进路线建议**：
   - 若要彻底根治 Once-Poisoning，必须对 `get_d3dkmt_vulkan_instance` 脱离原生 `pthread_once`，改用带有重试状态机的显式互斥锁（如 `pthread_mutex` + 状态字 `UNINIT / IN_PROGRESS / READY / RETRYABLE_FAIL`），或在上层建立显式的驱动重新加载通道。
