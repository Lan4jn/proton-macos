# Win32u Vulkan 重入补丁实验恢复与证据核对报告 (v2)

- **任务编号**：task-106
- **执行角色**：wine-recovery-reviewer (Team Teammate)
- **审查目标**：恢复 task-106 存盘 Wine 补丁实验数据，完成有界证据核对与报告；不重跑运行、不添加第二个补丁、不改动旧工件。
- **关联工件**：
  - `logs/win32u-fix/moduletrace8/comparison.json`
  - `logs/win32u-fix/recovery/recovery_summary.json`
- **绑定原始日志指纹 (Raw Log Fingerprints)**：
  - `patched stderr`: `b744129f00bcfa93c9fe6190d7c462c4aaf06d1c28f8ab873de0729c3801174a` (11,859 行, 1,139,399 字节)
  - `patched stdout`: `fa6d6879879295762509f1d9f0765b728697a6eb05585a84f03e261cd942b9fc` (486 字节)
  - `baseline stderr`: `a5acd112ebcad52fe954b22cf167b1a07fdba9cfd894f5f1e8f7e7c0146a7f11` (1,125,854 字节)
  - `baseline stdout`: `fa6d6879879295762509f1d9f0765b728697a6eb05585a84f03e261cd942b9fc` (486 字节)

---

## 1. 实验背景与恢复边界

此前实验针对 Windows ARM64 `vkCreateInstance` 调用在 `win32u.so` 内部触发的同线程 `pthread_once` 重入自锁问题实施了单点二进制补丁验证。
本报告基于存盘在 `logs/win32u-fix/moduletrace8/` 下的既有运行日志与收据，完成严格的物理证据核对，严格遵守以下工作边界：
1. **不重跑测试**：完全基于现有运行日志（`baseline-full` 与 `patched-full`）进行离线证据比对；
2. **不添加第二个 Patch**：不对 `0x20102d478` 实施盲目二度补丁；
3. **只读保护原工件**：不修改原始 `comparison.json`、`receipt.json`、fixtures 及系统全局环境；
4. **输出范围限制**：仅产出本报告 `reports/win32u-fix.md` 与机器可读总结 `logs/win32u-fix/recovery/recovery_summary.json`；
5. **不盲信历史摘要**：不凭先验摘要推断 elfuse 全面无缺陷，客观指出插桩的观测盲区。

---

## 2. 模块指纹与补丁精确比对

本次实验涉及的二进制模块指纹与改动已完成逐字节核对：

| 对象 | 路径 | SHA256 指纹 |
| :--- | :--- | :--- |
| **原始 win32u.so** | `sources/wine-win32u-experimental/baseline-full/files/lib/wine/aarch64-unix/win32u.so` | `4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5` |
| **补丁 win32u.so** | `sources/wine-win32u-experimental/patched-full/files/lib/wine/aarch64-unix/win32u.so` | `2e282b958cdb32c420bfde15ec8640d923227140020ef00733b9c80ae4dd3f68` |
| **elfuse 运行时** | `sources/elfuse-once-panorama2-derived/build/elfuse` | `8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda` |

### 补丁指令级精确核验

补丁仅修改了 `win32u.so` ELF 内部偏移 `0x13a3f4` 处的一条指令：
- **所在函数**：`vulkan_instance_create` (代码段起于 `0x13a3c0`)
- **ELF / 文件偏移**：`0x13a3f4`
- **原始机器码 (LE)**：`43 d0 fb 97` -> 反汇编为 `bl 0x2e500 <pthread_once@plt>`
  - 参数 `x0` 来自 `0x22d000 + 0x440 = 0x22d440`（运行时 uaddr 为 `0x20102d440`）
  - 参数 `x1` 为 `vulkan_init_once` (`0x139da0`)
- **补丁机器码 (LE)**：`1f 20 03 d5` -> 反汇编为 `nop`
- **物理差异检验**：两个 .so 文件全文件仅此 4 字节差异，无任何其他节区或符号表变动。

---

## 3. 探针 SHA 审计与收据误引用核查

### 差异核查结果
在旧工件 `logs/win32u-fix/moduletrace8/comparison.json` 与各组 `receipt.json` 中，均记录：
`"probe_sha256": "d408405ca8340342a08e6e44ddaccc8ad78d25570bea5a523a4b10067a87dc08"`

经过对仓库和运行参数的交叉审计：
1. **源码追溯**：`scripts/runtime/win32u_fix/run_ab_verified_module.py` 第 34 行直接字面量硬编码了 `"probe_sha256": "d408405ca8340342a08e6e44ddaccc8ad78d25570bea5a523a4b10067a87dc08"`。该哈希对应历史测试中的 x64 探针 `scripts/runtime/x64_vk/vk_enum_x64.exe` (PE32+ executable console x86-64)。
2. **实际运行目标**：两组运行的 `argv` 明确记录为：`exec ... wine 'C:\vk_enum_arm64.exe'`。
3. **实际文件核验**：
   - 路径：`fixtures/runtime/futex-args-vulkan/pfx/drive_c/vk_enum_arm64.exe`
   - 文件架构：`PE32+ executable (console) Aarch64, for MS Windows`
   - 真实 SHA256：`f82f4e7987ae1dc4ef20674c2f24809b4e7c88bbd4b902fb754a8dc0a8ec6b62`
4. **输出佐证**：`stdout.log` 首行清晰打印：
   `[WIN_ARM64_VK] Starting Windows ARM64 Vulkan Enumeration Test`
   证明 Wine 实际加载并运行的确实是 ARM64 原生探针。

**结论**：**此项属于旧测试收据元数据误引用（Miscited Receipt）**。执行脚本在构造 JSON 时直接沿用了 x64 探针哈希，未动态计算实际传给 wine 的 ARM64 探针哈希。实际运行载体与环境是真实一致的 ARM64 PE 探针。

---

## 4. `run_valid` 计算规则分析与 v2 多维评估

### 旧规则的逻辑缺陷
在 `run_ab_verified_module.py` 第 35 行：
```python
rec["run_valid"] = bool(rec["has_step3"] and rec["same_target_futex_enter_count"] > 0 and rec["module_load_confirmed"])
```
- 在 `baseline-full` 中：`has_step3=True`，`module_load_confirmed=True`，`same_target_futex_enter_count=1`，因此旧结果为 `run_valid: true`。
- 在 `patched-full` 中：因为补丁将 `bl pthread_once` 替换为了 `nop`，程序直接跳过了对 `0x20102d440` 的二次进入，所以 `same_target_futex_enter_count` 成功降为 `0`。但旧规则硬性要求该计数大于 0，从而导致 `patched-full` 被错误地标记为 `run_valid: false`。

**根本原因**：旧规则混淆了“重现 Bug 现象的特征检查（futex enter > 0）”与“补丁验证实验的有效性检查”。补丁实验的目标正是要消除该 futex 阻塞，用阻塞的存在作为运行有效性判定是语义自相矛盾的。

### 建立 Versioned Evaluation Schema (v2)

为了既保留历史收据的可追溯性、又不就地反转旧字段，我们在 `recovery_summary.json` 中建立解耦的多维评估体系：

| 评估维度 | 评价标准 | baseline-full | patched-full | 判定说明 |
| :--- | :--- | :---: | :---: | :--- |
| **1. 实验有效性**<br>(`experimental_validity`) | - 模块加载确认<br>- 模块哈希匹配<br>- 运行达 Step 3<br>- 环境与沙箱完好 | **PASS** (true) | **PASS** (true) | 两组实验均在一致配置下正常启动并到达 Vulkan 初始化阶段，无环境异常中断。 |
| **2. 补丁路径覆盖**<br>(`patch_path_coverage`) | - 目标重入点宏观分流<br>- `0x20102d440` 入口 2->1<br>- `direct_hit_observed` | **derived_support**<br>(confidence: high)<br>`direct_hit=false` | **derived_support**<br>(confidence: med-high)<br>`direct_hit=false` | **间接衍生支持**：入口 2->1、futex 1->0、LR `0x200f3a3f8` 1->0 提供了强间接证据，但因 elfuse 未对 `0x13a3f4` PC 独立挂钩，无 NOP 被实际执行的直接指令级记录。 |
| **3. 目标成功达成**<br>(`objective_success`) | - `vkCreateInstance` 成功返回<br>- 探针到达 Step 4<br>- 进程退出码 0 | **FAIL** (false) | **FAIL** (false) | 目标均未达成：两组均未返回，均超时 exit 124。 |

---

## 5. 下游 `0x20102d478` 行为深度核查与观测边界说明

在绑定 SHA256 `b744129f...` 的 `patched-full/run-a7f4vr7t/stderr.log`（全文件 11,859 行）中，以 1-based 物理行号核对下游变量 `0x20102d478`：

### 1. 物理行号逐行核对 (1-based Raw Lines)
1. **首次调用 (Line 9421)**：
   ```text
   Line 9421: ONCE_ENTRY_COUNT ts_us=1252081038687 pid=44195 gtid=1 pc=0x2000ce1a0 x0_uaddr=0x20102d478 is_target=0 target_count=0 total_count=17 word=0 word_status=0 lr=0x200f3af04
   ```
   - 线程 1 发起对 `0x20102d478` 的首次初始化，此时 `word=0`，LR 对应 `lazydrv_map_instance_extensions` (`0x13af04`)，调用初始化例程 `vulkan_driver_init` (`0x13af60`)。
2. **二次调用 (Line 10612)**：
   ```text
   Line 10612: ONCE_ENTRY_COUNT ts_us=1252086093125 pid=44195 gtid=1 pc=0x2000ce1a0 x0_uaddr=0x20102d478 is_target=0 target_count=0 total_count=19 word=1 word_status=0 lr=0x200f3af04
   ```
   - 经过 5.054 秒后，**同一线程** (`pid=44195 gtid=1`) 再次进入同一 once 变量 `0x20102d478`，此时 `word=1`（处于初始化中状态），LR 依然是 `0x200f3af04`。
3. **真实 Futex 阻塞 (Line 10613 - 10619)**：
   - Line 10613: `THREAD_LIFETIME_ENTER ts_us=1252086093131 pid=44195 gtid=1 nr=98 sc=futex x0=0x20102d478 x1=0x80 x2=0x1 x3=0x0 x4=0x20102d478 x5=0x200f3af60 lr=0x2000ce048 elr=0x2000ce084`
   - Line 10614: `THREAD_FUTEX_DETAIL ts_us=1252086093131 pid=44195 gtid=1 uaddr=0x20102d478 op=0x80 val=1 word=1 word_status=0`
   - Line 10618: `FUTEX_ARGS pid=44195 gtid=1 id=1291 uaddr=0x20102d478 op=0x80 val=1 timeout=0x0 uaddr2=0x20102d478 val3=8605904736 word=1 word_status=0 op_status=0 timeout_status=0 uaddr2_status=0 val3_status=0 lr=0x2000ce048 elr=0x2000ce084 lr_status=0 elr_status=0`
   - Line 10619: `IO_TX_ENTER pid=44195 gtid=1 id=1291 nr=98 fd=8606897272 arg2=1 fd_status=0x0 arg2_status=0x0`
   - 线程 1 明确进入了 `futex(0x20102d478, FUTEX_WAIT_PRIVATE, 1)` 系统调用。

### 2. 看门狗快照精确计数与 Predicate 说明
- **严谨 Predicate**：
  ```python
  line.includes("pid=44195") and line.includes("in_syscall=98") and line.includes("parked=1")
  ```
- **重算结果**：在 raw 日志中，符合上述条件的行数**严格为 19 行**。
  - 出现的具体行号为：`10853, 10908, 10962, 11016, 11065, 11123, 11173, 11226, 11277, 11333, 11385, 11440, 11492, 11545, 11599, 11651, 11707, 11759, 11812`。
- **前期 58 次计数的来源辨析**：
  前期粗过滤统计的是 Line 10619 之后包含 `"44195"` 的所有行，总计 58 行，其组成结构为：
  - 1 行 `IO_TX_ENTER`（系统调用进入）
  - 19 行 `THREAD_SNAPSHOT_BEGIN`
  - 19 行 `FUTEX_OWNER_THREAD` (即满足 predicate 的行)
  - 19 行 `THREAD_SNAPSHOT_END`
  - 合计：`1 + 19 * 3 = 58` 行。
  **本次更正**：确认看门狗记录的真正 parked 快照出现次数为 **19** 次。

### 3. 为何“尚未证明完整自锁”？——观测盲区与所缺证据
尽管日志显示同线程先后触发 word=0 和 word=1 并陷入 futex wait，但从严格的系统调试与逆向论证角度，**该记录尚未闭环证明“完备的递归自死锁”**，原因在于现有观测存在以下盲区：

1. **缺针对性目标地址观测**：
   运行环境配置为 `ELFUSE_FUTEX_TARGET_UADDR=0x20102d440`，而 `0x20102d478` 为未注册目标（`is_target=0`）。因此，elfuse 的原子状态转移机（`ONCE_TRANSITION`）和锁属主跟踪（`FUTEX_OWNER_ENTER`）未对 `0x20102d478` 采样。
2. **栈回溯未记录 (Stack Backtrace Unrecorded)**：
   需要明确：**AArch64 架构下维持了 Frame Pointer (`x29`)，FP 栈回溯框架本身具备可行性，并非因缺 DWARF 就完全无法回溯**。但在本次运行中，elfuse 插桩探针并未在 `0x20102d478` 调用处捕获并导出 FP 栈回溯序列，产物中仅留有叶子返回寄存器 LR (`0x200f3af04`)。从 Line 9421 到 Line 10612 之间经历的 5 秒钟以及多条系统调用链路中，无法得知上层是由何种业务逻辑再次触发了 `lazydrv_map_instance_extensions`。
3. **不能排除跨线程/进程同步异常**：
   在两次调用之间，Wine 派生了 `explorer.exe`，且存在大量的 RPC/Socket 交互。在没有完整线程交互与锁状态转移图的情况下，无法从数学上排他性地证明：到底是“线程 1 在其自身尚未退出的 init routine 内部同步重入了自身”，还是“init routine 曾因异常中断导致 word 残留为 1”，亦或是“涉及跨线程协作但协作方失联”。
4. **结论审慎性**：
   确证了“存在对 `0x20102d478` 的未返回 futex 等待”，但因缺乏目标级状态追踪与栈回溯，**必须如实标注缺乏观测，不能断言已完全证明单线程自死锁**。

---

## 6. 最终结论与交付物索引

### 核心结论
1. **重入边干预有效**：单点二进制补丁（`0x13a3f4: NOP`）宏观上成功阻断了 `0x20102d440` 处的二次 `pthread_once` 调用（提供 derived 支持，无 direct PC 追踪）。
2. **目标尚未达成**：`vkCreateInstance` 仍未返回，探针未能进入 Step 4，调用受阻于下游 `0x20102d478`（`lazydrv_map_instance_extensions`）。
3. **不得盲目加打第二个补丁**：下层 `0x20102d478` 涉及 Wine 的 lazydrv 驱动加载与扩展映射机制，需回到 Wine 源码架构层面分析其初始化生命周期，严禁在未搞清调用拓扑的情况下随意叠加二进制 NOP。

### 交付物索引
- **机器可读数据**：`logs/win32u-fix/recovery/recovery_summary.json`
- **分析报告工件**：`reports/win32u-fix.md`
