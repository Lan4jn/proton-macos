# 正常私有文件映射与 Wine 会话一致性定位与评估报告 (Task-134 终审修订版)

**评估者**：x64-pipe-reviewer  
**核心结论与分级定性**：
1. **已证事实 (Established Facts)**：
   - **公平对比实测确证**：在与 Task-133 完全一致的环境（相同 prefix、`default_pfx_arm64`、`creation_sync_guard`、相同 `guest_env` 及 115 秒有界超时）下进行单一变量（Gate ON vs Gate OFF）严格对照测试：
     - **Gate ON**（`ELFUSE_DIAG_SESSION_SHARED=1`）：在 **44.93 秒** 顺利跑通 **Step 1 至 Step 5**，成功枚举物理设备 `count=1`（`llvmpipe`），正常退出（`exit=0, timed_out=false`）；
     - **Gate OFF**（未设置该环境变量）：在运行至 **Step 3 (`vkCreateInstance`)** 处完全停滞，连续 115 秒未能进入 Step 4，最终超时强杀（`exit=124, timed_out=true`），标准输出截断在 Step 3 调用前，生成 36,576 行系统日志与 12,835 次 Watchdog 快照；
   - **门禁破坏私写隔离与回写文件实测证伪（负对照验证）**：在增强版回归探针（`probe_cow_semantics` Part 2）中，对完全符合 `mem.c:2909` 触发条件（`length == 0x144000`、`st_nlink == 0`、`O_RDWR`、`MAP_PRIVATE`）的文件进行实测：
     - 在 Gate ON 状态下，`mem.c:2909` 打印 `DIAGNOSTIC_SHARED_ALIAS_NOT_ABI_FIX` 并强制将映射转为 `MAP_SHARED`；随后客户机对私有页面的写入（`0x77`）被直接回写到底层物理文件（`pread` 读出 `0x77` 破除隔离），且文件外部修改（`0xBB`）直接冲刷覆盖了客户机的私有写（`0x55`）（测试输出：`GATE_ANOMALY_RESULT: WRITE_LEAKAGE_AND_COW_CORRUPTION_CONFIRMED mask=0x3`）；
     - 在 Gate OFF 状态下，私有写完全隔离且不泄漏（`CLEAN_PRIVATE_ISOLATION_PRESERVED`）；
2. **高置信度推断 (Engineering Inferences)**：
   - 结合 Wine 源码 `dlls/ntdll/unix/virtual.c:2598` 的注释（Wine 显式记录：在 Linux 环境下将只读节视图映射为 `MAP_PRIVATE`，依赖 Linux 页面缓存使底层修改实时可见），推断 `0x144000` 映射对应于 Wine 会话与桌面共享节（winstation / session shared memory）；
   - 在 `elfuse` 未开门禁时，`MAP_PRIVATE` 仅使用静态 `pread` 快照（`copy_file_range_to_guest_pages`），使得子进程无法动态获取会话就绪信号，导致初始化握手超时；
   - **边界声明**：因本轮未对该 1.265MB 内存块执行逐字节的内部数据结构逆向，因果链定性为**高置信度工程推断**，严禁断言为 100% 绝对封闭证据；
3. **架构缺项与替代演进方案**：
   - **实测排除宿主私有文件映射覆盖**：经在 Apple Silicon Hypervisor 框架下实测与源码审计（`src/runtime/forkipc.c:1775`），macOS XNU 内核的 `MAP_PRIVATE` 内存无法与虚拟机 Stage-2 硬件映射协同实现写时复制（硬件写穿透绕过 Mach VM 缺页处理，导致 `HV_DENIED` 或状态错乱）；
   - **去除无依据断言**：删除所有“必须 Stage-2 fault + 600-900 行”的绝对化唯一架构断言；
   - **给出两项可行演进方案**：
     - **方案 1（受控只读中继 / 白名单映射代理）**：在宿主运行时仅对经过严密白名单验证的 unlinked 会话共享文件建立安全跨进程通道；
     - **方案 2（Wine `virtual.c` 非 Linux 映射分支适配 - 推荐）**：适配 Wine `virtual.c:2600`，对纯只读 section 采用 `MAP_SHARED` 配合 `PROT_READ`（写权限剥离，从根本上杜绝私写泄漏回物理文件），彻底摆脱对 Linux 专有 Page Cache 私有穿透假设的依赖。

---

## 1. 运行时映射实现与现有门禁机制审计 (Acceptance 1)

### 1.1 映射分流机制与源码定位
在 `sources/elfuse-once-panorama2-derived/src/syscall/mem.c` 中，`sys_mmap` 处理文件映射时存在两个完全分立的执行分支：
1. **`MAP_SHARED` 路径（行 3201 / 3567）**：
   - 触发条件：`(flags & LINUX_MAP_SHARED) && overlay_fd_writable(host_backing_fd)`；
   - 实现机制：调用 `hvf_apply_file_overlay`，在宿主端调用 `mmap(host_base + ipa, len, PROT_READ|PROT_WRITE, MAP_FIXED|MAP_SHARED, host_backing_fd, offset)`，随后通过 `hv_vm_map` 挂入 Stage-2 页表；
   - 语义特征：Guest 对该区域的写入直接作用于宿主内核页面缓存，底层物理文件实时被修改，且跨进程共享映射实时可见；
2. **`MAP_PRIVATE` 路径（行 3218 / 3585）**：
   - 触发条件：所有未置位 `MAP_SHARED` 的文件映射；
   - 实现机制：保留 GPA 挂接在匿名私有内存池（`host_base + gpa`），在分配时单次调用 `copy_file_range_to_guest_pages(g, result_off, host_backing_fd, offset, length)`（即通过 `pread` 静态复制数据进入匿名页）；
   - 语义特征：内存与底层文件在此刻彻底断开联系。后续任何针对底层文件的修改，Guest 内存均完全无感知。

### 1.2 现有门禁机制与伪修复剖析
在 `mem.c:2905-2928`，诊断开关代码如下：
```c
/* NOT AN ABI FIX: gated causal experiment sacrificing private-write isolation. */
if (getenv("ELFUSE_DIAG_SESSION_SHARED") && fd >= 0 &&
    length == 0x144000 && offset == 0 && prot == (LINUX_PROT_READ | LINUX_PROT_WRITE) &&
    (flags & LINUX_MAP_PRIVATE) && !(flags & LINUX_MAP_ANONYMOUS)) {
    ...
    flags = (flags & ~LINUX_MAP_PRIVATE) | LINUX_MAP_SHARED;
}
```
- 该门禁通过强制改写标志位将 `MAP_PRIVATE` 变为 `MAP_SHARED`；
- **危害**：破坏了私写隔离，客户机写入会直接穿透回物理文件，无法作为合规生产实现。

---

## 2. ARM64 Linux 映射回归探针实测 (Acceptance 2 & 3)

编写并编译了原生 AArch64 Linux ELF 探针 `scripts/runtime/cow_recovery/probe_cow_semantics.c`（包含 Part 1 通用语义与 Part 2 门禁条件负对照），并在 `elfuse` 容器内完成实测：

```text
=== PART 1: GENERAL MAP_PRIVATE / MAP_SHARED SEMANTICS ===
[1] Testing MAP_PRIVATE private write isolation...
  [PASS] Sibling MAP_PRIVATE untouched: got 0x11 (expected 0x11)
  [PASS] File not written back: pread got 0x11 (expected 0x11)
[2] Testing MAP_SHARED cross-process visibility...
  [PASS] MAP_SHARED writes back to file: pread got 0x88 (expected 0x88)
  [PASS] MAP_SHARED visible bidirectionally across fork child
[3] Observing file modification after MAP_PRIVATE (POSIX Unspecified)...
  [OBSERVE] Clean page read after file update: got 0x14 (original 0x14, updated 0xEE)
    -> Behavior: Snapshot pread behavior (permitted by POSIX.1-2017: 'unspecified')
[4] Testing MAP_FIXED partial remapping...
  [PASS] MAP_FIXED partial remapping correctly preserved surrounding pages
[5] Testing non-zero offset alignment...
  [PASS] Non-zero page-aligned offset mapping read correct bytes

=== PART 2: GATE-MATCHING 0x144000 UNLINKED FILE CONTROL ===
Gate file initialized: fd=3 size=0x144000 nlink=0
--- [Under Gate OFF (Clean)] ---
[GATE_TEST_1] Guest writes 0x77 to MAP_PRIVATE page 2...
  [PASS] Private write NOT leaked to file: pread got 0x10 (expected 0x10)
[GATE_TEST_2] Guest writes 0x55 to page 3, then file modified to 0xBB...
  [PASS] COW isolation intact: guest sees 0x55 (expected 0x55)
GATE_ANOMALY_RESULT: CLEAN_PRIVATE_ISOLATION_PRESERVED

--- [Under Gate ON (ELFUSE_DIAG_SESSION_SHARED=1)] ---
DIAGNOSTIC_SHARED_ALIAS_NOT_ABI_FIX pid=37025 dev=16777242 ino=77713 len=0x144000 old_flags=0x2
[GATE_TEST_1] Guest writes 0x77 to MAP_PRIVATE page 2...
  [ALERT] Gate triggered MAP_SHARED leak: pread got 0x77 (private write leaked to file!)
[GATE_TEST_2] Guest writes 0x55 to page 3, then file modified to 0xBB...
  [ALERT] Gate destroyed COW isolation: guest sees 0xBB (file overwrite clobbered private write 0x55!)
GATE_ANOMALY_RESULT: WRITE_LEAKAGE_AND_COW_CORRUPTION_CONFIRMED (mask=0x3)
```

### 2.1 映射语义与标准边界对照表
| 语义测试项 | 动作与时序 | Linux 内核实现机制 | POSIX 规范规定 | 当前 elfuse 实测表现 |
| :--- | :--- | :---: | :---: | :---: |
| **私写隔离** | 进程写私有映射，检查兄弟私有映射与文件 | 独立（COW 拷贝，不写回文件） | **必须保证隔离** | **PASS**（保持独立匿名页） |
| **共享穿透** | 进程写共享映射，跨 fork 读写 | 穿透可见，回写物理文件 | **必须保证共享与可见** | **PASS**（依托 host MAP_SHARED） |
| **活文件穿透** | 私有映射建立后，底层文件被外部 `pwrite` | 未写干净页可见新数据；脏页保留 | **明确未指定（Unspecified）** | **快照未穿透（维持初始值 0x14）** |
| **局部重映射** | `MAP_FIXED` 局部替换页面 | 精确覆盖目标页，邻页完好 | **必须保证** | **PASS**（精准替换无污染） |
| **偏移对齐** | `offset = 4096` 跨页映射 | 精确解析对应页偏移切片 | **必须保证** | **PASS**（数据读取准确） |

### 2.2 Linux vs POSIX 语义精确辨析 (Acceptance 6)
1. **POSIX.1-2017 规范**：
   对 `MAP_PRIVATE` 明确规定：*"It is unspecified whether modifications to the underlying object done after the MAP_PRIVATE mapping is established are visible through the MAP_PRIVATE mapping."*。因此，未穿透文件修改在 POSIX 层面属于完全合规的宽容行为；
2. **Linux 内核行为特性**：
   Linux 的穿透性来自其统一页面缓存（Unified Page Cache）设计。在客户机执行私有写入触发写时复制（COW）之前，PTE 直接指向文件缓存物理页；一旦发生写时复制，脏页与文件彻底解耦。若文件发生 `truncate` 缩小，访问超出文件范围的页面会在 Linux 上触发 `SIGBUS`；
3. **不可将未保证语义作为强断言**：
   Wine 依赖的是 Linux 内核专有特性，在纯 POSIX 兼容实现中该依赖本身存在兼容性摩擦。

---

## 3. 115 秒有界公平对照实测与失败分析 (Acceptance 1, 2, 5)

使用受控脚本 `scripts/runtime/cow_recovery/run_fair_gate_comparison.py`，在与 Task-133 完全相同的生产配置（相同 prefix、`default_pfx_arm64` 预装、`creation_sync_guard`、相同 `guest_env`、相同 patched win32u 库）下执行双向公平对照：

### 3.1 两路运行指标对照
| 比较维度 | 试验组 1: Gate ON (`ELFUSE_DIAG_SESSION_SHARED=1`) | 试验组 2: Gate OFF (`ELFUSE_DIAG_SESSION_SHARED` 未设置) |
| :--- | :---: | :---: |
| **执行超时上限** | 115.0 秒 | 115.0 秒 |
| **实际结算耗时** | **44.93 秒** (提前完成退出) | **115.0 秒** (超时挂死强杀) |
| **退出码 (Exit Code)** | **`0`** (`timed_out=false`) | **`124`** (`timed_out=true`) |
| **标准输出 Step 进展** | **Step 1 至 Step 5 全走通** | **截断在 Step 3 调用前** |
| **设备枚举结果** | `Physical device count: 1`, `llvmpipe` | **无任何物理设备输出** |
| **生成系统日志规模** | 正常执行日志 | **36,576 行**（高频轮询与 Watchdog 周期） |
| **Watchdog 快照次数** | 正常快照 | **12,835 次快照**（主线程卡在 Step 3） |

### 3.2 失败因果分层定性 (已证事实 vs 高置信度推断)
1. **已证事实 (Established Facts)**：
   - 在 115 秒的超长窗口下，Gate OFF 依然稳定死锁在 Step 3 `vkCreateInstance` 内部，完全排除了“30 秒时间不足以启动完成”的假象；
   - 在 Gate ON 下，`sys_mmap` 拦截到了 `0x144000` 大小、`st_nlink == 0` 的 unlinked 读写临时文件，并将其转为 `MAP_SHARED`；
2. **高置信度工程推断 (High-Confidence Inferences)**：
   - 根据 Wine 源码 `dlls/win32u/winstation.c` 与 `dlls/ntdll/unix/virtual.c:2598`，该 `0x144000` 映射是 Wine 用户桌面与会话共享节（winstation shared section）；
   - 在缺少动态缓存感知机制时，客户端进程读取静态快照，未能感知 wineserver 写入的会话状态更新，最终在内部同步点形成死锁挂起；
   - **边界声明**：因未对 1.265MB 数据块做逐字节结构体反查，该因果链保持为高置信度推断，不写为绝对封闭定论。

---

## 4. 架构机理探索与替代演进方案 (Acceptance 4)

### 4.1 宿主 `MAP_PRIVATE` 文件覆盖层为何在 HVF 下不可行
针对“能否直接通过宿主 `mmap(..., MAP_FIXED | MAP_PRIVATE, host_fd, ...)` 来让 macOS 内核处理写时复制”的技术探索：
1. **Stage-2 硬件映射穿透机制**：
   在 Apple Silicon Hypervisor 框架下，`hv_vm_map` 是将宿主虚拟地址（HVA）对应的物理页（HPA）固定映射到虚拟机二级页表（IPA -> HPA）；
2. **Mach VM 与 Stage-2 冲突**：
   macOS XNU 内核的写时复制是在 EL0/EL1 发生 CPU 内存写缺页时由 Mach VM 的 `vm_fault` 处理。但 vCPU 在客户机（EL0/EL1）执行写操作时，直接经由 ARM64 Stage-2 硬件地址转换，**完全绕过了宿主 macOS 内核的软件缺页处理链路**；
3. **源码与实测确证**：
   查阅 `src/runtime/forkipc.c:1775-1778` 记录的既有事实：*"The parent's own mapping cannot be flipped to MAP_PRIVATE here: hv_vm_map caches the host VA->PA mapping, and a MAP_FIXED remap invalidates it (the parent then reads stale memory and writev returns EFAULT)."*。因此，无法简单依托宿主内核实现透明 COW。

### 4.2 两项可行的演进替代方案 (Alternative Proposals)

#### 方案 1：运行时受控会话共享中继代理 (Host Session Relay Proxy)
- **原理**：在 `elfuse` 的 `sys_mmap` 中，不实施无差别的全局共享泛化，而是严格限定匹配签名：`st.st_nlink == 0` && `length == 0x144000` && `(access & O_ACCMODE) == O_RDWR`；仅将此唯一的 Wine 会话内部 IPC 临时文件接入共享覆盖层，其余常规磁盘文件 100% 保持严格私有隔离；
- **评价**：改动局限于 `elfuse` 内存分发层（仅数行判定强化），保持 Wine 原版无修改，但仍保留了该特定文件的写回行为。

#### 方案 2：Wine `virtual.c` 只读节映射适配 (推荐，彻底杜绝写泄漏)
- **原理**：查阅 `dlls/ntdll/unix/virtual.c:2598-2603`，Wine 源码原生存在跨平台分支：
  ```c
  #ifdef __linux__
      flags |= MAP_PRIVATE;
  #else
      flags |= MAP_SHARED;
      prot &= ~PROT_WRITE;
  #endif
  ```
  在非原生 Linux 内核虚拟化环境（如 elfuse 用户态仿真器）中，Wine 只需启用 `#else` 分支逻辑：对只读 section 采用 `MAP_SHARED` 并剥离写权限（`prot &= ~PROT_WRITE`）；
  - **安全性保证**：由于 `PROT_READ` 映射在硬件级别禁止写入，Guest 绝不可能向底层文件写回任何脏数据（Test C 天然 100% 满足，**绝对不会发生写泄漏**），同时又能实时观测到底层文件的修改（满足会话同步需求）；
- **取舍考量**：需要维护针对 Wine `virtual.c` 的微小补丁，但能以最高优雅度彻底达成“既能穿透会话更新、又绝不破坏私写安全”的双重目标。

---

## 5. 交付工件清单

1. **主报告**：`reports/cow-recovery.md`
2. **综合证据收据**：`logs/cow-recovery/recovery_evidence.json`
3. **回归探针结果（含负对照）**：`logs/cow-recovery/cow_semantics_probe_result.json`
4. **公平 115 秒对照记录**：
   - `logs/cow-recovery/fair_comparison/gate_on_result.json`（44.93s, exit 0, Step 1-5 通过）
   - `logs/cow-recovery/fair_comparison/gate_off/stdout.log`（卡死在 Step 3 前，超时 115s）
   - `logs/cow-recovery/gate_off_wine_result.json`
5. **AArch64 原生回归探针源码与二进制**：
   - 源码：`scripts/runtime/cow_recovery/probe_cow_semantics.c`
   - 编译产物：`scripts/runtime/cow_recovery/probe_cow_semantics`（AArch64 ELF 可执行文件）
6. **自动化执行脚本**：
   - `scripts/runtime/cow_recovery/run_cow_probe.py`
   - `scripts/runtime/cow_recovery/run_fair_gate_comparison.py`
   - `scripts/runtime/cow_recovery/reproduce_wine_gate_off.py`
   - `scripts/runtime/cow_recovery/assemble_recovery_evidence.py`
7. **派生运行时目录**：`sources/elfuse-cow-recovery-derived/`
