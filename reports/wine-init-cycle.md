# Wine 初始化死锁循环断环点选择与语义回归方案报告 (v3 独立验收版)

- **任务编号**：task-111
- **执行角色**：wine-recovery-reviewer (Team Teammate)
- **审查目标**：基于 task-106 / task-110 确证的物理现场证据与调用栈回溯，精确定位 Wine 驱动初始化的依赖闭环；比较至少两个语义断环方案，给出推荐最小源码补丁候选与可验证回归计划；杜绝第二处 NOP 与假完成。
- **关联工件**：
  - 标准候选补丁文件：`sources/wine-init-cycle-analysis/wine_vulkan_reentrancy_guard.patch` (4,739 字节, 130 行，标准 `a/dlls/win32u/` 路径，经 `git apply --check` 与 `patch --dry-run` 零错误验证)
  - 机器可读综合数据：`logs/wine-init-cycle/cycle_analysis.json`
  - 上游原始固化源码：`sources/wine-init-cycle-analysis/upstream/dlls/win32u/` (5 个文件，含 URL/commit/SHA)
  - 独立 Native C 单元测试：`sources/wine-init-cycle-analysis/test_guard.c` (4 大核心场景全部 PASS)
  - 栈回溯判定报告：`reports/once478.md` (已按 Lead 意见修订术语与边界)

---

## 1. 执行摘要与核心主张

此前实验表明：
1. 原版 Wine 二进制在 `0x20102d440` 处发生初级重入自锁；
2. 单 NOP 实验版（`0x13a3f4: NOP`）阻断初级重入后，执行流在下游 `0x20102d478` 处再次暴露次级同线程自递归死锁（已由 task-110 的 6 级上层活跃帧身份绝对匹配闭环确证）。

> **核心技术裁定**：
> - **真正的架构死结**：在于“Vulkan 驱动初始化例程内部枚举显示适配器时，反向要求创建依赖该驱动本身的完整 Vulkan 实例”；
> - **正切依赖定位**：必须在 **原版架构依赖链**（即 `lock_display_devices` -> `get_vulkan_gpus`）上切除此递归边，而不是在单 NOP 派生环境中去“打地鼠”式 NOP 第二处 once；
> - **语义正确标准**：断环方案必须保证**不伪造完成**、**不读取未就绪驱动表**、**不引发 once-poisoning（永久缓存失败）**，且完全具备原生 fallback；
> - **Display Cache 边界客观定性**：虽然 `d3dkmt_vulkan_instance` 的 `pthread_once` 未被污染，但 GDI Display Cache 在缺乏外部显示模式变更事件（`WM_DISPLAYCHANGE`）时会被持久化在 Fallback 状态，其自然恢复状态必须定为 **`UNKNOWN`**。

---

## 2. 真实符号表与二进制调用偏移表 (readelf / nm / objdump 精确重建)

基于 `win32u.so`（SHA256: `2e282b95...` 与 baseline `4f6013fa...`）实际符号表与反汇编，重构函数入口与关键调用偏移表：

| 模块符号 (Symbol) | 符号类型 | 函数入口地址 (Entry) | 关键指令偏移 (Callsite / Instruction) | 返回地址偏移 (Return PC / LR) | 相对函数入口 Delta | 语义操作与目标说明 |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `__wine_get_vulkan_driver` | 导出 (T) | `0x139d00` | `0x139d20` | `0x139d24` | `+0x24` | `bl pthread_once@plt` (目标: `0x20102d440`, `vulkan_init_once`) |
| `vulkan_init_once` | 静态 (local) | `0x139da0` | `0x13a370` | `0x13a374` | `+0x5d4` | `blr x8` (调用 `driver_funcs->p_map_instance_extensions`) |
| `vulkan_instance_create` | 静态 (local) | `0x13a3c0` | `0x13a3f4` | `0x13a3f8` | `+0x38` | 原版: `bl pthread_once@plt` (`0x20102d440`); 单 NOP 版: `nop` |
| `lazydrv_map_instance_extensions` | 静态 (local) | `0x13aee0` | `0x13af00` | `0x13af04` | `+0x24` | `bl pthread_once@plt` (目标: `0x20102d478`, `vulkan_driver_init`) |
| `vulkan_driver_init` | 静态 (local) | `0x13af60` | `0x13af8c` | `0x13af90` | `+0x30` | `blr x8` (进入驱动枚举，Frame 13 活跃帧) |
| `get_vulkan_gpus` | 静态 (local) | `0x3b8e0` | `0x3b910` | `0x3b914` | `+0x34` | `bl pthread_once@plt` (内部触发 `get_d3dkmt_vulkan_instance`) |
| `d3dkmt_init_vulkan` | 静态 (local) | `0x3edb0` | `0x3edc0` | `0x3edc4` | `+0x14` | `bl vulkan_instance_create` (创建虚拟 D3DKMT 实例) |
| `lock_display_devices` | 静态 (local) | `0x125260` | `0x12540c` | `0x125410` | `+0x1b0` | `bl get_vulkan_gpus` |
| `lock_display_devices` | 静态 (local) | `0x125260` | `0x125444` | `0x125448` | `+0x1e8` | `bl get_opengl_gpus` (原生 Fallback 分支) |

---

## 3. 两次循环拓扑的精确重建与正本清源

### 1. 原版未改模块循环 (Original Unpatched Cycle)
在未经修改的官方 Wine 模块中：
```text
[Client] vkCreateInstance
  └── winevulkan.so + 0x9568
        └── win32u.so + 0x139d24 (__wine_get_vulkan_driver + 0x24)
              └── 【首次进入 0x20102d440】libc.so.6!pthread_once(&0x20102d440, vulkan_init_once)  [word 0 -> 1]
                    └── win32u.so + 0x13a374 (vulkan_init_once + 0x5d4)
                          └── win32u.so + 0x13af04 (lazydrv_map_instance_extensions + 0x24)
                                └── 【首次进入 0x20102d478】libc.so.6!pthread_once(&0x20102d478, vulkan_driver_init)  [word 0 -> 1]
                                      └── win32u.so + 0x13af90 (vulkan_driver_init + 0x30)
                                            └── win32u.so!load_desktop_driver -> lock_display_devices (+0x1b0)
                                                  └── win32u.so + 0x3b914 (get_vulkan_gpus + 0x34)
                                                        └── win32u.so + 0x3edc4 (d3dkmt_init_vulkan + 0x14)
                                                              └── win32u.so + 0x13a3c0 (vulkan_instance_create)
                                                                    └── 【死锁点：0x13a3f4】bl pthread_once(&0x20102d440, vulkan_init_once)
                                                                          └── 0x20102d440 仍为 word=1！同线程陷入 futex wait！
```
**原版死锁点**：在 `win32u.so + 0x13a3f4` 处重入 `0x20102d440`。

---

### 2. 单 NOP 实验版次级循环 (Single-NOP Experimental Derived Cycle)
在 `0x13a3f4` 处将 `bl pthread_once` 替换为 `nop` 后的派生模块中：
```text
[Client] vkCreateInstance
  ... (前置步骤与原版相同) ...
        └── win32u.so + 0x13a3c0 (vulkan_instance_create)
              ├── 【0x13a3f4: NOP】：跳过 0x20102d440 重入
              └── vulkan_instance_create 尾部继续执行 (win32u.so + 0x13a520)
                    └── win32u.so + 0x14c57c: lazydrv_map_instance_extensions
                          └── 【死锁点：0x13af04】bl pthread_once(&0x20102d478, vulkan_driver_init)
                                └── 0x20102d478 仍为 word=1（由本线程在 Frame 14-15 保持激活）！
                                └── 同线程陷入 futex wait（Line 10613，19 次 watchdog parked）！
```

### 3. 正本清源
- 单 NOP 实验版是破坏原版早期拦截点后暴露的派生环境次生行为，不可泛化为上游全部 Wine 版本的普遍架构缺陷；
- 真正的架构死锁源头在于：**Vulkan 驱动初始化例程通过显示系统反向要求创建依赖该驱动本身的完整实例**；
- 修复必须正切原版依赖（`lock_display_devices` -> `get_vulkan_gpus`），杜绝盲目实施第二处 NOP。

---

## 4. 上游固化原始源码清单 (Valve Wine dc26e618)

所有源码均直接取自官方仓库 **ValveSoftware/wine**，commit: `dc26e61847081a1b5cb0733dc30feba6ee575482`（标记为 `candidate_upstream_alignment`，非认证精确构建）：

| 相对路径 | 物理大小 (Bytes) | 行数 | SHA256 校验和 | 官方检索 URL |
| :--- | :---: | :---: | :--- | :--- |
| `dlls/win32u/vulkan.c` | 195,458 | 4,231 | `bacf0e55052b16f1d82115f5fa771bc67fc4a70cd2b56f25ada7b36dc76dffaf` | [vulkan.c](https://raw.githubusercontent.com/ValveSoftware/wine/dc26e61847081a1b5cb0733dc30feba6ee575482/dlls/win32u/vulkan.c) |
| `dlls/win32u/d3dkmt.c` | 74,504 | 2,101 | `c3e15eb08715e43fb385bf3900fc4ee6ff47271d9b8597882d52a2df61934747` | [d3dkmt.c](https://raw.githubusercontent.com/ValveSoftware/wine/dc26e61847081a1b5cb0733dc30feba6ee575482/dlls/win32u/d3dkmt.c) |
| `dlls/win32u/win32u_private.h` | 20,733 | 460 | `cb92fe0f67d7c57f0174b16a2bd5939e6dfc4c153894557fc873e658c8968902` | [win32u_private.h](https://raw.githubusercontent.com/ValveSoftware/wine/dc26e61847081a1b5cb0733dc30feba6ee575482/dlls/win32u/win32u_private.h) |
| `dlls/win32u/sysparams.c` | 309,780 | 8,330 | `2fbff2646eb2cb2e80f90a69c4f137b9e1a7df9691a53d54b9c2cc5d217572f9` | [sysparams.c](https://raw.githubusercontent.com/ValveSoftware/wine/dc26e61847081a1b5cb0733dc30feba6ee575482/dlls/win32u/sysparams.c) |
| `dlls/win32u/opengl.c` | 132,077 | 3,514 | `d57b4e26242210200053da46b2efe74fc7a8d4d7af71507397844510ba99f580` | [opengl.c](https://raw.githubusercontent.com/ValveSoftware/wine/dc26e61847081a1b5cb0733dc30feba6ee575482/dlls/win32u/opengl.c) |

所有 5 份源文件已完整固化在 `sources/wine-init-cycle-analysis/upstream/dlls/win32u/`。

---

## 5. 源码深度审计：控制流、回退路径与缓存 Poisoning

### 1. 遗漏 Hunk 根因解释与补齐
在上一轮草案中，补丁制作脚本由于字符串模式匹配出现未命中，仅替换了尾部 `failed:` 标签，遗漏了函数体上方的定义与进入点 hunk。本次已在不可变 `upstream/` 目录中完成整洁严密的标准 git diff 重建，生成了 130 行完整补丁，并通过真实命令验证。

### 2. Wine TLS 约定与消除 C 数据竞争
- 源码检视确认：Wine 的 `win32u` Unix 模块不使用 C11 `_Thread_local` 或 GCC `__thread`；
- 若使用非原子的全局变量 `static pthread_t thread; static int in_progress;`，在回调函数与并发查询之间存在跨线程并发读写的 **C 数据竞争 (Undefined Behavior)**；
- **真正线程局部方案**：采用 POSIX 标准的 **Thread-Specific Data (`pthread_key_t`)**：
  ```c
  static pthread_key_t vulkan_init_key;
  static pthread_once_t vulkan_key_once = PTHREAD_ONCE_INIT;

  static void init_vulkan_key(void) {
      pthread_key_create( &vulkan_init_key, NULL );
  }

  BOOL is_vulkan_init_in_progress(void) {
      pthread_once( &vulkan_key_once, init_vulkan_key );
      return pthread_getspecific( vulkan_init_key ) != NULL;
  }
  ```
  POSIX 保证每个线程拥有完全隔离的私有指针槽位，彻底消除跨线程数据竞争与内存屏障开销。

### 3. `vulkan_init_once` 完整退出路径成对清理 (C89 规范)
在 `dlls/win32u/vulkan.c:4093-4169` 中审查所有退出路径：
- **Exit 1 (Line 4109)**：`if (!vulkan_handle) { pthread_setspecific( vulkan_init_key, NULL ); return; }`
- **Exit 2 (Line 4117)**：`LOAD_FUNCPTR` 宏中 dlsym 失败时清除 key 后 `return;`
- **Exit 3 & 4 (Line 4188)**：正常完成或失败跳转至 `failed:` 标签，首行统一执行 `pthread_setspecific( vulkan_init_key, NULL );`
- **C89 规范**：变量声明严格置于代码块起始，避免在声明前插入可执行语句。

### 4. OpenGL 回退分支与锁重入审计
在 `dlls/win32u/opengl.c:3493` 审查 `get_opengl_gpus`：
- 该函数调用 `__wine_get_opengl_driver(WINE_OPENGL_DRIVER_VERSION)`，内部触发 `pthread_once(&init_once, display_funcs_init)`；
- `display_funcs_init` 仅调用 `user_driver->pOpenGLInit`，**不调用 `load_desktop_driver`，不调用 `lock_display_devices`，也不请求任何 Vulkan 相关锁**；
- 确证：当 `get_vulkan_gpus` 返回 `FALSE` 时，回退到 `get_opengl_gpus` **不会引发二次初始化自锁**。

### 5. Display Cache Poisoning（显示缓存持久化）关键判定
在 `dlls/win32u/sysparams.c:3061-3080` 中审查显示设备持久化逻辑：
```c
if (force)
{
    if (!get_vulkan_gpus( &ctx.vulkan_gpus )) WARN( "Failed to find any Vulkan GPU\n" );
    if (!get_opengl_gpus( &ctx.opengl_gpus )) WARN( "Failed to find any OpenGL GPU\n" );
    if (!(status = update_display_devices( &ctx ))) commit_display_devices( &ctx );
    release_display_manager_ctx( &ctx );

    ret = update_display_cache_from_registry( serial );
}
```
- **重要事实**：当 `get_vulkan_gpus` 返回 `FALSE` 时，注册表被写入了缺省 Vulkan 信息的设备记录，且 `monitor_update_serial` 被刷新为当前 serial；
- 随后的普通调用（`update_display_cache(FALSE)`）由于满足 `monitor_update_serial >= serial`，**将直接返回 TRUE，根本不会重新执行 `get_vulkan_gpus`**；
- 全局源码检视显示：`d3dkmt.c` 中 **没有任何调用 `update_display_cache(TRUE)` 强制刷新的逻辑**。
- **严谨结论**：
  - `d3dkmt_init_vulkan` 自身的 once 未被污染（因未被触发，依然为 `word=0`）；
  - **但是，GDI 显示设备缓存（Display Cache）确实会被持久化在 Fallback 状态，不能声称其具备“自然恢复能力”**；
  - 只有在外部产生显示模式变更（`WM_DISPLAYCHANGE`，`sysparams.c:4557`）或显式触发 `update_display_cache(TRUE)` 时，Vulkan 物理 GPU 属性才会被重新写入 GDI 显示注册表；
  - **在无外部事件介入前，后续 GDI 设备列表对 Vulkan 属性的恢复状态必须界定为 `UNKNOWN`（存在持久缓存盲区）**。

---

## 6. 三种首次入口场景推导分析

| 场景 | 触发入口与序列 | TLS 状态机转移 | 自锁风险分析 | 最终行为推导 |
| :--- | :--- | :--- | :--- | :--- |
| **场景 A：首次入口为 Vulkan**<br>*(已在 task-106/110 实测)* | `vkCreateInstance` -> `vulkan_init_once` -> `vulkan_driver_init` -> `lock_display_devices` -> `get_vulkan_gpus` | 进入 `vulkan_init_once` 时设置 `vulkan_init_key=1` | 无补丁时在 `0x20102d440`（原版）或 `0x20102d478`（单 NOP）自死锁 | **补丁成功拦截**：`get_vulkan_gpus` 返回 `FALSE`，走 OpenGL/默认回退，驱动顺利就绪，退出时 key 清空。 |
| **场景 B：首次入口为 D3DKMT**<br>*(游戏先调 D3D9/DXGI/D3DKMT)* | `NtGdiDdDDIEnumAdapters2` -> `get_d3dkmt_vulkan_instance` -> `pthread_once(&once, d3dkmt_init_vulkan)` -> `vulkan_instance_create` -> `vulkan_init_once` -> `vulkan_driver_init` -> `lock_display_devices` -> `get_vulkan_gpus` -> `get_d3dkmt_vulkan_instance` | 1. 进入 `d3dkmt_init_vulkan` 时设置 `d3dkmt_init_key=1`<br>2. 随后进入 `vulkan_init_once` 时设置 `vulkan_init_key=1` | 若无保护，会在自身 `d3dkmt_vulkan_instance` 的 `&once` 上再次自死锁！ | **双重保护拦截**：<br>1. `get_vulkan_gpus` 检测到 `vulkan_init_key`，返回 `FALSE`；<br>2. `get_d3dkmt_vulkan_instance` 亦具备 `is_d3dkmt_init_in_progress()` 检查直接返回 NULL，彻底阻断 D3DKMT 自身的重入。 |
| **场景 C：首次入口为 OpenGL**<br>*(应用先调 wglCreateContext)* | `wglCreateContext` -> `__wine_get_opengl_driver` -> `display_funcs_init` | 所有 key 为 NULL | `display_funcs_init` 不调 `lock_display_devices`，无环 | 正常初始化 OpenGL；后续若 GDI 触发设备枚举，归入场景 B 推导，安全放行。 |

---

## 7. 真实补丁 Apply-Check 与命令验证

### 1. 补丁文件
固化于：`sources/wine-init-cycle-analysis/wine_vulkan_reentrancy_guard.patch` (4,739 字节，130 行，标准 `a/dlls/win32u/` 路径)。

### 2. 真实命令与回显输出记录 (Zero Errors)

#### (1) `git apply --check` 命令输出
```bash
$ cd sources/wine-init-cycle-analysis/upstream && git apply --check -v ../wine_vulkan_reentrancy_guard.patch
Checking patch dlls/win32u/d3dkmt.c...
Checking patch dlls/win32u/vulkan.c...
Checking patch dlls/win32u/win32u_private.h...
Applied patch dlls/win32u/d3dkmt.c cleanly.
Applied patch dlls/win32u/vulkan.c cleanly.
Applied patch dlls/win32u/win32u_private.h cleanly.
$ echo "git apply exit: $?"
git apply exit: 0
```

#### (2) `patch --dry-run` 命令输出
```bash
$ cd sources/wine-init-cycle-analysis/upstream && patch -p1 --dry-run < ../wine_vulkan_reentrancy_guard.patch
patching file 'dlls/win32u/d3dkmt.c'
patching file 'dlls/win32u/vulkan.c'
patching file 'dlls/win32u/win32u_private.h'
$ echo "patch dry-run exit: $?"
patch dry-run exit: 0
```

#### (3) 独立鲜活目录 (`test_apply/`) 应用后 Grep 检验结果
在全新复制的 `test_apply/` 目录实际执行 `patch -p1` 并检索：
- `dlls/win32u/vulkan.c:10`: `BOOL is_vulkan_init_in_progress(void)` 实现存在；
- `dlls/win32u/vulkan.c:4116`: 入口 `pthread_setspecific( vulkan_init_key, (void *)(intptr_t)1 );` 存在；
- `dlls/win32u/vulkan.c:4129, 4139, 4190`: Exit 1, Exit 2 与 failed 标签清理存在；
- `dlls/win32u/d3dkmt.c:499`: `is_d3dkmt_init_in_progress` 实现存在；
- `dlls/win32u/d3dkmt.c:514, 516`: 入口与退出 key 设置存在；
- `dlls/win32u/d3dkmt.c:523`: `if (is_d3dkmt_init_in_progress()) return NULL;` 存在；
- `dlls/win32u/d3dkmt.c:1037`: `if (is_vulkan_init_in_progress()) return FALSE;` 存在；
- `dlls/win32u/win32u_private.h:221`: `extern BOOL is_vulkan_init_in_progress(void);` 声明存在。

---

## 8. 独立 Native C Standalone 单元测试验证 (`test_guard.c`)

在 `sources/wine-init-cycle-analysis/test_guard.c` 中构建了不依赖 Wine 大型构建的独立 C 单元测试，完全采用候选补丁的 `pthread_key_t` 源码实现与仿真调用链路，使用原生 Clang 编译运行：

```bash
$ clang -Wall -Wextra -pthread -O2 test_guard.c -o test_guard
$ ./test_guard
=== Native Re-entrancy Guard Test Suite ===
[Test 1] Running Scenario A: First Vulkan Entry...
  -> PASS: Deferred without recursion, driver inited, TLS cleaned up.
[Test 2] Running Scenario B: First D3DKMT Entry...
  -> PASS: D3DKMT initiated without self-deadlock, TLS cleaned up.
[Test 3] Running Scenario C: Concurrent Thread Isolation...
  -> PASS: Thread B saw FALSE while Thread A held TLS key. No cross-thread data race.
[Test 4] Running Exit Cleanup Verification on Early Errors...
  -> PASS: All 3 failure exit paths restored TLS key to NULL cleanly.
=== ALL 4 NATIVE GUARD TESTS PASSED ===
```

**测试结论**：
1. **Scenario A (首次 Vulkan)**：正常放行，驱动顺利初始化，避免死锁；
2. **Scenario B (首次 D3DKMT)**：正常放行，实例顺利创建，避免 D3DKMT 自身死锁；
3. **Scenario C (并发隔离)**：并发线程 B 观察到自身的 key 始终为 NULL，与主线程绝对隔离，无任何数据竞争；
4. **Early Exit Cleanup**：所有失败返回分支均正确释放 thread key，无悬挂状态。

---

## 9. 分层定性声明与可验证回归测试矩阵

### 1. 分层定性声明 (Layered Verdict)
- **语法与补丁可应用性 (Syntactically Applicable)**：**PASS (通过)**，diff hunk 行号与上下文与 Valve Wine dc26e618 官方源码 100% 严密吻合，`git apply --check` 与 `patch --dry-run` 零错误；
- **核心断环逻辑正确性 (Guard Logic Correctness)**：**PASS (通过)**，经由 `test_guard` 真实 C 代码 4 大场景覆盖验证，无跨线程数据竞争；
- **全量 Wine 构建可行性 (Build Viability)**：**UNVERIFIED (待证)**，当前 lab 未配置 Wine 全量交叉编译链，未在本任务进行侵入式编译；
- **Display Cache 恢复语义 (Cache Recovery)**：**UNKNOWN (存在盲区)**，GDI 显示设备缓存缺乏后续主动刷新机制，在无外部显示模式变更前属于未证实状态。

### 2. 可验证回归测试矩阵

| 矩阵项 ID | 覆盖场景 | 关键验证点 | 预期合格标准 |
| :--- | :--- | :--- | :--- |
| **R1_BASELINE_ORIGINAL** | 原版未改模块对照基准 | 验证原版自锁重现性 | 必须重现 `0x20102d440` 处的 `ENTER=2, futex=1`。 |
| **R2_BASELINE_NOP** | 单 NOP 实验版对照基准 | 验证次级自锁重现性 | 必须重现 `0x20102d478` 处的 `ENTER=2, futex=1` 及 Frame 17~22 一致性。 |
| **R3_RECURSION_GUARD** | 候选 Patch 运行验证 | 验证循环边是否被正确断开 | 驱动初始化期间 `get_vulkan_gpus` 返回 `FALSE`，`vulkan_driver_init` 顺利返回，无 futex 等待。 |
| **R4_CONCURRENT_THREAD** | 并发调用与线程安全 | 验证 TLS 隔离未伤及并发线程 | 独立辅助线程发起 D3DKMT 调用，不被主线程的 `vulkan_init_key` 阻塞。 |
| **R5_DISPLAY_CACHE_REFRESH** | 后续 GDI 显示缓存刷新 | 验证是否存在 Display Cache Poisoning | **[核心待证项]** 驱动初始化后触发 `update_display_cache(TRUE)`，核查 GDI 设备列表能否补全 Vulkan 设备。 |
| **R6_VK_INSTANCE_SUCCESS** | 端到端探针最终验收 | 跨过 Step 3 进入 Step 4 | 探针 `vkCreateInstance` 成功返回 `VK_SUCCESS`，探针进入 Step 4，退出码 0。 |
