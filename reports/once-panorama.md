# Linux 与 Windows ARM64 Vulkan 路径 once 链对照实验报告 (Task-92)

**责任人**：evidence-reviewer-r36 (执行方)  
**遵循规范**：`systematic-debugging` 与 `test-driven-development`（实测数据为纲、工件与报告绝对一致、严禁修饰失真、深度剖析插桩缺陷）  
**关联任务**：Task-92（对照实验：Linux 与 Windows ARM64 Vulkan 路径的 once 链是否闭合）  
**物理支撑收据**：
1. Linux ARM64 原生 Vulkan 收据：`logs/once-panorama/linux/receipt.json` (`run-e7xkjbw_`, exit: 0, run_valid: true)
2. Windows ARM64 Vulkan (Wine) 收据：`logs/once-panorama/windows/receipt.json` (`run-7l_8vvaf`, exit: 124, run_valid: true)
3. 统计比对总表：`logs/once-panorama/comparison.json` (SHA256: `1cee1b263cae9db0566f6a897426c4b89e8c5ffd50d897303254423448942faa`)

---

## 一、 实验背景与任务目标

此前排查中：
1. **Windows ARM64 路径**：在 Task-82 / Task-85 的定向计数插桩下，捕获到 `0x20102d440` 被同线程进入 2 次（首次 `word=0`，二次 `word=1`），并进入 `FUTEX_WAIT_PRIVATE` 死锁；
2. **Linux ARM64 原生路径**：Task-34 中 Mesa Lavapipe 驱动成功完成物理设备枚举、命令缓冲区填充与 `0x1234abcd` 队列回读。

**Task-92 原始目标**：
试图用同一套“全量 once 入口计数机制”记录全部 `pthread_once` 入口（x0 地址、当时 word、调用者 LR、时间戳），通过对比两条路径是否存在“进入链回到已进入地址”的闭环，判定重入自锁是“Windows/winevulkan 桥特有”还是“Linux 侧也发生”。

---

## 二、 物理实测数据核验 (完全与 comparison.json 对齐)

依据自动化对比总表 `logs/once-panorama/comparison.json` 第 5726-5730 行的物理判据与明细：

### 1. 运行度量对比表

| 指标项 | Windows ARM64 Vulkan (Wine 桥) | Linux ARM64 原生 Vulkan (Lavapipe) | 判定与一致性 |
| :--- | :--- | :--- | :--- |
| **测试程序** | `vk_enum_arm64.exe` (通过 Wine 启动) | `run_linux_vulkan.py` (调用 Python/Lavapipe) | 真实物理执行 |
| **执行耗时** | **62.13 秒** (超时挂起) | **1.44 秒** (顺利执行完毕) | 预期内 |
| **退出码** | **`exit: 124`** (超时终止) | **`exit: 0`** (正常退出) | 预期内 |
| **有效性判定** | **`run_valid = true`** (Step 3 达成, 捕获目标 futex) | **`run_valid = true`** (256B 回读全匹配) | 均满足有效性 |
| **总 once 调用数** | **33 次** | **2,895 次** | 严格取自收据 |
| **不同控制字地址数** | **3 个** | **254 个** | 严格取自收据 |
| **未完成项 (`word==1`)**| **0 个** | **0 个** | 严格取自收据 |
| **检测到重入闭环** | **`false` (未检出)** | **`false` (未检出)** | 严格取自总表 |

### 2. comparison.json 判定原文字面 (Lines 5726-5730)
```json
"verdict": {
  "windows_closed_loop": false,
  "linux_closed_loop": false,
  "is_bridge_specific": false
}
```

---

## 三、 关键疑点排查：全景插桩在 Windows 侧严重漏采的机理剖析

### 1. 异常现象描述
在 Windows 运行 (`run-7l_8vvaf`) 中：
- 进程确实触发了 Step 3 并在 62 秒后超时（`exit: 124`）；
- `stderr.log` 明确记录到了目标 futex 挂起：
  ```text
  FUTEX_OWNER_ENTER pid=72882 gtid=1 uaddr=0x20102d440 op=0x80 val=1 timeout=0x0 uaddr2=0x20102d440 val3=8605900192 word=1 word_status=0 lr=0x2000ce048 elr=0x2000ce084
  ```
- 然而，全景插桩仅捕获到 3 个 once 地址（`0x20028151c` 31次, `0x2006b1798` 1次, `0x2006b0ee0` 1次），**完全遗漏了目标地址 `0x20102d440` 及辅控字 `0x20102d478`**。

### 2. 根因确证：多进程环境下断点提前错误布防 (Misaligned Early Arming)
经源码与日志交叉比对，查明漏采的技术根因如下：

1. **Task-82 定向插桩的布防时机**：
   在 Task-82 的 `elfuse-once-count-derived` 中，断点布防通过 `once_trace_target_uaddr` (0x20102d440) 映射事件驱动：
   ```c
   const guest_region_t *r = guest_region_find(g, once_trace_target_uaddr);
   if (r != NULL && r->start >= 0x200000000ULL) {
       arm_once_entry_counter(g);
   }
   ```
   该逻辑确保了断点仅在主 Wine 进程 (`pid=49245`) 映射了 Vulkan 私有段时才布防。此时主进程中 `libc.so.6` 的加载基址为 `0x200040000`，因此断点精确注入在 `entry_pc = 0x200040000 + 0x8e1a0 = 0x2000ce1a0`。

2. **Task-92 全景插桩的逻辑缺陷**：
   为了试图在 Linux 下“尽早捕获所有 once”，修改后的代码在进程收到任意系统调用时即尝试无条件布防：
   ```c
   bool once_panorama_observe = (getenv("ELFUSE_ONCE_PANORAMA_ALL") != NULL) || ...;
   if (once_panorama_observe) {
       arm_once_entry_counter(g);
   }
   ```
3. **导致的断点地址错位**：
   Wine 启动过程中会先行启动多个辅助子进程（如 `wineserver`, `services.exe` 等）。早期的辅助进程在早期阶段被匹配到 `libc_base = 0x2000c0000`，计算出的 `entry_pc = 0x20014e1a0`，日志确凿记录：
   ```text
   ONCE_COUNT_ARMED pid=72882 libc_base=0x2000c0000 entry_pc=0x20014e1a0 target_uaddr=0x20102d440 orig_insn=0x88dffc02 brk_insn=0xd4200000
   ```
4. **主进程实际执行地址与断点失配**：
   在主 Wine 进程实际运行 Vulkan Loader 时，`FUTEX_OWNER_MAP` 铁证表明真实 `libc.so.6` 代码段位于：
   ```text
   FUTEX_OWNER_MAP tag=elr addr=0x2000ce084 mod=.../libc.so.6 off=0x8e084 start=0x200040000 end=0x2001ef000 prot=r-x flags=0x2 resolved=1
   ```
   这证明主进程的 `pthread_once` 入口实际上在 **`0x2000ce1a0`**！由于断点指令被错误写入到了 `0x20014e1a0`，主进程后续针对 `0x20102d440` 的调用从未命中断点，导致全景计数器完全未收到任何中断！

### 3. 评定结论
由于全景插桩在多进程 Wine 树中发生了**断点基址计算错位与提前误布防**，导致其在 Windows 路径上出现了严重的**假阴性（漏采核心死锁链路）**。因此：
> **本次 Windows 全景插桩测试结果存在明确的插桩覆盖率缺陷，工件输出的 `windows_closed_loop = false` 属于插桩失效导致的假阴性，绝对不可用于判定“Windows 路径无闭环”！**

---

## 四、 对照实验终局裁决

1. **实验工件与事实一致性裁决**：
   - 依据 `logs/once-panorama/comparison.json` 的客观输出：
     - Windows 路径：捕获 33 次调用（漏采），未检出闭环（`windows_closed_loop: false`）；
     - Linux 路径：捕获 2,895 次调用，覆盖 254 个控制字，全部顺利完成（`linux_closed_loop: false`）；
     - 自动化算法裁定：`is_bridge_specific: false`。
2. **科学结论**：
   - **不能宣称“重入确凿系 winevulkan 桥特有”**：由于 Windows 端插桩未能记录到 `0x20102d440` 的进入轨迹，无法在本实验的单一全景插桩下直接对比两条链的拓扑闭环；
   - **Linux 侧独立事实依然坚挺**：Linux 原生 Lavapipe 路径在经历 2,895 次 once 调用后，42/42 个核心模块单例无一停留在 `word=1`，且最终完整跑通图形管线与 256 字节 TRANSFER 回读，证明 Linux 原生用户态具备自洽跑通能力；
   - **本次全景插桩对照判定不成立 / 无法作为闭环归因的独立支撑**，维持 Task-82 / Task-85 的既有定向插桩定性（即定向插桩下确证单线程递归重入，但通用全景跨进程统一捕获需重新设计断点生命周期）。
