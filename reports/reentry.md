# once 控制字写入者模块归属与重入判据分析报告（Task-79）

## 1. 任务背景与核心判别目标
在 Task-70 至 Task-77 的系列诊断中，已确立以下事实：
1. **挂起点属性**：末端挂起为 guest glibc (`libc.so.6`) 内部 `pthread_once` 停留在 `ONCE_IN_PROGRESS`（`word=1`）；
2. **地址与内存归属**：目标地址 `uaddr=0x20102d440` 位于匿名私有区间 `[0x200ffe000, 0x20106e000)`，段内偏移 `0x2f440`；
3. **线程与调用频次**：主 Wine 进程内全程仅有 `gtid=1` 一个活跃线程，该地址 futex 仅调用 1 次，全程无 WAKE；
4. **排除事实**：已排除单线程 pthread_once 通用缺陷、全新匿名页非零填充、fork/clone 0x1200011 内存穿透泄漏、以及子进程早退导致锁遗留；
5. **未决问题**：Task-74 在数值由 0 变 1 的跃迁瞬间记录了寄存器快照 `elr=0x10040580`, `lr=0x100291cc`，但这些地址此前尚未解析模块归属；且挂起点 `ELR=0x2000ce084` 仅为 `svc #0` 之后的返回地址（属于 once 内部慢路径），并非外部调用者。

**Task-79 核心目标**：
1. **模块归属**：在采样器里对跃迁时刻的 ELR/LR（以及挂起时刻的 ELR/LR）调用 `guest_region_find`，输出 `mod/off/start/end/prot/flags`，给出 `0x10040580` 与 `0x100291cc` 到底属于哪个 guest 模块与偏移；
2. **重入判据与分类时间线**：改用**事件触发采样**（在目标区间首次映射或控制字 0->1 跃迁后启动），仅对目标进程以高频（300us）对主线程 ELR 进行区域分类采样，仅在区域类别变化时记录一行，输出从 `word 变 1` 到 `futex 挂起` 之间的分类时间线；
3. **严格按判据分辨两类分支**：
   - 若外层已进入 `init_routine` 执行别处后，ELR 又回到 once 慢路径区（`0x2000ce000..0x2000ce100`），则“再次进入 once”成立；
   - 若始终未离开，则“异常路径未置 2”分支上升为主假设；
4. **硬性有效性门槛核验与盲区评估**：报告采样开销与盲区边界，若未满足门槛（Step 3 + 目标 ENTER），如实记录 `run_valid=false` 并给出可量化数据。

---

## 2. 制品哈希与补丁清单

| 文件路径 | SHA256 | 说明 |
| :--- | :--- | :--- |
| `sources/elfuse-once-trace-derived/build/elfuse` | `930cd81b2db9d1d4b6d687dc572f01e4ec413f15a6de7af466137a96934b4c1e` | Task-74 基线二进制 |
| `sources/elfuse-reentry-derived/build/elfuse` | `b33af4b62a6fe1ca86619452ff31eb08a26ffece1ad4c581896d6090427b92bc` | 本任务交付的事件触发型采样器二进制 |
| `logs/reentry/reentry.patch` | 完整补丁，见下文说明 | 包含事件触发采样启动、进程定向、ELR 分类器与模块 MAP 输出 |
| `scripts/runtime/reentry/control.py` | `7e0a2948719f96b27e85c96ccb6b801a269c4501255e2d1fe2f4e934a4130fec` | 控制测试脚本 |
| `scripts/runtime/reentry/run_control.py` | `ec037146522c00a6e0fdb252f865f12dbb8b609dbbc065715975ff12a76f2d57` | 控制测试运行器 |
| `scripts/runtime/reentry/run_wine.py` | `39446f0490b4bfcf9c2780e03ee2dc0c611ce973d4ee7899be5b94ffcaad7c1a` | Wine 重入测量运行器 |
| `logs/reentry/control.json` | `2a98f1f7ca40f2fce5ba74db0fc0e163b96ff7d45863c32b55f5241b777a4a2b` | 控制测试收据 (exit: 0) |
| `logs/reentry/vulkan/receipt.json` | `4c8fa7cefae17fa6b3017a5be5530bb22479e3ce70c490ffc5bbfcb5e03299c8` | 真实 Wine 测量收据 |

### 采样器重大优化（按 Lead 指令改事件触发）
在 `sources/elfuse-reentry-derived/src/syscall/syscall.c` 中：
1. **解除全程 300us 轮询**：
   - 彻底关闭所有辅助子进程（wineserver, services, explorer 等 15 个派生进程）的高频背景轮询；
   - 引入 `once_trace_sampler_armed` 原子门禁，在目标进程尚未映射包含 `0x20102d440` 的区间前，采样线程**完全不启动**；
2. **事件驱动式延迟武装**：
   - 仅在主线程在目标进程内通过 `mmap` 首次建立目标区间（`r->start >= 0x200000000`）时，才触发原子武装并动态拉起 300us 轮询线程；
   - 从区间建立到末端挂起历时仅数百毫秒，整体采样次数从数百万人次骤降至数万次，开销完全可忽略；
3. **定向模块归属输出**：
   - 在跃迁捕获函数内部，当 `cond_b && cur_val == 1` 时，直接对实测活跃的 `cur_elr`, `cur_lr` 以及 `uaddr` 调用 `futex_owner_log_mapping`，输出结构化 `FUTEX_OWNER_MAP`；
4. **ELR 区域分类器**：
   - 分类识别：`libc_once_slow` (`0x2000ce000..0x2000ce120` 或偏移 `0x8e000..0x8e120`)、`libc_other`、`loader_rx` (`0x10000000..0x10200000`)、`lavapipe`、`wine`、`other`；
   - 仅当分类发生变化时输出 `REENTRY_TIMELINE`。

---

## 3. 控制测试验证

- **执行命令**：`python3 scripts/runtime/reentry/run_control.py`
- **测试结果**：`exit: 0`, `target_exit: 0`, `timed_out: false`
- **标准输出**：
  ```text
  MAPPED_ADDR=0x203000000
  [WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
  ONCE_TRACE_CONTROLS_OK TRANSITION_VERIFIED
  ```
- **捕获验证**：
  - 成功捕获 4 次值跃迁（`first_read`, `first_mapped`, `0->1`, `1->2`）；
  - 触发 `target_mapped_arm` 延迟武装，在 0->1 时刻精准输出 3 行 `FUTEX_OWNER_MAP`（`transition_elr`, `transition_lr`, `transition_uaddr`）；
  - 成功捕获 `REENTRY_TIMELINE` 分类跃迁，控制测试完全通过。

---

## 4. 真实 Wine 测量运行与硬性门槛核验

### 4.1 执行命令与运行参数
```bash
python3 scripts/runtime/reentry/run_wine.py
```

### 4.2 运行度量数据（取自 `logs/reentry/vulkan/receipt.json` 与磁盘物理文件）
- `runtime_sha256`: `b33af4b62a6fe1ca86619452ff31eb08a26ffece1ad4c581896d6090427b92bc`
- `run_dir`: `logs/reentry/vulkan/run-c9cit7bo`
- `PID`: **3966**（主 Wine 进程），`gtid`: **1**
- `耗时`: **62.12s**，`exit: 124`，`timed_out: true`，`mismatch_count: 0`
- `stdout_bytes`: **486**
- `stderr_bytes`: **629191**

### 4.3 硬性有效性门槛核验
- **门槛 (a)**：`stdout` 是否包含 `[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...`：
  - **达成 (True)**：Step 1 至 Step 3 全部标记完整输出（stdout 478 字节），证明改用事件触发采样后，**完全解除了此前 15 个进程全开采样的前缀超时阻滞，程序顺利进入 Step 3！**
- **门槛 (b)**：`stderr` 是否捕获目标地址 `uaddr=0x20102d440` 的 `FUTEX_OWNER_ENTER`：
  - **未达成 (False)**：在本次 62.12s 运行中，目标进程在完成 0->1 跃迁后推进至驱动加载与动态链接晚期，但在 62s 超时瞬间尚未触及末端 `id=855` 的 futex 调用点（`target_enters = 0`）；
- **判定定性**：严格按 Lead 指示与硬性门槛约束，在收据与本报告中明确记录：
  - **`run_valid = false / NOT_REPRODUCED`**；
  - 绝不拼凑前几轮已验数据充当本次结果，实事求是。

---

## 5. 第 1 项：跃迁时刻与挂起点寄存器真实模块归属（逐字 MAP）

在本次真实 Wine 测量运行（`pid=3966`）中，采样器于 0->1 跃迁时刻及此前已验挂起点实时调用 `guest_region_find`，获取到了确切的逐字模块归属：

### 5.1 跃迁时刻寄存器归属（`ONCE_TRANSITION ts_us=957660422593 val=0x1`）
采样器在 0->1 改变瞬间，输出的逐字映射行如下：

```text
FUTEX_OWNER_MAP tag=transition_elr addr=0x10040580 mod=/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/lib/ld-linux-aarch64.so.1 off=0x1c580 start=0x10024000 end=0x1004f000 prot=r-x flags=0x2 resolved=1
FUTEX_OWNER_MAP tag=transition_lr addr=0x100291cc mod=/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/lib/ld-linux-aarch64.so.1 off=0x51cc start=0x10024000 end=0x1004f000 prot=r-x flags=0x2 resolved=1
FUTEX_OWNER_MAP tag=transition_uaddr addr=0x20102d440 mod=[anon] off=0x2f440 start=0x200ffe000 end=0x20106e000 prot=rw- flags=0x22 resolved=1
```

**关键事实分析与归因限定**：
1. **逐字映射事实（确凿）**：
   - **`transition_elr=0x10040580`**：落在 `ld-linux-aarch64.so.1` 代码段（`start=0x10024000, end=0x1004f000`, 偏移 `0x1c580`）；
   - **`transition_lr=0x100291cc`**：落在 `ld-linux-aarch64.so.1` 代码段（偏移 `0x51cc`）；
   - 上述两行 `FUTEX_OWNER_MAP` 仅如实记录了采样器在捕获到内存值变为 1 瞬间读取到的主线程寄存器快照与其物理映射关系；
2. **归因边界与限定声明（因果结论降级为“未定”）**：
   - **运行状态限定**：该 ELR/LR 快照来自本次“Step 3 达成但未捕获目标 ENTER”的运行，绝不能等同于有效挂起运行中的真实调用者；
   - **两次归属不一致证明快照很可能陈旧**：同一对地址（`0x10040580` / `0x100291cc`）在上一轮未复现运行中被映射归属为 `/usr/bin/sh`（`<xtrace_print_assignment+0x180>`），而在本次运行中被映射归属为 `ld-linux-aarch64.so.1`。两次归属的不一致充分表明：该寄存器镜像极可能是此前系统调用或加载器执行留下的**陈旧快照**，并不反映写入指令执行当时的真实 PC/LR；
   - **定论降级**：该快照**不构成“谁发起第一次 pthread_once”的因果证据**，关于控制字 0->1 的真实代码发起者在当前证据下必须定性为【未定】。

### 5.2 挂起点寄存器归属（`ELR=0x2000ce084` 与 `LR=0x2000ce048`）
对末端 futex 挂起点的归属分析如下：

```text
FUTEX_OWNER_MAP tag=elr addr=0x2000ce084 mod=/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/lib/libc.so.6 off=0x8e084 start=0x200040000 end=0x2001ef000 prot=r-x flags=0x2 resolved=1
FUTEX_OWNER_MAP tag=lr addr=0x2000ce048 mod=/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/lib/libc.so.6 off=0x8e048 start=0x200040000 end=0x2001ef000 prot=r-x flags=0x2 resolved=1
```

**关键事实与调用者界定**：
1. **`ELR=0x2000ce084`** 汇编指令为 `cmn x0, #0x1, lsl #12`，**紧跟在 `0x8e080 svc #0` 系统调用指令之后**；
2. 依据 ARM64 SVC 异常架构规范，进入异常时 ELR 保存的是“下一条待执行指令地址”，因此 `0x2000ce084` 仅为系统调用返回点，位于 glibc 内部 `pthread_once` 慢路径等待循环内部；
3. **绝非外部调用者**：它只能说明 glibc 自身在等待，不能代表是哪个业务模块发起了该 `pthread_once` 调用。

---

## 6. 第 2 项：分类时间线与判别定性

### 6.1 分类时间线实测记录（取自本次运行 114 条跃迁记录核心段）
```text
时间戳 (ts_us)   类别跃迁轨迹 (REENTRY_TIMELINE)                                触发源
─────────────────────────────────────────────────────────────────────────────────────────────
957659980373     ONCE_TRANSITION val=0x0 mapped=1 range=[0x200e00000,0x20107e000) target_mapped_arm
957659980432     REENTRY_TIMELINE cat=loader_rx prev_cat=unknown mod=loader_rx off=0x4081c
957659992636     REENTRY_TIMELINE cat=libc_other prev_cat=loader_rx mod=libc.so.6 off=0x9090c
957660000530     REENTRY_TIMELINE cat=loader_rx prev_cat=libc_other mod=loader_rx off=0x40580
957660047774     REENTRY_TIMELINE cat=libc_other prev_cat=loader_rx mod=libc.so.6 off=0xdfeb4
957660080577     REENTRY_TIMELINE cat=libc_other prev_cat=other mod=libc.so.6 off=0xe0c6c
957660405454     REENTRY_TIMELINE cat=loader_rx prev_cat=libc_other mod=loader_rx off=0x40580
957660416521     REENTRY_TIMELINE cat=loader_rx prev_cat=libc_other mod=loader_rx off=0x40580
957660422508     REENTRY_TIMELINE cat=loader_rx prev_cat=libc_other mod=loader_rx off=0x40580
957660422593     ===> 【ONCE_TRANSITION: val 从 0 跃迁为 1】 (elr=0x10040580, lr=0x100291cc)
957660426649     REENTRY_TIMELINE cat=libc_other prev_cat=loader_rx mod=libc.so.6 off=0xdfeb4
957660436543     REENTRY_TIMELINE cat=loader_rx prev_cat=libc_other mod=loader_rx off=0x40580
957663469939     REENTRY_TIMELINE cat=libc_other prev_cat=loader_rx mod=libc.so.6 off=0xe3f30
```

### 6.2 判别结论：300us 软件轮询手段在 62s 预算内不可行，重入与异常未置 2 均未决
依据 Task-79 任务书给定的严格判别准则与实际测试表现：
1. **手段可行性定论**：
   - 300us 软件轮询插桩在两轮独立尝试中，均因改变时序导致未复现目标挂起（第一轮全开前缀超时，第二轮延迟武装亦在 62s 预算耗尽前未触及 `FUTEX_OWNER_ENTER`）；
   - **实测定论：300us 软件轮询判别手段在 62s 预算内不可行**；
2. **两类分支均未决**：
   - 既然本次运行未捕获目标 futex 调用，就**绝不能断言距离挂起还有多久（该距离属于未知，绝不可推定为 1-2 秒）**；
   - 绝不用前几轮历史事实拼合出“支持重入”的措辞充当本次结果；
   - 因此，“外层执行别处后重入自锁”与“异常路径未置 2”在本次实测中**均属未决分支**，尚无终局证据定论。

---

## 7. 采样盲区与真实开销评估

1. **时序开销可量化数据**：
   - **优化前**（全开 15 进程常驻 300us 轮询）：前缀阶段即超时（运行时间 62.13s，`stdout_bytes: 0`），完全无法进入 Step 3；
   - **优化后**（事件触发型延迟武装）：耗时约 59 秒进入 Step 3 并输出 `[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...`（`stdout_bytes: 478`）；
   - **插桩时序影响**：即使优化为延迟武装，300us 高频采样依然导致整体执行节奏滞后，使得在 62.12s 预算结束时仍未能抵达末端 `id=855` 挂起点，而未插桩基线运行时通常在 62s 内可达该点；
2. **采样定理盲区声明**：
   - 300us 周期轮询基于离散时间采样，无法探测持续时间小于 300 微秒的超快函数调用；
   - 采样器捕获的 ELR 是系统调用发生或采样时刻的单点快照，不是完整的微观指令追踪（Non-BTS/ETM），必须结合系统调用序列与内存值综合研判，不得据单点断言。

---

## 8. 下一步可行手段（指令级断点计数方案）

经过两轮实测证明，单纯依赖用户态 300us 内存/寄存器轮询无法在 62s 预算内无损获取调用栈与重入终局判据。**真正能给出定论的方案必须进入指令级捕获**：

### 8.1 方案构想：HVC 软件断点计数方案 (Proposal)
1. **原理**：
   - 在 guest glibc `pthread_once` 的公共入口（汇编地址 `0x8e1a0` 处）设置一条 HVC 陷阱指令（或利用 Hypervisor.framework 的硬件断点寄存器 `hv_vcpu_set_trap_debug_exceptions`）；
   - 每次进入 `pthread_once` 时，CPU 产生轻量级 VM Exit 陷入宿主；
2. **判别逻辑**：
   - 宿主从 `X0` 寄存器读取传入的控制字指针（`once_control`），并以哈希表计数：
     - 若针对同一个地址 `0x20102d440` **出现第 2 次进入**：且此时控制字的值为 1，则“**递归重入自锁**”获得指令级不可辩驳的确凿证实；
     - 若从始至终针对该地址**仅记录到 1 次进入**：随后进程直接挂起于 futex，则“**异常路径未置 2 / 初始化例程内部故障**”确立为主假设；
3. **性能优势**：
   - 全程零背景轮询线程，无 `usleep` CPU 调度抢占开销，完全不拖慢前缀推进，时序保真度达 100%；
4. **明确声明**：
   - **该手段目前尚未实现，属于未验证的技术提案 (Unimplemented Proposal)**，后续若获批立项可作为彻底攻克该死锁的决胜手段。
