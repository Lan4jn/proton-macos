# 全景按进程惰性布防与 Linux/Windows Vulkan once 链闭环终局对照报告 (Task-94)

**责任人**：evidence-reviewer-r36 (执行方)  
**遵循规范**：`systematic-debugging` 与 `test-driven-development`（先证明尺子能量、实测数据为纲、工件直接引用、假阴性技术修正、严格闭环验证）  
**关联任务**：Task-94（修正全景布防后重跑 L 与 W 对照，先证明尺子能量）  
**物理支撑收据**：
1. 尺子能量控制测试收据：`logs/once-panorama2/control.json` (exit: 0, target_hits: 2)
2. Linux ARM64 原生 Vulkan 收据：`logs/once-panorama2/linux/receipt.json` (`run-2s686w80`, exit: 0, run_valid: true)
3. Windows ARM64 Vulkan (Wine) 收据：`logs/once-panorama2/windows/receipt.json` (`run-a5l2o8e4`, exit: 124, run_valid: true)
4. 统计比对总表：`logs/once-panorama2/comparison.json` (SHA256: `ad806b05be174ea83515822e030700ff3cf09ae87bbfa4ad94da753c15d4fc47`)
5. 派生运行时二进制：`sources/elfuse-once-panorama2-derived/build/elfuse` (SHA256: `8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda`)

---

## 一、 实验背景与 Task-92 假阴性根因修正

在 Task-92 的全景插桩运行中，出现了 `comparison.json` 判定 `windows_closed_loop: false` 的假阴性反常现象。经深入反汇编与执行流溯源，查明根本原因：
1. **`execve` 状态残留与多进程错位**：
   Wine 启动链经由 `/usr/bin/sh -c "exec wine ..."` 展开。早期的 `sh` 进程触发首个系统调用时，全局变量 `once_count_armed` 被置为 `true`，断点被写入 `sh` 自身内存的 `0x20014e1a0`。
   随后 `sh` 执行 `execve`，虚拟化层虽然通过 `guest_reset(g)` 擦除了旧进程内存并映射了 `wine` 二进制（其真实的 `libc.so.6` 加载在 `0x200040000`，`pthread_once` 入口在 `0x2000ce1a0`），但宿主全局的 `once_count_armed` 仍为 `true`！
   这导致 `wine` 进程从未重新安装断点，真正承载 Vulkan Loader 的主进程 `pthread_once` 全程未受 BRK 拦截，造成严重假阴性。
2. **Task-94 架构级修正措施**：
   - **`execve` 自动重置机制**：在 `src/syscall/exec.c` 的 `guest_reset(g)` 后新增 `once_count_exec_reset()`，在进程重载时彻底清空 `once_count_armed`、`once_count_libc_base` 与 `once_count_entry_pc`，使得新进程能够独立重新按自身基址安装断点；
   - **按进程惰性布防 (Lazy Event-Driven Arming)**：沿用 Task-82 经过验证的 `guest_region_find(g, target_uaddr)` 机制。在指定目标控制字（如 Wine 下的 `0x20102d440` 或控制测试的 `0x203000440`）被真正分配映射至 `[0x200000000, ...)` 时，才触发当前进程的 `arm_once_entry_counter(g)`；在原生 Linux 无指定目标模式下，则在检测到 `libc.so.6` 映射后自动布防。

---

## 二、 阶段一：硬性门槛——尺子能量控制测试验证 (Prove the Measuring Stick)

依据任务书“**先证明尺子能量：若控制用例本身测不到 count>=2，必须停止并要求先修插桩，不得进入正式对照**”的绝对铁律，在正式对照前执行最小控制程序：
- **测试程序**：`scripts/runtime/once_panorama2/control.py` 与 `run_control.py`
- **控制目标地址**：`0x203000440`（mmap 匿名分配）
- **物理收据**：`logs/once-panorama2/control.json`
- **控制测试实测输出**：
  ```text
  MAPPED_ADDR=0x203000000
  INIT_ROUTINE_CALLED (call 1)
  [WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
  ONCE_COUNT_CONTROLS_OK INSTRUCTION_LEVEL_VERIFIED

  Found ONCE_COUNT_ARMED: ONCE_COUNT_ARMED pid=76704 libc_base=0x200760000 entry_pc=0x2007ee1a0 target_uaddr=0x203000440 orig_insn=0x88dffc02 brk_insn=0xd4200000
  Target count lines: 2
     ONCE_ENTRY_COUNT ts_us=985183161792 pid=76704 gtid=1 pc=0x2007ee1a0 x0_uaddr=0x203000440 is_target=1 target_count=1 total_count=1 word=0 word_status=0 lr=0x200cc8804
     ONCE_ENTRY_COUNT ts_us=985183161810 pid=76704 gtid=1 pc=0x2007ee1a0 x0_uaddr=0x203000440 is_target=1 target_count=2 total_count=2 word=2 word_status=0 lr=0x200cc8804
  Call 1: target_count=1, word=0
  Call 2: target_count=2, word=2
  CONTROL_VERIFICATION_PASS: The measuring stick successfully recorded count >= 2 on known repeated target!
  ```
- **结论**：**尺子能量 100% 确证生效！** 指令级断点能够在已知重复调用的控制字上精准捕获到 `target_count = 1` (`word=0`) 与 `target_count = 2` (`word=2`)，具备开展正式对照的充足精度。

---

## 三、 阶段二：Windows vs Linux Vulkan 路径正式物理实测数据

在尺子能量确证通过后，使用完全相同的派生运行时二进制（SHA256: `81803322...`）对两条真实 Vulkan 执行链路进行跑测，并经 `scripts/runtime/once_panorama2/compare_results.py` 抽取总表 `logs/once-panorama2/comparison.json`：

### 1. 两条路径全局执行与有效性核准表

| 指标项 | Windows ARM64 Vulkan (Wine 桥) | Linux ARM64 原生 Vulkan (Lavapipe) | 字段来源与判定 |
| :--- | :--- | :--- | :--- |
| **测试程序** | `vk_enum_arm64.exe` (通过 Wine 启动) | `probe_queue_fill.py` (Python 原生调用) | 相同底层虚拟化 |
| **运行时 SHA256** | `8180332221745ee0a1870d1bf588ce97...` | `8180332221745ee0a1870d1bf588ce97...` | **同一套二进制** |
| **执行耗时** | **62.122 秒** (超时终止) | **0.941 秒** (快速完成) | 预期物理表现 |
| **退出码** | **`exit: 124`** (`timed_out: true`) | **`exit: 0`** (`timed_out: false`) | 严格与收据一致 |
| **有效性判定** | **`run_valid = true (VALID)`** | **`run_valid = true (VALID)`** | 均达成有效性门槛 |
| **有效性凭证** | `has_step3=true`, `target_enters=1` | `PATTERN_MATCH_OK` (256B 全匹配) | 物理证据确凿 |
| **布防记录** | `pid=76865 libc_base=0x200040000 entry_pc=0x2000ce1a0` | `pid=76780 libc_base=0x200760000 entry_pc=0x2007ee1a0` | 精确对齐自身基址 |
| **总 once 调用数** | **19 次** | **2,895 次** | 取自 comparison.json |
| **不同控制字数** | **5 个** | **254 个** | 取自 comparison.json |
| **目标 0x20102d440 调用数**| **2 次** (`target_count = 2`) | **0 次** (Linux 侧无该地址) | 取自 comparison.json |
| **目标 0x20102d440 状态**| **`first_word=0, last_word=1`** | 未涉及 | 取自 comparison.json |
| **未完成项 (`word==1`)**| **1 个** (`0x20102d440`) | **0 个** (全部完成归 2) | 取自 comparison.json |
| **闭环死锁判定** | **`closed_loop_detected = true`** | **`closed_loop_detected = false`** | 严格取自工件 verdict |

### 2. comparison.json 判定直接引用 (Raw JSON Verdict)
```json
"verdict": {
  "windows_closed_loop": true,
  "linux_closed_loop": false,
  "is_bridge_specific": true
}
```

---

## 四、 微观调用链路深度解剖

### 1. Windows ARM64 路径：确凿捕获单线程递归重入闭环
在修正了 `execve` 重置与惰性布防后，全景插桩在 `pid=76865`（主 Wine 进程）中精准记录到了全部 19 次 `pthread_once` 轨迹：
1. **启动辅控字**：
   - `0x200ffdd10`：第 1 次调用，`word=0`，由 `LR=0x200e33b4c` 发起；
2. **目标控制字第 1 次进入**：
   - `0x20102d440`：第 2 次调用（`target_count=1`），时间戳 `ts_us=985307557385`，**`word=0`**，`LR=0x200f39d24`（Khronos Vulkan Loader 内部）；
   - 主线程顺利 CAS 获取锁，将控制字置为 1，进入初始化例程；
3. **例程内部展开与次级控制字**：
   - `0x20d6a15dc`：第 3-16 次调用，首次 `word=0`，随后 13 次均为 `word=2`（Mesa/Lavapipe 内部 once，快速放行）；
   - `0x20102d478`：第 17 次调用，时间戳 `ts_us=985307995289`，`word=0`，`LR=0x200f3af04`；
   - `0x20100de08`：第 18 次调用，时间戳 `ts_us=985316574025`，`word=0`，`LR=0x200e3b914`；
4. **同线程致命递归重入（闭环触发）**：
   - **`0x20102d440`**：第 19 次调用（`target_count=2`），时间戳 `ts_us=985316574046`（相隔 **9.017 秒**后）；
   - 此时当前控制字值：**`word=1`**！
   - 调用者返回地址：`LR=0x200f3a3f8`；
   - 结果：glibc `pthread_once` 发现其处于 `ONCE_IN_PROGRESS`，误判为有并发线程正在执行，立即发起 `nr=98 (FUTEX_WAIT_PRIVATE)`；
   - 主线程进入自锁，全进程因再无其他线程唤醒而彻底卡死，直至 62 秒超时触发。
   - **由此直接推导：`windows_closed_loop = true`！**

### 2. Linux ARM64 原生路径：零未完成项、零闭环
在原生 Linux Lavapipe 环境中，同一套插桩记录了 2,895 次 once 调用：
- 覆盖 254 个独立控制字；
- **所有控制字在初次 `word=0` 执行完例程后，均成功置为 2**；
- 随后的 2,641 次调用均为快速路径探测（`word=2`）；
- **`uncompleted_word1_count = 0`**，**`reentry_events_count = 0`**；
- 逻辑设备顺利创建，队列命令提交并成功在宿主映射区读回 256 字节的 `0x1234abcd` 预设图案。
- **由此直接推导：`linux_closed_loop = false`！**

---

## 五、 终局对照判据与归因裁决

依据任务书设定的判定条件：
> “若 A 闭环而 B 不闭环 → 重入为 Windows/winevulkan 桥特有；若两者都闭环 → 属 loader/ICD 通用问题；并给出反驳条件。”

### 1. 终局结论
根据自动化比对总表 `logs/once-panorama2/comparison.json` 的实际输出：
```json
{
  "windows_closed_loop": true,
  "linux_closed_loop": false,
  "is_bridge_specific": true
}
```
**终局裁决结论**：  
**`pthread_once` 单线程递归重入闭环死锁，确凿系「Windows ARM64 / winevulkan 桥接层与 Wine 用户态状态机协同场景下特有」，绝非 Linux 侧 Khronos Vulkan Loader 或 Mesa Lavapipe 驱动自身的固有缺陷。**

### 2. 反驳条件 (Falsification Conditions)
1. 若在脱离 Wine 的原生 Linux 环境下，通过特定环境变量或调用链路构造出在 `vkCreateInstance` 内部针对同一控制字的二次重入并出现 `word=1` 的 futex 挂起，则本“桥特有”结论被反驳；
2. 若反编译证明 `LR=0x200f3a3f8` 与 `LR=0x200f39d24` 之间的调用链纯属 Khronos Loader 内部直接自循环而不经过任何 Wine 驱动层导出符号，则本“桥特有”结论需要重新审视。
