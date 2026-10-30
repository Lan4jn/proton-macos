# Round 38 实验终态汇总与未决项报告 (reports/r38-status.md)

**编制员**：evidence-reviewer-r36 (独立审查员)  
**审查与编制基准**：纯只读证据核验、逐条标注收据来源与反驳条件、四分法定性（已确立 / 已排除 / 未决 / 仍未实证）  
**覆盖轮次与任务**：Round 36 至 Round 38（Task-70 至 Task-81）

---

## 一、 独立复核流程与自检勘误声明 (Self-Audit & Errata Statement)

在本次 Round 38 审查过程中，独立审查员始终恪守双端客观核验，并在流程中如实记录以下自检勘误与教训：
1. **审查员自检勘误（Step 3 判定更正）**：
   - 审查员此前在 reports/reentry-review.md 草稿中曾误将门槛未达写为“预算用尽未达 Step 3”；
   - **Lead 交叉核验指正**：logs/reentry/vulkan/receipt.json 第 50 行的 stdout 字段明确记录了 478 字节输出，包含完整的 [WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...。Step 3 实际已成功达成，未达成的仅为目标 FUTEX_OWNER_ENTER；
   - **已全面更正**：审查员已重写 reports/reentry-review.md 与 logs/reentry-review/audit_summary.json，如实反映该项已达成的事实，并如实记录本轮独立复核自身的纠错过程。
2. **系统性高发笔误通报**：
   - 本轮系列报告连续四次出现 stderr_bytes 机械复用旧值（149432B 与 685764B）、run_dir 路径虚标失效（如不存在的 run-5k49m17s、run-d19x74b_、run-x960682y）；
   - 所有数据已强制以物理落盘文件与收据 JSON（如 run-rx848drl、run-c9cit7bo）为唯一真理校准。

---

## 二、 四分法定性汇总清单 (Taxonomy: Established / Disproved / Unsettled / Unverified)

### 1. 已确立事实 (Established Facts)
指在多次真实 Wine 测量运行中稳定复现、物理收据完整闭环、汇编与系统调用参数完全一致的硬性技术事实。

| 序号 | 已确立事实条目 | 证据来源 (Receipt & Log) | 物理参数与反驳条件 |
| :---: | :--- | :--- | :--- |
| **E1** | **末端挂起点位于 glibc pthread_once 内部** | reports/futex-libc-symbols.md<br>logs/futex-symbols/pthread_once_disasm.txt | 偏移 0x8e080 svc #0，入参 nr=98, op=0x80 (FUTEX_WAIT_PRIVATE), val=1, timeout=0，返回点 ELR=0x8e084，CAS返回点 LR=0x8e048。<br>**反驳条件**：反汇编证明其非 pthread_once 或系统调用号/入参不符。 |
| **E2** | **控制字 0x20102d440 确系处于状态 1 的 pthread_once_t** | logs/futex-owner/vulkan/receipt.json<br>logs/once-trace/vulkan/receipt.json | 内存快照 word=1（对应 ONCE_IN_PROGRESS），反汇编证实完成路径将在 0x8e120 stlr 存入 2 并通过 0x8e138 svc #0 广播唤醒。<br>**反驳条件**：内存字不为 1，或其偏移对应其他互斥量/读写锁字段。 |
| **E3** | **目标内存位于匿名私有区间，非驱动代码/数据段** | logs/futex-owner/vulkan/receipt.json (FUTEX_OWNER_MAP) | 确切位于区间 [0x200ffe000, 0x20106e000)，大小 448 KiB，权限 rw-，标志 0x22 (MAP_PRIVATE|ANONYMOUS)，相对偏移 0x2f440。<br>**反驳条件**：该地址被任何文件映射或驱动 .so（如 libvulkan_lvp.so）包含。 |
| **E4** | **主 Wine 进程从始至终单线程存活，无并发唤醒者** | logs/thread-lifetime/vulkan/receipt.json (run-iagdhuck) | 进程内 thread_alloc 计数恒为 0，唯一存活 gtid=1；全运行针对该地址的 Futex 调用仅 1 次，无并发 FUTEX_WAKE。<br>**反驳条件**：捕获到主进程内有第 2 个线程存活并参与调度。 |
| **E5** | **区间建立首读为 0x00，在 324.207ms 后发生唯一写 1 跃迁** | logs/once-trace/vulkan/receipt.json (run-rx848drl) | ts_us=955523381988 (first_mapped, val=0) 到 ts_us=955523706195 (val_change, val=1) 差值严格为 324,207 us = 324.207 ms。<br>**反驳条件**：首读不为 0，或跃迁时间差不等于 324.207 ms。 |

---

### 2. 已排除假设 (Disproved Hypotheses)
指通过针对性隔离实验、最小纯 C 测试或全量生命周期时序确凿否定、不再成立的竞争假设。

| 序号 | 已排除假设条目 | 证据来源 (Receipt & Test) | 排除依据与反驳条件 |
| :---: | :--- | :--- | :--- |
| **D1** | **排除单线程 pthread_once 通用实现缺陷** | scripts/runtime/mem_once/test_once<br>logs/mem-once/summary.json | 最小单线程程序调用 pthread_once(PTHREAD_ONCE_INIT) 顺利进入回调、置 2 并返回 0，无挂起（退出码 0）。<br>**反驳条件**：在 elfuse 下基础单线程调用产生死锁。 |
| **D2** | **排除全新匿名映射未零填充 / 底层脏内存残留** | scripts/runtime/mem_once/test_mmap_zero<br>logs/mem-once/summary.json | 申请 448 KiB 匿名私有页，包括目标偏移 0x2f440 在内的全部抽样点初始读取严格全为 0x00（退出码 0）。<br>**反驳条件**：全新 mmap 分配后首次读取出现非零字节。 |
| **D3** | **排除 fork / clone 0x1200011 私有页写泄漏 (COW 穿透)** | scripts/runtime/mem_once/test_fork_cow<br>test_clone_variants | 子进程对私有页写 1，父进程 wait 后重读依然严格为 0x0，COW 隔离完好，无跨进程污染。<br>**反驳条件**：父进程在子进程写后读出非零数值。 |
| **D4** | **排除子进程 49 崩溃/早退导致锁遗留** | logs/thread-lifetime/vulkan/receipt.json (tid49_records) | 子进程 49 仅存活 16.7ms 且以退出码 0 正常退出回收，发生于末端挂起前 124 个调用之前，与锁无关。<br>**反驳条件**：子进程 49 处于异常退出或其内存与主进程强行共享。 |
| **D5** | **排除初值污染 / 堆复用残留假设 A2** | logs/once-trace/vulkan/receipt.json | 采样器捕获的真实首读 first_mapped 为 val=0x0，控制字并非建立时即为 1。<br>**反驳条件**：首次映射即读出数值 1。 |

---

### 3. 未决状态分支 (Unsettled Branches)
指当前软件轮询技术手段已达物理极限、证据链尚存断层、两类竞争模型均未被完全证伪的开放问题。

| 序号 | 未决项目与分支 | 当前证据现状与局限 | 终局证实 / 反驳方案 |
| :---: | :--- | :--- | :--- |
| **U1** | **单线程递归重入自锁 (假设 A) vs 异常路径未置 2 (假设 A_alt)** | **两分支均未决**：已证实程序离开初始化入口执行了大量外部操作后再次到达 once 等待；但未捕获两次调用栈前，不能排除初始化例程内部异常跳转未置 2 的微弱分支。 | **方案**：采用指令级 HVC 断点计数（在 0x8e1a0 处设置陷阱），统计针对目标地址的实际进入次数（见第三节）。 |
| **U2** | **写 1 跃迁时刻的调用者与发起模块** | **因果定性为未定**：虽捕获逐字映射落在 ld-linux-aarch64.so.1，但前序轮次曾归属于 sh，两轮不一致表明其极可能是此前系统调用留下的陈旧寄存器镜像，不构成直接调用者证据。 | **方案**：在 0->1 写入点直接截获硬件数据写入中止（Data Write Abort），提取写入当时硬件管线中的实时 PC。 |
| **U3** | **高频软件轮询判别手段的可行性** | **已被实测否定**：300us 软件轮询带来不可忽略的时序滞后扰动，在两轮 62s 预算内均未能抵达末端挂起点（run_valid = false / NOT_REPRODUCED）。 | **方案**：彻底放弃背景多线程轮询，全面转向零开销的指令级/异常触发式断点方案。 |

---

### 4. 仍未实证项清单 (Unverified High-Level Goals)
指距离工业级运行依然存在本质跨度的未达标领域，严禁过度宣称：
1. **Windows Vulkan 图形设备与渲染流水线未见返回**：目前仅推进至 vkCreateInstance 内部动态链接期，物理设备枚举、交换链与帧渲染未实证；
2. **原生 macOS Steam 客户端交互与 Steamworks API 通信未实证**：当前仅在离线存根与模拟目录验证了可逆性与路径封闭性，真实 Steam 客户端内部启动与在线票据下发未实证；
3. **Valve 官方直接签名未实证**：当前依赖经过校验的公开二次分发镜像，非官方直接源；
4. **正确的 COW（写时复制）机制未实现**：当前所有衍生诊断运行时均继承了 ELFUSE_DIAG_SESSION_SHARED=1 诊断门禁，并非工业级 COW 实现。

---

## 三、 决胜方案：指令级 HVC 软件断点计数方案规范 (Proposed Resolution)

鉴于高频软件轮询已被实测证明不可行，下一步攻坚应采用如下零开销断点方案：

1. **实现机制**：
   - 在 guest glibc pthread_once 入口汇编指令（0x8e1a0）处设置断点指令（或配置 Hypervisor 硬件断点寄存器）；
   - 每次有执行流进入 pthread_once 时，触发轻量级 VM Exit 陷入宿主；
2. **终局判定判据**：
   - 宿主从寄存器 X0 提取 once_control 地址，维护哈希表计数：
     - **计数 == 2**：若同一地址 0x20102d440 被第 2 次进入，且当前内存值为 1，则**确凿证实单线程递归重入自锁（假设 A）**；
     - **计数 == 1**：若针对该地址自始至终只进入 1 次即陷入等待，则**确凿证实异常路径未置 2（假设 A_alt）**。
3. **技术声明**：该方案为经过理论验证的可行技术路径，目前尚未编码实现，作为后续攻坚基石立项。
