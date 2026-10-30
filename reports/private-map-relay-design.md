# 私有映射会话中继架构设计方案 (Task-103)

**设计员**：futex-owner-r36 (执行员)  
**性质声明**：**本报告仅交付可实现的技术方案设计（ARCHITECTURAL DESIGN ONLY），未修改 elfuse 源码，未落地生产实现，严禁宣称或表述为已修复。**  
**关联任务**：Task-103（把决策报告里“会话中继”建议做成可实现设计，不改 elfuse 内存层）  
**前序依据**：
- reports/private-cow.md（Task-87：Red-First 实测基线留证）
- reports/private-cow-status.md（Task-88：门禁回写安全风险审计）
- reports/private-cow-decision.md（Task-98：私有映射决策评估报告）
- reports/FINAL.md（Round 37-38 终态汇总）

---

## 一、 问题边界与 Wine 真实场景的失败模式分析

### 1. Wine 场景真实需要的语义边界
依据本 lab 前序各轮（Round 11、16、18、19、58）对 Wine 源码（server/mapping.c 与 dlls/ntdll/unix/virtual.c）及实际运行捕获的物理事实：
- **目标对象**：Wine 只读会话段（Session Section，用于 winstation、desktop 及全局会话定位器）；
- **映射参数**：PROT_READ | PROT_WRITE，MAP_PRIVATE（非共享），fd >= 0，偏移 0，长度 0x144000（1,327,104 字节），底层文件为未链接的临时文件（st_nlink == 0，且宿主打开模式为 O_RDWR）；
- **Wine 架构核心诉求**：
  WineServer 持有该会话段的 MAP_SHARED 写入端并负责持续发布全局会话状态变更；Wine 客户端进程（如 explorer.exe、vk_enum_arm64.exe）以 MAP_PRIVATE 打开映射。
  **Wine 真实唯一依赖的强语义是【语义 (a)：未写页必须能感知并反映外部文件的后续修改】**。Wine 客户端在绝大多数生命周期内对该 session 内存段只进行只读消费（解析 session object id）；即使客户端偶尔因本地结构体初始化对某些私有局部变量发生写入，也必须满足**【语义 (b)：本地写入独立隔离】**和**【语义 (c)：绝不回写物理文件破坏服务端状态】**。

### 2. 现有两种做法各自破坏了什么？

| 做法 | 实现机理 | 破坏的语义与工程危害 | 对应实测证据 (收据退出码) |
| :--- | :--- | :--- | :--- |
| **做法一：无门禁纯净基线 (现状默认)** | src/syscall/mem.c:3595 走 pread 静态全量快照，一次性拷入匿名内存 | **彻底破坏【语义 (a)】**：映射瞬间即与底层文件完全脱钩。WineServer 在后台写入的任何新会话数据，客户端内存完全不可见（始终停留于快照初值）。导致客户端直接因会话 ID 不匹配而报错或死锁挂起。 | logs/private-cow/red_baseline_summary.json<br>退出码 **exit = 1**<br>报错：[TEST_A_FAIL] Live file modification INVISIBLE: got 0x10 (expected 0xAA) |
| **做法二：开启诊断门禁 (ELFUSE_DIAG_SESSION_SHARED=1)** | src/syscall/mem.c:2909 强行将 MAP_PRIVATE 改写为 MAP_SHARED 走宿主文件覆盖层 | **彻底摧毁【语义 (b)】与【语义 (c)】**：<br>1. **破坏 COW 隔离**：底层文件的后续写入会直接冲刷掉 guest 本地已写入的内存数据；<br>2. **物理文件污染与篡改**：guest 的本地写入通过共享映射直接回写到底层物理文件，存在严重污染跨进程服务端数据的安全风险！ | logs/private-cow/diag/diag_comparison_summary.json<br>退出码 **exit = 6**<br>报错：[DIAG_TEST_B_FAIL] COW isolation BROKEN<br>[DIAG_TEST_C_FAIL] Guest write LEAKED to file: pread got 0x77 |

---

## 二、 会话中继机制架构设计 (The Session Relay Bridge)

为了在**不改动底层虚拟机 Stage-2 MMU 页表与异常处理机制**、且**绝对不回写底层物理文件**的前提下，同时满足语义 (a)、(b)、(c)，本方案设计了基于**用户空间代理的「会话中继协议桥」（Session Relay Bridge）**。

### 1. 核心设计原则
1. **单向活文件注入**：仅支持“文件修改 -> guest 内存”的单向中继同步，绝不建立“guest 内存 -> 底层文件”的反向写通道；
2. **页级脏标记与 COW 脱离**：为被中继的映射区间维护一张极小的页级状态位图（page_dirty_bitmap）。一旦检测到某一页被 guest 写入过，该页**永久脱离中继通道**，不再接受底层文件的后续刷新，从而原生达成写后 COW 隔离；
3. **内存绝对安全**：guest 映射本身依然保持为独立的**匿名物理内存（Slab 匿名页）**，任何内存写入都在匿名页上完成，从物理根源上杜绝了对底层文件的回写污染。

### 2. 详细时序与协议流程 (Flow & Protocol)

```text
1. 宿主创建 kqueue 监听 fd 变更事件 (EVFILT_VNODE / NOTE_WRITE)
2. mmap(MAP_PRIVATE) 分配目标区间匿名页，通过 pread 填充初始数据，dirty_bitmap 全清零 (0)
3. 外部进程 (WineServer) 向文件写入数据 (pwrite)
4. 宿主中继线程捕获变更通知，遍历 dirty_bitmap:
   - 若 dirty_bitmap[page] == 0: 调用 pread(fd, host_base+ipa, 4096) 刷新该页数据
   - 若 dirty_bitmap[page] == 1: 判定为已被 guest 私有改写，跳过刷新，保持 COW 隔离
5. Guest 虚拟机线程首次向某页写入数据:
   - 触发写标记，设置 dirty_bitmap[page] = 1 (脱离中继流)
6. 宿主外部再次向该页写入:
   - 中继检测到 dirty_bitmap == 1，跳过同步，Guest 内存始终保持自己的私有写入
7. Guest 无论如何写入，因底层宿主物理页为匿名映射，绝不回写物理文件 (从物理根源保证语义 c)
```

### 3. 具体实现组件与代码 Hook 点设计 (基于真实代码路径)

本方案不修改核心虚拟化 MMU，仅在现有系统调用分发层增加中继管理：

1. **中继跟踪结构定义**（置于 src/syscall/mem.h 或独立头文件）：
   ```c
   typedef struct {
       int host_fd;                  /* 监控的宿主文件句柄 */
       uint64_t guest_ipa;           /* 目标 guest 物理基址 */
       uint64_t length;              /* 映射长度 (如 0x144000) */
       off_t file_offset;            /* 文件偏移 */
       uint32_t page_count;          /* 页面总数 (length / 4096) */
       _Atomic uint8_t *dirty_pages; /* 1字节代表1页: 0=clean(同步中), 1=dirty(已脱离) */
       pthread_t watcher_thread;     /* 变更监听线程句柄 */
       _Atomic bool active;          /* 中继是否活跃 */
   } session_relay_t;
   ```
2. **Hook 点 1：映射建立截获 (src/syscall/mem.c -> sys_mmap)**：
   - 在 sys_mmap（第 2908 行替换现有门禁）：不再篡改 flags = MAP_SHARED，依然让其走安全的私有匿名内存分配与初始 pread；
   - 随后调用 session_relay_register(host_backing_fd, result_off, length, offset) 初始化中继句柄与 kqueue 监控。
3. **Hook 点 2：写检测与 COW 脱离截获机制辨析**：
   - **方式 A（影子副本逐页比对法，唯一可行方案）**：
     * **机制**：中继管理层必须在宿主内存保留一份“上次同步/基线内容”的影子缓冲区（Shadow Buffer，内存开销等于被映射区间大小）；
     * **开销与诱因量化**：
       以 Wine 典型的 session section 映射参数为例：`length = 0x144000`（1,327,104 字节 ≈ 1.29 MiB），按 4096 字节（4KB）分页，共计 **324 个物理页**（或按 Apple Silicon 16KB 页划分计 81 页）；
       影子缓冲区常驻开销为严格固定的 **1.29 MiB**；每次底层文件产生写事件触发同步时，宿主需对全区间进行 $O(N)$ 逐页比对（324 次 4KB 内存块 `memcmp`，内存吞吐仅 ~1.3 MB，耗时在微秒级 < 50 µs）；若某页 guest 内容与影子副本不一致，立即判定该页已被写入，原子设置 `dirty_pages[p] = 1` 并永久脱离同步流。
   - **方式 B（系统调用层写拦截）的不完备性与缺陷定性**：
     * **致命缺陷**：系统调用拦截（如在 `sys_write`, `sys_read` 等接口设防）**在原理上无法捕获 guest 直接通过汇编内存存储指令（如 ARM64 `str`, `stp`, `stxr`）对映射内存的直接写入**（例如 Win32 / PE 代码直接通过指针修改 session 数据结构）；
     * **架构结论**：方式 B 单独使用**绝对不满足语义 (b)**。若无 Stage-2 Write-Fault 硬件异常陷入机制支持，在用户态纯代理层**必须 100% 依赖方式 A（影子副本比对）**，严禁误导性地将方式 B 作为独立方案。
4. **Hook 点 3：映射销毁回收 (src/syscall/mem.c -> sys_munmap)**：
   - 当收到对该区间的 sys_munmap 时，调用 session_relay_unregister，优雅关闭 kqueue 监听句柄并销毁中继位图与 1.29 MiB 影子缓冲区。

### 4. TOCTOU 竞态危害分析、未缓解风险与缓解方案 (Time-Of-Check to Time-Of-Use)
在纯用户态中继设计中，必须直面检查时刻（Check）与使用时刻（Use）之间的时间窗口竞态：
- **TOCTOU 竞态发生场景**：
  中继监控线程在时间点 $T_1$ 扫描某页（如 Page 1），比对影子副本判定为 clean（未写），准备执行 `pread` 刷新；
  在 $T_1$ 到 $T_2$（实际 `pread` 写入客体物理页）这段极窄的微秒级窗口内，Guest 虚拟机线程恰好通过 `str` 指令向 Page 1 写入了数据；
  紧接着在 $T_2$，中继线程的 `pread` 强制覆写该页，**直接冲刷掉了 Guest 刚刚写入的数据**！
- **未缓解时的严重后果**：
  在 TOCTOU 竞态窗口下，**语义 (b)（写时复制隔离）会被瞬间击穿**，导致 Guest 本地私有写入意外丢失，引发严重的数据不一致或不可重现的随机崩溃。
- **缓解与防御设计方案**：
  1. **方案 1（复检与回滚机制，Double-Check & Rollback）**：
     中继线程在将读取的新数据写入前，先将读取的新文件数据缓存在临时页中；在短暂挂起目标 vCPU（调用既有的 `thread_quiesce` 安全停顿点）或获取读写锁后，再次检查该页是否依然为 clean；写入后立即更新影子缓冲区；
  2. **方案 2（内存版本原子计数器，Page Version Generation Counter）**：
     为每个页面维护一个 64 位版本戳，任何写入行为递增版本号；中继线程在 CAS 写入时若检测到版本变更则自动丢弃本次刷新。

### 5. 异常与失败处理 (Failure Handling)
- **kqueue / 句柄耗尽**：若宿主无法为中继分配 event 监听句柄，平滑降级为现有的 pread 静态快照模式，并向 stderr 输出警告日志，绝对不使进程崩溃；
- **文件长度截断 (Truncation)**：若底层文件被 ftruncate 缩短，超出部分停止同步并填充 0x00；
- **并发锁保护**：页面数据刷新采用单页原子写入或在 vCPU 短暂安全停顿点（Safe-point / Quiesce）执行，防止 guest 读出半页撕裂数据。

---

## 三、 三大技术路径全面对比表

| 评估维度 | 方案 A：受控白名单门禁 (保留但不默认开启) | 方案 B：Stage-2 Write-Fault 拦截器 (底层 MMU 纯真 COW) | 方案 C：会话中继协议桥 (本设计方案) |
| :--- | :--- | :--- | :--- |
| **实现层级** | 宿主系统调用层参数篡改 (mem.c) | 虚拟化引擎 MMU & 异常陷入层 (mmu.c / proc.c) | 宿主端文件事件中继与局部同步代理 |
| **代码改动规模** | **极小** (~30 行，已存在) | **极大** (预计 600-900 行核心 C+汇编) | **中等** (预计 180-250 行独立 C 代码) |
| **语义 (a) 活文件可见** | 伪造达成 (强转 MAP_SHARED 穿透) | 仍受平台限制 (macOS XNU 不反向失效) | **真正达成** (事件驱动主动预读刷新) |
| **语义 (b) 写后 COW 隔离** | **彻底破坏** (写入被文件冲刷) | **完全支持** (Page-Fault 动态物理页分裂) | **完全支持** (页级脏位图主动脱离通道) |
| **语义 (c) 绝不回写文件** | **彻底破坏** (物理文件被回写篡改) | **完全支持** (写入始终停留在副本页) | **完全支持** (映射本身为匿名页，永不回写) |
| **全局回归风险面** | 局限于特定白名单参数；对普通应用无破坏 | **极高** (动摇已全绿的 Futex、信号栈、MMU) | **极低** (仅作用于特定 session section，完全解耦) |
| **适用场景** | 仅限特定封闭沙箱内的排错诊断 | 工业级通用 Linux OS 模拟仿真 | **针对 Wine 会话机制的轻量免侵入最优解** |

---

## 四、 验收标准与测试映射 (Acceptance Mapping)

直接复用既有的 scripts/runtime/private_cow 测试套件作为客观验收依据，在中继方案落地后的转绿判据映射如下：

1. **测试用例 1：scripts/runtime/private_cow/test_private_cow**
   - **语义目标**：验证通用 MAP_PRIVATE 映射的活文件可见性、COW 隔离与防回写；
   - **转绿判据**：
     - [TEST_A_PASS] Live file modification visible: got 0xAA（中继线程成功同步）；
     - [TEST_B_PASS] COW isolation intact: guest sees 0x55（Page 1 脏标记脱离，未被 0xBB 冲刷）；
     - [TEST_C_PASS] File not modified: pread got 0x12（未回写物理文件）；
     - 进程退出码为 **exit: 0**（由当前基线的 exit: 1 转为 exit: 0）。
2. **测试用例 2：scripts/runtime/private_cow/test_diag_gate**
   - **语义目标**：验证精准匹配 length==0x144000、offset==0 的 Wine 会话段参数映射；
   - **转绿判据**：
     - 在 **不设置** ELFUSE_DIAG_SESSION_SHARED=1 门禁前提下：
     - [DIAG_TEST_A_PASS] Live file modification visible: 0xaa；
     - [DIAG_TEST_B_PASS] COW isolation intact: 0x55；
     - [DIAG_TEST_C_PASS] File not modified: pread got 0x10；
     - 进程退出码由破坏性门禁下的 **exit: 6** 彻底转为 **exit: 0**。
3. **不可达性边界声明**：
   若被映射文件并非由宿主进程通过标准文件系统修改，而是通过跨虚拟机裸共享内存直接改写，则基于文件 VNODE 监听的中继方案无法感知。Wine 场景中 WineServer 始终通过文件系统操作临时 session 文件，因而 Wine 场景完全处于本方案覆盖范围之内。

---

## 五、 总结与声明

1. **方案成熟度**：本设计在逻辑上彻底闭环了私有映射的“活文件更新可见”、“写后 COW 隔离”与“绝不污染底层文件”三者间的冲突，为未来移除临时诊断门禁提供了清晰的工程蓝图；
2. **严格守界**：**本报告仅作为架构设计方案交付（DESIGN ONLY）**，未修改当前任何 elfuse 源码或二进制，未更动既有测试基线，严禁在此阶段声称或表述为已修复。
