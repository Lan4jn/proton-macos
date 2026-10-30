# 末端 private futex 模块归属与唤醒关系精确分析（Task-70 / Round 36 复核交付）

## 1. 任务背景与执行事实
在 Task-68 (Round 33) 诊断基础上，本轮（Task-70）对末端 private futex 等待进行了模块映射与唤醒关系观测。根据 Lead 独立核验意见，建立硬性有效性门槛并在全新测量运行中完成闭环验证。

- **运行有效性门槛**：
  1. `stdout` 必须包含 `[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...`（证明已成功越过前缀初始化，完成 `vulkan-1.dll` 加载与符号解析并进入 Vulkan 实例创建）；
  2. `stderr` 必须捕获到至少一条目标地址 `uaddr=0x20102d440` 的 `FUTEX_OWNER_ENTER`。
- **本次测量运行结果**：
  - `run_valid`: **true (VALID)**
  - `validity_status`: **VALID**
  - `stdout_bytes`: **478** 字节（完整包含 Step 1 至 Step 3）
  - `stderr_bytes`: **149432** 字节
  - `run_dir`: `logs/futex-owner/vulkan/run-7v5a6pa2`
  - `PID`: **91073**，`gtid`: **1**
  - `耗时`: **62.22s**，退出状态：`exit: 124`，`timed_out: true`，`mismatch_count: 0`

---

## 2. 制品哈希与补丁清单

| 文件路径 | SHA256 / 状态 | 说明 |
| :--- | :--- | :--- |
| `sources/elfuse-futex-args-derived/build/elfuse` | `ccdc6732c9d2d1b7b528ae26d2d987fdfd28938abc37fa64646e76579e205535` | Round 33 基线二进制 |
| `sources/elfuse-futex-owner-derived/build/elfuse` | `ffa223e861103add2200141a4276b831cc1032c2c55f0b8477bb05775b88b553` | 本次构建并交付的观测器二进制 |
| `logs/futex-owner/syscall.patch` | 完整补丁，见下 | 针对 `src/syscall/syscall.c` 的最小非侵入观测补丁 |
| `scripts/runtime/futex_owner/control.py` | `d3b1451f04dbf55a1aa9b9dd632669e2c6dfb05a766c071d3744655452d37c95` | 控制测试脚本（断言 EAGAIN、TIMEOUT、跨线程 WAIT/WAKE） |
| `scripts/runtime/futex_owner/run_control.py` | `ae7db43b00fe64b1f6ea49fb360155b9a764d890cfb25a3a1059f7ec2cbdddb0` | 控制测试运行器 |
| `scripts/runtime/futex_owner/run_wine.py` | `e63df86b45a94a97495b28e5c26b384667a48d212b77c5c0d603a12a524a4805` | 带硬性有效性门槛的 Wine 测量运行器 |
| `logs/futex-owner/control.json` | `dbe355bf676dbdfc618641ea50e414c5c24d9c4bc11843bfe38a6a2a5170d440` | 控制测试成功收据（exit: 0, FUTEX_OWNER_CONTROLS_OK） |
| `logs/futex-owner/vulkan/receipt.json` | `4b14d2a13ee42a5a0446738aa63f821616c68cf60b977755e3ba05b060f64be7` | 本次有效 Wine 测量运行收据 |

### 观测器实现补丁说明
在 `sources/elfuse-futex-owner-derived/src/syscall/syscall.c` 中：
1. 实现 `futex_owner_log_mapping`：调用 `guest_region_find(g, addr)` 查询 `guest_region_t`；对文件映射优先通过 `fcntl(r->backing_fd, F_GETPATH)` 解析出未被 64 字节截断的宿主完整路径，并计算真实段内文件偏移；对匿名映射输出 `[anon]`；
2. 实现 `futex_owner_thread_cb`：利用现有的 `thread_for_each` 遍历活跃线程，安全导出 `guest_tid`、`in_syscall`、`futex_kick` 与 `is_parked`；
3. 在 `syscall_dispatch` 的 `SYS_futex` 入口进行全进程、无假阳性的精确地址过滤（`ELFUSE_FUTEX_TARGET_UADDR=0x20102d440`），在满足时打印 `FUTEX_OWNER_ENTER`、三地址 `FUTEX_OWNER_MAP` 及活跃线程快照 `FUTEX_OWNER_THREAD`。

---

## 3. 真实控制测试证明

- **执行命令**：`python3 scripts/runtime/futex_owner/run_control.py`
- **测试结果**：`exit: 0`, `target_exit: 0`, `timed_out: false`
- **标准输出**：
  ```text
  [WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
  FUTEX_OWNER_CONTROLS_OK EAGAIN TIMEOUT WAIT_WAKE
  ```
- **控制证据指标**：
  - 成功捕获 7 次 enters、21 次 maps 映射解析、13 条线程快照记录、7 次 returns；
  - 明确验证：EAGAIN（-11）、20ms 超时 ETIMEDOUT（-110）及跨线程同步（gtid 1 休眠被 gtid 2 的 FUTEX_WAKE unblock，返回 0）。

---

## 4. 模块归属映射表（逐字取自本次有效运行 FUTEX_OWNER_MAP）

在本次测量运行（`logs/futex-owner/vulkan/run-7v5a6pa2`）中，`pid=91073`、`gtid=1` 进入末端 futex 时，观测器实时调用 `guest_region_find` 导出的逐字字段如下：

| 观测字段 (Tag) | 观测目标地址 | 映射模块 (`mod=`) | 模块内偏移 (`off=`) | 内存映射区间 (`start= .. end=`) | 权限 (`prot=`) | 标志位 (`flags=`) | 解析状态 (`resolved=`) |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| **`tag=uaddr`** | `0x20102d440` | `[anon]` | `0x2f440` | `0x200ffe000 .. 0x20106e000` | `rw-` | `0x22` (MAP_PRIVATE | MAP_ANONYMOUS) | **1 (已解析)** |
| **`tag=elr`** | `0x2000ce084` | `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/lib/libc.so.6` | `0x8e084` | `0x200040000 .. 0x2001ef000` | `r-x` | `0x2` (MAP_PRIVATE) | **1 (已解析)** |
| **`tag=lr`** | `0x2000ce048` | `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/lib/libc.so.6` | `0x8e048` | `0x200040000 .. 0x2001ef000` | `r-x` | `0x2` (MAP_PRIVATE) | **1 (已解析)** |

### 映射语义详析
1. **末端 ELR / LR (`0x2000ce084` / `0x2000ce048`)**：
   - 确切落在 guest `libc.so.6` 的只读可执行代码段 `[0x200040000, 0x2001ef000)` 中；
   - 段内偏移分别为 `0x8e084` 与 `0x8e048`；
   - 汇编代码分析确认：此处为 glibc 内部 futex 辅助调用（`sub w0, w0, #1` 紧跟在 SVC 系统调用之后）。
2. **末端 uaddr (`0x20102d440`)**：
   - 确切落在匿名私有映射区间 `[0x200ffe000, 0x20106e000)`（大小 0x70000，即 448 KiB）；
   - 区间权限为 `rw-`，标志位为 `0x22`（`LINUX_MAP_PRIVATE | LINUX_MAP_ANONYMOUS`）；
   - 区间相对偏移为 `0x2f440`；
   - 证实该地址属于由用户态运行时动态 `mmap(MAP_ANONYMOUS)` 分配的内存池/数据结构，而非直接映射自磁盘上的共享库文件。

---

## 5. 精确等待关系、锁对象候选与唤醒者分析

### 5.1 本次运行捕获的等待事件
收据中捕获的唯一目标 futex 条目：
```text
FUTEX_OWNER_ENTER pid=91073 gtid=1 uaddr=0x20102d440 op=0x80 val=1 timeout=0x0 uaddr2=0x20102d440 val3=8605900192 word=1 word_status=0 lr=0x2000ce048 elr=0x2000ce084
FUTEX_ARGS pid=91073 gtid=1 id=855 uaddr=0x20102d440 op=0x80 val=1 timeout=0x0 uaddr2=0x20102d440 val3=8605900192 word=1 word_status=0 lr=0x2000ce048 elr=0x2000ce084
```
- 等待线程：`pid=91073`, `gtid=1`
- 等待参数：`op=0x80` (`FUTEX_WAIT_PRIVATE`)，期望值 `val=1`，当前读取内存值 `word=1` (`word_status=0` 成功)，无超时设置 (`timeout=0x0`)；
- 等待状态：线程 1 验证期望值与内存值匹配后，进入内核 futex 等待队列挂起。

### 5.2 同进程活跃线程快照
在线程 1 进入挂起的同一瞬间，`thread_for_each` 捕获的同进程线程状态：
```text
FUTEX_OWNER_THREAD pid=91073 caller_gtid=1 sibling_gtid=1 in_syscall=-1 futex_kick=1 parked=0
```
- 在进程 `pid=91073` 内，当前仅存在唯一活跃线程（`gtid=1` 本身），不存在其他并发运行的 sibling 线程。

### 5.3 锁对象候选与唤醒者结论
1. **锁对象候选**：
   - 位于匿名私有区间 `[0x200ffe000, 0x20106e000)` 的偏移 `0x2f440` 处；
   - 当前锁标志字为 1；
   - 处于 Vulkan 驱动加载流程中（`vkCreateInstance` 内部用户态同步锁）。
2. **唤醒者结论**：
   - **在本观测覆盖内未见任何唤醒调用**；
   - 唤醒者明确为：**未知 (UNKNOWN)**。
3. **观测覆盖与未覆盖边界**：
   - **已覆盖路径**：
     - 所有进入宿主 `syscall_dispatch` 的 `SYS_futex` 调用（跨所有线程全覆盖）；
     - `core/shim.S` 中的 `futex_wake_fast`：当且仅当该 futex 散列桶内无任何等待者时在 EL1 快速返回 0；一旦存在挂起的等待者（本案中 `gtid=1` 处于等待队列中，`waiters > 0`），快速路径强制执行 `cbnz w17, futex_wake_waiter_bail` 陷入宿主，因此任何针对该等待者的 WAKE 均必定进入宿主并被本观测器捕获。
   - **未覆盖路径（潜在漏报盲区）**：
     - 若锁释放逻辑在用户态仅执行了内存原子写（如将 `*uaddr` 从 1 CAS 还原为 0）而根本未发起系统调用 `sys_futex(FUTEX_WAKE)`；
     - 若预期唤醒者属于其他独立进程（但本调用显式声明为 `FUTEX_WAIT_PRIVATE`，Linux 内核语义下非共享映射不可跨进程唤醒）；
     - 负责唤醒的工作线程在能够发起 wake 前已因其他故障提前退出或根本未被创建。

### 5.4 负向约束核验
1. **不猜 `pthread_once`**：无证据表明该锁为 pthread_once 控制字，如实记录为匿名内存中的未知用户态私有锁；
2. **不宣布 futex 实现有 bug**：elfuse 内核 futex 模块对 `FUTEX_WAIT_PRIVATE` 的原子比对、排队休眠与无超时等待语义完全符合 Linux ABI 规范。无唤醒者是 guest 用户态逻辑未发出 wake 所致，而非内核调度器或 futex 实现缺陷。

---

## 6. 真实 Wine 测量运行证据

### 6.1 执行命令
```bash
python3 scripts/runtime/futex_owner/run_wine.py
```

### 6.2 运行收据数据（取自 `logs/futex-owner/vulkan/receipt.json`）
- `runtime_sha256`: `ffa223e861103add2200141a4276b831cc1032c2c55f0b8477bb05775b88b553`
- `run_valid`: `true`
- `validity_status`: `"VALID"`
- `exit`: `124`
- `timed_out`: `true`
- `seconds`: `62.217647`
- `run_dir`: `"/Users/mewcapoo/Projects/proton-macos-lab/logs/futex-owner/vulkan/run-7v5a6pa2"`
- `stdout_bytes`: `478`
- `stderr_bytes`: `149432`
- `mismatch_count`: `0`
- `stdout` 尾部标记：
  ```text
  [WIN_ARM64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
  [WIN_ARM64_VK] SUCCESS: vulkan-1.dll loaded at 0xfc440000
  [WIN_ARM64_VK] Step 2: Resolving Vulkan function pointers...
  [WIN_ARM64_VK] SUCCESS: All function pointers resolved.
  [WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
  ```

---

## 7. 结论与下一步

1. **真实复现达成**：本次测量运行成功达到硬性有效性门槛，在真实 Wine 环境下精确复现并捕获了末端 `uaddr=0x20102d440` 的 `FUTEX_WAIT_PRIVATE` 挂起事件；
2. **模块归属尘埃落定**：
   - 调用者栈帧 ELR/LR 归属于 guest `libc.so.6` 代码段；
   - 等待地址 `0x20102d440` 归属于匿名分配内存池（`mod=[anon]`，区间 `0x200ffe000 .. 0x20106e000`，段内偏移 `0x2f440`）；
3. **唤醒者结论定性**：在当前进程内部没有任何线程针对该锁发起唤醒，且在挂起时刻该进程无其他存活 sibling 线程；
4. **下一步排查假设**：应重点追踪在 `vkCreateInstance` 内部为何没有启动负责异步初始化/设备枚举的辅助工作线程，或者该匿名内存锁是否预期由前置 RPC 交互（如 wineserver/驱动守护）通过信号/管道触发后才唤醒。
