# 末端 Futex 调用点 libc 符号与匿名区间角色分析报告（Task-71 交付）

**分析员**：evidence-reviewer-r36  
**分析基准**：纯只读静态分析、不重跑 Wine、不改既有源码与收据、严禁无根据猜测  
**分析对象**：
- 上游实测收据：`reports/futex-owner.md`、`logs/futex-owner/vulkan/receipt.json`、`logs/futex-owner/vulkan/run-7v5a6pa2/stderr.log`
- 目标 libc 二进制：`fixtures/runtime/arch-case/usr/lib/libc.so.6`（glibc 2.43 稳定版，aarch64，大小 1853736 字节）
- 目标地址与偏移：
  - `ELR = 0x2000ce084`（段基址 `0x200040000`，段内偏移 `off = 0x8e084`）
  - `LR = 0x2000ce048`（段基址 `0x200040000`，段内偏移 `off = 0x8e048`）
  - `uaddr = 0x20102d440`（区间 `[0x200ffe000, 0x20106e000)`，大小 `0x70000`，段内偏移 `off = 0x2f440`）

---

## 一、 调用点符号定位与反汇编链条 (Libc Symbol & Disassembly Proof)

### 1.1 符号归属与外层入口
通过对 `libc.so.6` 进行符号表解析与文本段反汇编，确认偏移 `0x8e084` 与 `0x8e048` 所在函数区间的确切符号信息：

- **导出入口**：`0x8e1a0 <pthread_once@@GLIBC_2.34>`（同时别名为 `__pthread_once@GLIBC_2.17`、`call_once@@GLIBC_2.34` [0x92380 跳转至此]）
- **封闭函数实体**：`0x8dfc4 - 0x8e1a0`。该函数无独立公开符号（属于 glibc `nptl/pthread_once.c` 编译内联折叠的 `__pthread_once_slow` 静态函数实体）。
- **静态调用链**：
  ```text
  pthread_once (0x8e1a0) / call_once (0x92380)
    │
    ├── ldar  w2, [x0]                 ; 快速检查 once_control
    ├── tbz   w2, #1, 0x8e1b0          ; 若已完成 (bit 1 == 1, val == 2)，直接返回 0
    └── 0x8e1b8: bl 0x8dfc4            ; 未完成则调用 __pthread_once_slow (0x8dfc4)
  ```

### 1.2 关键反汇编片段与寄存器语义（逐指令核对）
反汇编源自 `objdump --disassemble --start-address=0x8dfc4 --stop-address=0x8e140`:

```arm64asm
;; -------------------------------------------------------------------------
;; __pthread_once_slow 慢速路径核心循环与 Futex 挂起逻辑
;; x0/x4: once_control 虚拟地址 (即 uaddr = 0x20102d440)
;; x1/x5: init_routine 回调函数指针
;; -------------------------------------------------------------------------

000000000008dfc4:
   8dfc4:  sub   sp, sp, #0x80
   8dfc8:  mov   x4, x0                ; 保存 once_control 地址到 x4
   8dfd4:  mov   x5, x1                ; 保存 init_routine 回调指针到 x5
   ...
   8dff0:  ldar  w3, [x4]              ; 加载 once_control 当前值
   8dff4:  tbz   w3, #1, 0x8e024       ; 若 bit 1 == 0 (未完成)，跳到 8e024 尝试竞争或等待
   ...                                 ; 若 bit 1 == 1 (已完成)，正常清理栈并退出返回 0

   ;; 尝试原子 CAS 抢占执行权
   8e024:  adrp  x0, 0x1c6000
   8e028:  mov   x2, x4                ; x2 = once_control 地址
   8e02c:  str   w3, [sp]              ; 记录当前期望值
   8e030:  ldr   x1, [x0, #0x4e0]
   8e034:  mov   w0, w3                ; w0 = expected
   8e038:  stp   x4, x5, [sp, #0x8]
   8e03c:  orr   w1, w1, #0x1          ; 试图将控制字设置为 1 (正在初始化)
   8e040:  str   w1, [sp, #0x1c]
   8e044:  bl    0x13cf80              ; 调用原子 CAS 辅助函数 (__atomic_compare_exchange)
   
   ;; LR = 0x2000ce048 对应的返回点：
   8e048:  ldr   w3, [sp]              ; LR 处：读取栈中先前保存的值
   8e04c:  ldp   x4, x5, [sp, #0x8]    ; 恢复 x4 (uaddr) 与 x5 (callback)
   8e050:  cmp   w0, w3                ; 比较 CAS 是否成功 (w0 为实际内存值)
   8e054:  mov   w3, w0
   8e058:  b.ne  0x8dff4               ; CAS 失败（被其他线程抢占），重新读取并重试
   8e05c:  tbz   w3, #0, 0x8e0c4       ; 若当前无其他线程占有 (bit 0 == 0)，跳转 8e0c4 执行回调
   
   ;; 若 bit 0 == 1，说明已有其他线程在执行初始化，本线程必须进入 Futex 等待：
   8e060:  ldr   w1, [sp, #0x1c]
   8e064:  cmp   w1, w0
   8e068:  b.ne  0x8e0c4
   8e06c:  mov   w2, w3                ; w2 = val = 1 (期望值)
   8e070:  mov   x0, x4                ; x0 = uaddr = 0x20102d440
   8e074:  mov   x1, #0x80             ; x1 = 128 (FUTEX_WAIT_PRIVATE)
   8e078:  mov   x3, #0x0              ; x3 = timeout = NULL
   8e07c:  mov   x8, #0x62             ; x8 = 98 (SYS_futex)
   8e080:  svc   #0                    ; 发起系统调用：SYS_futex(uaddr, FUTEX_WAIT_PRIVATE, 1, NULL)
   
   ;; ELR = 0x2000ce084 对应的返回点（系统调用中断陷出后的下一条指令）：
   8e084:  cmn   x0, #0x1, lsl #12     ; 检查返回值是否为负错误码
   8e088:  b.ls  0x8dff0               ; 成功醒来，重新回到 8dff0 读取 once_control 最新状态
   8e08c:  cmn   w0, #0xb              ; 检查是否为 EAGAIN (-11)
   8e090:  b.eq  0x8dff0               ; 若为 EAGAIN，说明值已改变，重新循环
   8e094:  cmn   w0, #0x4              ; 检查是否为 EINTR (-4)
   8e098:  b.eq  0x8dff0               ; 若被信号打断，重新循环
   8e09c:  ...                         ; 其他未知错误码触发 __libc_fatal("The futex facility...")
```

### 1.3 确凿判定与调用关系总结
1. **ELR（`0x2000ce084`）**：精确指向 `__pthread_once_slow` 内部系统调用指令 `svc #0`（`0x8e080`）的返回地址。系统调用入参完全对应：
   - `x0 = 0x20102d440`（`uaddr`）
   - `x1 = 0x80`（`FUTEX_WAIT_PRIVATE`）
   - `x2 = 1`（期望内存值为 1，表示正在被某线程初始化）
   - `x3 = 0`（无超时阻塞）
   - `x8 = 98`（`SYS_futex`）
2. **LR（`0x2000ce048`）**：精确指向在发起 `FUTEX_WAIT` 之前执行原子 CAS 比较交换（`bl 0x13cf80`）的返回点。这说明该线程在进入 Futex 前，刚完成了对 `uaddr` 状态的原子探测。

---

## 二、 锁类型严格判定 (Lock Type Determination)

- **确凿锁类型**：**`pthread_once_t`（单次初始化控制字）**。
- **排除类型**：
  - **不是 `pthread_mutex_t`**：`pthread_mutex_lock` 位于 `0x8bea0`，其等待调用使用的是带优先级和鲁棒性处理的 `__lll_lock_wait_private`（`0x85680`）。
  - **不是 `pthread_rwlock_t`**：读写锁入口位于 `0x8ea00` / `0x8f820`，结构包含读者计数与写者锁字。
  - **不是 `pthread_cond_t`**：条件变量位于 `0x87280`，等待走 `futex(FUTEX_WAIT_BITSET)`。
- **依据与状态机机制（glibc NPTL `pthread_once` 规范）**：
  - 控制字为 32 位整型（`uint32_t`），具有如下状态：
    - `0`：未初始化（初始状态）。
    - `1`（即 `ONCE_IN_PROGRESS`）：有线程已获得初始化权利，正在执行 `init_routine`。其他并发到达的线程发现为 1 后，执行 `FUTEX_WAIT_PRIVATE(uaddr, 1, NULL)` 挂起睡眠等待唤醒。
    - `2`（即 `ONCE_COMPLETED`）：初始化成功完成，执行者在 `0x8e120` 执行 `stlr w0, [x4]`（写入 2），随后在 `0x8e138` 发起 `FUTEX_WAKE_PRIVATE(uaddr, INT_MAX)` 广播唤醒所有等待者。
  - **与收据快照完全咬合**：收据中 `word=1`，说明该 `pthread_once_t` 当前**正处于“正在被初始化”状态**。

---

## 三、 匿名区间角色候选与边界评估 (Anonymous Region Role Evaluation)

### 3.1 区间基本事实
- **虚拟地址范围**：`[0x200ffe000, 0x20106e000)`
- **大小**：`0x70000` 字节（458,752 字节 = **448 KiB**）
- **权限与标志位**：`rw-`，`flags = 0x22`（`MAP_PRIVATE | MAP_ANONYMOUS`）
- **相对偏移**：`off = 0x2f440`（`0x20102d440 - 0x200ffe000`）

### 3.2 角色候选分析与概率评估

| 角色候选 | 可能性 | 证据与判定依据 |
| :--- | :---: | :--- |
| **候选一：动态运行时私有堆 / Malloc Arena 内存块** | **极高 (HIGH)** | 1. 大小为 448 KiB，是典型的用户态内存分配器（glibc ptmalloc / jemalloc）通过 `mmap(MAP_ANONYMOUS)` 向系统申请的堆内存池块（Arena Chunk）；<br>2. 偏移 `0x2f440` 位于内存池内部，非常符合在加载 Vulkan ICD（如 `lavapipe` / `winevulkan`）创建全局单例或设备枚举上下文时，通过 `calloc`/`malloc` 分配的动态对象结构（内含 `pthread_once_t` 单例守卫）。 |
| **候选二：子线程执行栈 (Thread Stack)** | **极低 (LOW/NEGLIGIBLE)** | 1. glibc/Linux 默认线程栈大小通常为 2 MiB（`PTHREAD_STACK_MIN` 亦至少 128 KiB 且伴随 4 KiB `PROT_NONE` 保护页）；448 KiB 不符合标准线程栈尺寸与对齐；<br>2. 挂起时刻进程内部仅有 `gtid=1` 一个主线程，且主线程的用户态栈基址由 elfuse 引导期在高端内存建立，不在此区间。 |
| **候选三：静态线程局部存储 (Static TLS Block)** | **低 (UNLIKELY)** | 1. 静态 TLS 段（ELF `.tdata` / `.tbss`）在 `libc.so.6` 中仅数十字节（0x30/0x50）；<br>2. 即使加上 Wine 其它动态库，静态 TLS 结构通常紧贴线程描述符（TPIDR_EL0）布置，而非单独分配 448 KiB 的独立匿名映射。 |

### 3.3 可确定与不可确定的边界

#### 可确定的部分 (Determined Facts)
1. **控制字属性确凿**：`0x20102d440` 确定为 `pthread_once_t` 控制字（当前值为 1，处于进行中状态）；
2. **当前线程角色确凿**：当前主线程（`gtid=1`）在 `vkCreateInstance` 内部调用 `pthread_once` 时，发现该对象已被置为 1，因而进入内核队列等待初始化完成；
3. **分配方式确凿**：该区间不是共享内存（`flags=0x22` 纯私有），由用户态动态匿名 `mmap` 产生。

#### 不可确定的部分 (Undetermined Unknowns)
1. **具体组件与对象归属不可确定**：
   - 该 `pthread_once_t` 究竟属于哪个具体软件模块（是 Wine 内部的 `winevulkan.dll` / `vulkan-1.dll` 单例，还是 Linux 侧驱动 `lavapipe` / `libvulkan.so` 的驱动载入守卫）？由于该内存块是匿名堆分配，缺少符号导出。
2. **回调函数（`init_routine`）的函数指针不可确定**：
   - 寄存器 `x5` 保存的回调地址在本次未返回的系统调用快照中未直接导出，无法静态获知具体在执行哪一段初始化代码。
3. **执行初始化者的归属与缺失唤醒原因不可确定**：
   - 既然当前进程在挂起时刻只有 `gtid=1` 一个线程，那么到底是谁将 `0x20102d440` 置为了 1？
     - *推论分支 A*：`gtid=1` 在此之前同一线程内嵌套重入了同一个 `pthread_once`（自死锁，递归初始化）；
     - *推论分支 B*：此前曾存在一个辅助工作线程将该值置为 1 并开始执行初始化，但在完成并调用 `FUTEX_WAKE` 之前该线程异常退出/崩溃，留下未完成的标志字 1，导致主线程随后跟进时永远休眠。

---

## 四、 结论与后续排查建议 (Conclusion & Next Steps)

1. **核心定性**：
   - 末端挂起并非通用未知锁，而是 **`pthread_once` 单次初始化自锁/未完成等待**。
   - 调用点精确为 `__pthread_once_slow` 的系统调用返回点（`ELR=0x2000ce084`）与 CAS 返回点（`LR=0x2000ce048`）。
2. **下一步建议**：
   - **拦截 `pthread_once` 入口**：在 `0x8e1a0` 处记录每次 `pthread_once(control, init_routine)` 的调用参数，直接抓取是哪一个 `init_routine` 函数指针被传入，并排查是否存在同一线程重入同一个 `once_control`。
