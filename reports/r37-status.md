# Round 37–40 终态综合技术报告 (reports/r37-status.md)

**编制员**：evidence-reviewer-r36 (独立审查员)  
**纪律原则**：纯只读证据链综合、严禁过度定性、逐条标注物理收据与指令反汇编来源、四分法定性  
**覆盖任务范围**：Round 37 至 Round 40 关键技术突破（Task-79 至 Task-86）

---

## 一、 核心架构技术定论 (The Central Architectural Conclusion)

> **核心定论**：  
> **Windows ARM64 Vulkan 执行链当前仍然被 guest 用户空间（Linux 侧）的 `pthread_once` 递归重入死锁完全阻断。物理证据确凿证明：该死锁的根本成因在于 `libvulkan.so.1`（Khronos Vulkan Loader）内部调用图与初始化状态机环路闭合，绝非 `elfuse` 虚拟机底层 Futex 同步原语的实现缺陷。**

---

## 二、 关键技术突破与证据链条 (Verified Technical Breakthroughs)

### 1. 指令级断点计数确证：两次进入与嵌套重入死锁 (Task-82 证据)
在 `sources/elfuse-once-count-derived` 中，宿主通过在 guest glibc (`libc.so.6`) 的 `pthread_once` 公共入口（汇编地址 `0x2000ce1a0`）精准布设 `BRK` 指令级硬件陷阱（拦截证据：`entry_pc=0x2000ce1a0`, `orig_insn=0x88dffc02`, `brk_insn=0xd4200000`），捕获到了主线程（`gtid=1`）对目标控制字 `0x20102d440` 的全量微观行为：
- **首次进入**：`ts_us=977897241236`，读取当前内存字 `word=0`，调用者返回地址 `LR=0x200f39d24`，原子 CAS 执行 0 -> 1，进入外层初始化；
- **二次进入**：`ts_us=977906698324`（相隔整整 **9.457 秒** 之后），读取当前内存字 `word=1`，调用者返回地址 `LR=0x200f3a3f8`；
- **glibc 状态机语义推导证明**：
  依据 `nptl/pthread_once.c` 与反汇编证据（`reports/futex-libc-symbols.md`），正常完成的初始化例程退出前**必然在 `0x8e120 stlr` 指令将控制字置为 2**。全生命周期内，该地址从未被置 2，证明首次调用尚未返回；而二次进入时读取为 1，直接触发慢路径 `SYS_futex(0x20102d440, FUTEX_WAIT_PRIVATE, 1)`（事务 `id=855`）无限挂起。
- **裁决**：**单线程递归嵌套重入死锁获得指令级事实确证（CONCLUSIVELY PROVEN）**。

---

### 2. 多重 once 嵌套链时间线与环路闭合 (Task-85 证据)
基于 `run-iwju_2kq` 捕获的 19 次全量 once 进入记录，刻画出完整的嵌套级联初始化时间线：

```text
1. ts=977896836386: 0x200ffdd10 进入 (word=0, LR=0x200e33b4c, 基础加载初始化)
2. ts=977897241236: #1 0x20102d440 首次进入 (word=0, LR=0x200f39d24, CAS 0->1, 外层初始化展开)
3. ts=977899633543: 0x20d6a15dc 进入 (LR=0x20d47ab48, Mesa/Lavapipe 驱动 once, 顺利 0->2 完成, 随后13次快路径返回)
4. ts=977900171408: #2 0x20102d478 进入 (+2.93s, word=0, LR=0x200f3af04, CAS 0->1, 内层组件初始化展开)
5. ts=977906698307: #3 0x20100de08 进入 (word=0, LR=0x200e3b914, CAS 0->1, 扩展子系统初始化)
6. ts=977906698324: #1 0x20102d440 再次重入 (距 #3 仅 17 微秒！word=1, LR=0x200f3a3f8)
7. ts=977906698340: 发起 futex wait (0x20102d440, op=0x80, val=1) -> 环路闭合，全链挂死！
```

**技术特征**：三个不同的 `pthread_once` 控制字（#1 `0x20102d440`, #2 `0x20102d478`, #3 `0x20100de08`）在同一调用树上同时处于“已被置 1、正在初始化、尚未置 2”的活跃状态；最终在距离 #3 仅 17 微秒时，执行流闭合回 #1，触发重入死锁。

---

### 3. 诊断性放行实验：首个缺口与次级缺口 (Task-83 证据，DIAGNOSTIC ONLY)
为验证“该死锁是否为唯一障碍”，在 `sources/elfuse-once-bypass-derived` 中实施受控诊断放行（严格受控：`op=0x80, val=1, word=1`, 仅限单线程放行一次，标记 `BORROWED/DIAGNOSTIC`，严禁作为修复）：
- **基准对照组 (`run-4fy5uahy`, 开关关闭)**：耗时 62.13s 超时退出，卡死在首个控制字 `0x20102d440`，`stderr_bytes = 717,937`，`run_valid = true`；
- **放行实验组 (`run-myqxkcq3`, 开关开启)**：
  - 首个死锁点被放行（耗时 51µs 返回 0，控制字强制置 2）；
  - **45 微秒后命中次级缺项**：在事务 `id=856` 处，执行流立即陷入第二个控制字 **`uaddr = 0x20102d478`**（同样 `op=0x80, val=1, word=1`）；
  - `stderr_bytes = 666,550`，`run_valid = true`。
- **技术定性**：`0x20102d440` 是执行链条上的**首个截断点，但绝非唯一缺口**。

---

### 4. 本轮否证与澄清的猜测 (Falsified Guesses)
1. **否证 Khronos Loader 显式递归告警猜测**：
   此前推测 Loader 内部可能因函数指针循环抛出 `points to the loader / infinite recursion` 警告。对全部运行日志检索，**匹配命中数严格为 0**，证实未曾触发该官方防御日志；
2. **限定 Task-84 调用点反汇编的边界**：
   - 目标库 `fixtures/runtime/arch-case/usr/lib/libvulkan.so.1` 处于 **stripped（剥除符号）** 状态；
   - 报告中提及的函数名（如 `loader_is_extension_supported`, `normalize_path`）仅系基于 rodata 报错字符串的语义临近推测，**不得当作真实动态符号证据**；
   - 56 字节间距（`0x38`）虽符合结构体对齐，但“`56字节 = struct loader_scanned_icd`”属于**未验证的结构假设**，真实 C 结构体定义待后续源码对比或 DWARF 符号反查。

---

## 三、 四分法定性汇总 (Final Taxonomy)

### 1. 已确立事实 (Established Facts)
- **E1**: 进程内唯一单线程 `gtid=1`，无并发 WAKE 唤醒者；
- **E2**: 末端挂起点位于 glibc `pthread_once` 内部慢路径（`0x8e080 svc #0`）；
- **E3**: 目标内存 `0x20102d440` 与 `0x20102d478` 位于匿名私有区间 `[0x200ffe000, 0x20106e000)`，非驱动代码/数据段；
- **E4**: 目标控制字初值严格为 0，经 324.207ms 后写 1，在 9.457s 后发生二次重入；
- **E5**: 诊断放行证实存在次级死锁点 `0x20102d478`，两者间距精准为 56 字节（`0x38`）。

### 2. 已排除假设 (Disproved Hypotheses)
- **D1**: 排除单线程 `pthread_once` 通用实现缺陷（最小测试退出码 0）；
- **D2**: 排除全新匿名页未零填充 / 脏内存残留；
- **D3**: 排除 fork / clone `0x1200011` COW 私有内存穿透泄漏；
- **D4**: 排除子进程 49 退出导致锁遗留（早退于挂起前 124 事务）；
- **D5**: 排除 Loader 显式 infinite recursion 告警触发；
- **D6**: 排除“单点死锁是唯一缺口”的乐观假设。

### 3. 未决状态分支 (Unsettled Branches)
- **U1**: 导致初始化例程产生嵌套调用的上层具体驱动业务函数名尚未取得符号确证（受限于 stripped 动态库）；
- **U2**: 连续 56 字节结构体究竟是 Loader 内部的扫描 ICD 列表、扩展结构体还是图元分配链表尚未确证；
- **U3**: 300us 高频软件轮询已被证明会因微观时序扰动改变执行节奏，无法作为长程追踪手段。

### 4. 仍未实证项清单 (Unverified Goals)
- **Vulkan 图形设备枚举与真实渲染流水线未见返回**；
- **原生 macOS Steam 客户端交互与 Steamworks 在线 API 未验证**；
- **Valve 官方直接签名源未实证**；
- **正确的全局写时复制（COW）未实现**（目前依赖 `ELFUSE_DIAG_SESSION_SHARED=1` 诊断门禁）。

---

## 四、 报告制品与收据索引

| 制品路径 | 字节数 | 说明 |
| :--- | :---: | :--- |
| `reports/r37-status.md` | 本文件 | Round 37–40 终态综合技术报告 |
| `logs/r37-summary/receipt.json` | 3,696 | 结构化事实收据与时序链 |
| `reports/FINAL.md` | 见更新 | 实验全局总索引与当前状态段更新 |
