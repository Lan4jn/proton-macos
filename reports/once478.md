# Win32u 次级 once (0x20102d478) 调用栈回溯与递归自锁判定报告

- **任务编号**：task-110
- **执行角色**：wine-recovery-reviewer (Team Teammate)
- **审查目标**：判定已 NOP 原内层 once 之后，控制字 `0x20102d478` 的两次进入是否构成活跃调用栈内同线程递归自死锁。
- **关联工件**：
  - 运行收据：`logs/once478/run-1792773145/receipt.json`
  - 帧比对数据：`logs/once478/frame_comparison.json`
  - 原始运行现场：`logs/once478/run-1792773145/run-_z5b4krt/` (raw stderr SHA256: `10f2c6930dd5d4669a8c21e3334f74b50a6255a480209f282f442ae1e0e382ce`)
  - 派生执行器：`sources/elfuse-once478-derived/build/elfuse`

---

## 1. 核心结论与裁定

针对次级 once 变量 `0x20102d478` 的有界实验与 AArch64 Frame Pointer 栈回溯分析，获得**闭环确证**：

> **核心判定结果**：**CONFIRMED_RECURSIVE_DEADLOCK (确认活跃调用栈内同线程自递归死锁)**
> 
> **判定依据**：
> 1. **同线程确证**：两次入口均发生在同一线程（`pid=68655, gtid=1`）；
> 2. **上层活跃帧身份绝对匹配**：第二次入口时，第一次调用所触发的初始化例程 `vulkan_driver_init`（Frame 13，off `0x13af90`）在栈上**仍处于活跃未退出状态**；
> 3. **栈帧身份严格一致**：第二次入口回溯到的 Frame 17~22 与第一次入口的 Frame 1~6 形成 **6 级连续绝对匹配**——原始帧指针 FP 地址（`0x1000ffb80` 至 `0x1000ffcb0`）、next_fp、saved_lr 及模块偏移完全一致；
> 4. **等待自身致死**：第二次入口检测到控制字处于 `word=1`（由自身线程在首次进入时设置），因而进入 `futex(0x20102d478, FUTEX_WAIT_PRIVATE, 1)` 等待自身完成，导致该线程永久挂起，直至 62s 超时（exit 124）。

---

## 2. 派生执行器与二进制指纹

本次实验完全遵守任务边界，所有代码修改均限制在独立派生目录，Wine 二进制与探针均动态计算真实哈希：

| 对象 | 物理路径 | SHA256 指纹 |
| :--- | :--- | :--- |
| **elfuse-once478 运行时** | `sources/elfuse-once478-derived/build/elfuse` | `1db7ee6f7fdc7d1482e48c5f01360058783f03bd0ead5b79532598cd3fd94c1b` |
| **Wine win32u.so (patched)** | `sources/wine-win32u-experimental/patched-full/files/lib/wine/aarch64-unix/win32u.so` | `2e282b958cdb32c420bfde15ec8640d923227140020ef00733b9c80ae4dd3f68` |
| **实际运行探针** | `drive_c/vk_enum_arm64.exe` (PE32+ Aarch64) | `f82f4e7987ae1dc4ef20674c2f24809b4e7c88bbd4b902fb754a8dc0a8ec6b62` |

### 运行时派生改动 (Diff from sources/elfuse-once-backtrace-derived)
1. **默认目标设定**：将 `once_count_target_uaddr` 默认值设为 `0x20102d478ULL`，且支持环境变量 `ELFUSE_ONCE_COUNT_UADDR` 覆盖；
2. **全量寄存器采集**：在断点捕获处增加对用户栈指针 SP（`HV_SYS_REG_SP_EL0`）的读取，连同 `x29 (FP)`、`x30 (LR)`、`PC` 一并打入日志；
3. **回溯深度扩展**：将 `MAX_BT_FRAMES` 由 32 扩展至 40；
4. **终止原因显式记录**：在 `ONCE_BACKTRACE_SUMMARY` 中记录精确终止原因（`term_reason=fp_non_monotonic`），并输出每帧的 `saved_lr` 与 `next_fp`；
5. **Session 诊断支持保持**：保留 `ELFUSE_DIAG_SESSION_SHARED` 内存映射门禁支持，防止由于基线功能丢失导致测试假阴性。

---

## 3. 实验配置与执行现场

- **执行命令**：`python3 scripts/runtime/once478/run_once478.py`
- **运行环境**：
  - `WINEPREFIX`: `logs/once478/run-1792773145/pfx` (基于 `fixtures/runtime/futex-args-vulkan/pfx` 完整复制)
  - `ELFUSE_ONCE_COUNT_UADDR`: `0x20102d478`
  - `ELFUSE_FUTEX_TARGET_UADDR`: `0x20102d478`
  - `ELFUSE_DIAG_SESSION_SHARED`: `1`
  - `WINEDEBUG`: `+timestamp,+winstation,+vulkan,+explorer,+driver,+loaddll`
  - `WINEDLLPATH`: 指向 patched-full 对应的 aarch64-unix 目录
- **执行结果**：
  - 退出码：124 (超时被杀，运行持续 62.13s)
  - 探针 Step 3 到达：`[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...`
  - 探针 Step 4：未到达
  - `vkCreateInstance` 是否返回：**否**
  - `0x20102d478` 命中次数：**2 次**
  - 捕获 FP 回溯帧总数：**30 帧**（首次 7 帧，二次 23 帧）

---

## 4. 栈帧深度比对 (Frame Comparison)

### 1. 两次进入现场快照

| 字段 | 首次入口 (Entry 1) | 二次入口 (Entry 2) | 核验结论 |
| :--- | :--- | :--- | :--- |
| **时间戳** | `ts_us=1339479797630` | `ts_us=1339485851004` | 相隔 6.053 秒 |
| **线程** | `pid=68655, gtid=1` | `pid=68655, gtid=1` | **严格同一主线程** |
| **目标地址** | `0x20102d478` | `0x20102d478` | **同一控制字** |
| **Control Word** | **0** (未初始化) | **1** (初始化中，被自身持有) | **自锁必要条件达成** |
| **X29 (FP)** | `0x1000ffb80` | `0x1000faba0` | 栈向低地址生长（新栈帧深于旧栈帧） |
| **SP** | `0x1000ffb80` | `0x1000faba0` | 栈顶与 FP 吻合 |
| **LR (X30)** | `0x200f3af04` | `0x200f3af04` | `win32u.so!lazydrv_map_instance_extensions` |
| **PC** | `0x2000ce1a0` | `0x2000ce1a0` | libc `pthread_once` 入口断点 |

---

### 2. 激活上层帧身份绝对匹配表

对比 Entry 1 的调用帧与 Entry 2 栈链深处的上层帧，记录 FP 地址、saved LR 与模块归属：

| 首次深度 (Entry 1) | 二次深度 (Entry 2) | 原始帧指针 (FP) | 下一级帧指针 (next_fp) | 保存的返回地址 (saved_lr) | 对应模块与偏移 | 函数标识 / 语义 |
| :---: | :---: | :---: | :---: | :---: | :--- | :--- |
| **Frame 1** | **Frame 17** | `0x1000ffb80` | `0x1000ffbb0` | `0x200f3a374` | `win32u.so + 0x13a374` | `vulkan_init_once` |
| **Frame 2** | **Frame 18** | `0x1000ffbb0` | `0x1000ffc70` | `0x2000ce10c` | `libc.so.6 + 0x8e10c` | `__pthread_once_slow` |
| **Frame 3** | **Frame 19** | `0x1000ffc70` | `0x1000ffc90` | `0x2000ce1bc` | `libc.so.6 + 0x8e1bc` | `pthread_once` |
| **Frame 4** | **Frame 20** | `0x1000ffc90` | `0x1000ffca0` | `0x200f39d24` | `win32u.so + 0x139d24` | `__wine_get_vulkan_driver` |
| **Frame 5** | **Frame 21** | `0x1000ffca0` | `0x1000ffcb0` | `0x201899568` | `winevulkan.so + 0x9568` | `wine_vkCreateInstance` 内部桥接 |
| **Frame 6** | **Frame 22** | `0x1000ffcb0` | `0x11fe28` | `0x2002504e4` | `ntdll.so + 0x404e4` | NT 客户端调用入口 |

**匹配分析**：
- 这 6 级调用栈帧在 Entry 2 中**完全保留且连续**，每个guest 虚拟栈地址 (GVA)（`0x1000ffb80` ~ `0x1000ffcb0`）及其保存的返回地址（`saved_lr`）与 Entry 1 毫无二致；
- 这在物理上证明：**当 Entry 2 发生时，Entry 1 尚未返回，其整个调用上下文依然完整驻留并激活在调用栈上！**

---

### 3. 调用链完整拓扑还原

结合两次入口的 30 帧 FP 数据与反汇编符号，完整调用链路拓扑清晰呈现：

```text
ntdll.so!NtCallbackReturn + 0x404e4
  └── winevulkan.so + 0x9568
        └── win32u.so + 0x139d24 (__wine_get_vulkan_driver + 0x4)
              └── libc.so.6!pthread_once(&0x20102d440) + 0x8e1bc
                    └── win32u.so + 0x13a374 (vulkan_init_once + 0x5d4)
                          └── win32u.so + 0x13af04 (lazydrv_map_instance_extensions + 0x24)
                                ├── 【首次进入 0x20102d478】(Entry 1, word=0 -> 1)
                                └── libc.so.6!pthread_once(&0x20102d478, vulkan_driver_init)
                                      └── win32u.so + 0x13af90 (vulkan_driver_init + 0x30) (Entry 2 Frame 13) [仍在执行中]
                                            └── win32u.so 图像驱动加载与枚举 (Frames 12 ~ 7)
                                                  └── win32u.so + 0x3b914 (get_vulkan_gpus + 0x34) (Frame 6)
                                                        └── win32u.so + 0x3edc4 (d3dkmt_init_vulkan + 0x14) (Frame 3)
                                                              └── win32u.so + 0x13a520 (vulkan_instance_create + 0x160) (Frame 2)
                                                                    └── win32u.so + 0x14c57c (Frame 1)
                                                                          └── 【二次进入 0x20102d478】(Entry 2, word=1)
                                                                                └── 陷入 futex(0x20102d478, FUTEX_WAIT_PRIVATE, 1) [自死锁!]
```

### 4. 栈回溯终止原因与覆盖率

两次回溯的终止原因均为：`term_reason=fp_non_monotonic`。
- **具体现象**：在 Frame 6 (Entry 1) 及 Frame 22 (Entry 2) 处，`cur_fp=0x1000ffcb0`，而从栈帧读出的下一个 `next_fp=0x11fe28`，满足 `next_fp < cur_fp`。
- **终止归因与边界严谨性**：仅证明栈地址发生非单调跳变触发保护性终止。鉴于本测试为纯 ARM64 原生探针与 Wine 进程，未证实存在 FEX 二进制翻译介入；此处 `0x11fe28` 仅代表进程底层引导/系统调用分发栈区域，不能断言为 FEX/host 边界。
- **帧数计数语义核对**：`ONCE_BACKTRACE_SUMMARY` 中的 `total_frames`（6 和 22）统计的是沿 FP 链向上展开的层数（depth 1..N）；加上 depth=0 的叶子返回帧（LR 帧），实际输出的日志记录数为 7 条与 23 条，两者定义一致，不存在矛盾。
- **有效性评估**：回溯已完整覆盖自 NT 接口入口至 Vulkan/Win32u 驱动初始化核心逻辑的全部栈帧，上层闭环完整，无未覆盖关键盲区。

---

## 5. 多维评估结果 (v2 Framework)

| 评估维度 | 状态判定 | 依据支撑 |
| :--- | :---: | :--- |
| **1. 实验有效性 (Experimental Validity)** | **PASS** (true) | 模块加载确证，探针达 Step 3，动态探针 SHA 与模块 SHA 均严格核对。 |
| **2. 补丁路径覆盖 (Target Path Coverage)** | **PASS** (true) | `0x20102d478` 两次断点全命中，成功提取 30 帧带 SP/FP/LR/Module 的完整数据。 |
| **3. 递归自死锁判定 (Recursive Deadlock)** | **CONFIRMED** | 6 级上层活跃帧物理地址与 LR 绝对一致，word=1 同线程陷入 futex wait。 |
| **4. 目标成功达成 (Objective Success)** | **FAIL** (false) | `vkCreateInstance` 仍未返回，卡死于自锁点，超时 exit 124。 |

---

## 6. 根因剖析与后续架构建议

### 1. 根因剖析 (Architecture Root Cause)
本次确证的自死锁发生在**单 NOP 派生 Wine 环境**中，系原版第一重自锁被阻断后，执行流向后推进所暴露的次级循环依赖：
1. **原版循环**：原版 `vulkan_instance_create` 内部直接调用 `bl pthread_once(&0x20102d440, vulkan_init_once)`，在 `0x20102d440` 处即发生同线程重入自锁；
2. **派生版暴露的次级循环**：单 NOP 补丁（`0x13a3f4: NOP`）阻断了对 `0x20102d440` 的重入，使得 `vulkan_instance_create` 得以继续执行并调用 `lazydrv_map_instance_extensions`；
3. 在特定驱动后端和图形初始化路径下，`vulkan_init_once` 通过 `lazydrv_map_instance_extensions` 触发 `pthread_once(&0x20102d478, vulkan_driver_init)`，而 `vulkan_driver_init` 在枚举 GPU（`get_vulkan_gpus`）时通过 `d3dkmt_init_vulkan` 再次反向依赖了 `lazydrv_map_instance_extensions`；
4. **环境边界声明**：该次级自锁不能直接泛化为上游全部 Wine 版本的普遍固有缺陷，它是在单 NOP 破坏了原版早期拦截点后、驱动表处于半初始化状态下所呈现的派生环境特有行为。

### 2. 严正警告：严禁盲目加打第二个二进制 NOP
如果盲目在 `0x13af00` / `0x13af40` 将 `bl pthread_once` 再次打成 `NOP` 或采用假完成放行：
- 第二次调用虽然会被绕过，但此时第一次调用的 `vulkan_driver_init` 尚未给驱动函数表（`volatile_keys` / `0x22d460` 等）赋值完成；
- 既往假完成实验已证明此类盲目放行曾引发尾调用死循环自旋（528,990次）或面临未就绪表解引用（`ldr x1, [x8, #0x10]; br x1`）的重大未定义行为风险；
- 因此绝不能断言简单 NOP 可以作为修复方案，必须转入源码级断环。

### 3. 建议解决方案 (Path Forward)
必须回到 **Wine 源码级别** 实现状态机防重入（Re-entrancy Guard）：
- 在 `win32u` 内部维护一个线程局部的 `in_vulkan_driver_init` 递归计数器；
- 当检测到同线程在 `vulkan_driver_init` 执行期间重入 `lazydrv_map_instance_extensions` 时，提供安全的早期 stub 响应或延迟解析机制，而非再次触发未完成的 `pthread_once`。

---

### 交付物索引
- 栈帧比对数据：`logs/once478/frame_comparison.json`
- 运行收据：`logs/once478/run-1792773145/receipt.json`
- 分析报告：`reports/once478.md`
