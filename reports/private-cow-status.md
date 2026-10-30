# 私有文件映射门禁的文件回写风险与状态审计报告 (Task-88)

**责任人**：futex-owner-r36 (执行员)  
**审计性质**：只读实测证据链归纳、安全与语义边界划定、多轮运行收据限定声明  
**支撑收据**：
1. `logs/private-cow-status/red_baseline_summary.json` (无门禁基线自动化测试收据)
2. `logs/private-cow-status/diag_comparison_summary.json` (门禁开启对照组自动化测试收据)

---

## 一、 无门禁基线赤字事实 (RED Baseline Evidence)

在 `logs/private-cow/red_baseline_summary.json` 中，针对标准 Linux 可写私有映射（`MAP_PRIVATE`, `PROT_READ | PROT_WRITE`）进行语义测试：
- **测试用例**：`scripts/runtime/private_cow/test_private_cow`
- **运行环境**：无诊断门禁纯净基线（`extra_env: {}`）
- **进程退出码**：`exit = 1` (测试失败)
- **实测标准输出核心断言**：
  ```text
  [TEST_A] Modifying file page 0 to 0xAA after MAP_PRIVATE...
  [TEST_A_FAIL] Live file modification INVISIBLE: got 0x10 (expected 0xAA, stuck at snapshot 0x10)
  [TEST_B] Guest writes 0x55 to page 1, then file modified to 0xBB...
  [TEST_B_PASS] COW isolation intact: guest sees 0x55 (expected 0x55)
  [TEST_C] Verifying guest write does not write back to file...
  [TEST_C_PASS] File not modified: pread got 0x12 (expected 0x12, not 0x77)
  PRIVATE_COW_TESTS_FAILED failure_mask=0x1
  ```
- **机理确证**：
  在无门禁时，`elfuse` 内部实现严格走 `mem.c:3595` 的 `pread` 快照模式。页面数据在 `mmap` 瞬间从文件静态复制到匿名内存；底层文件随后的任何动态更新，guest 内存完全不可见（依然停留于首次快照值 `0x10`）。**语义 (a)（活文件修改可见性）确定缺失，确凿留存 RED 证据**。

---

## 二、 开启诊断门禁对照组实测事实 (Diagnostic Gate Flaw Evidence)

在 `logs/private-cow/diag/diag_comparison_summary.json` 中，针对满足门禁判定参数（`length == 0x144000`, `offset == 0`, `unlink` 导致 `st_nlink == 0`, `O_RDWR`）的文件映射进行对比：
- **测试用例**：`scripts/runtime/private_cow/test_diag_gate`
- **运行环境**：`extra_env: {'ELFUSE_DIAG_SESSION_SHARED': '1'}`
- **进程退出码**：`exit = 6` (语义 (b) 与 (c) 双重失败：`0x2 | 0x4 = 0x6`)
- **内核日志留证 (stderr)**：
  ```text
  DIAGNOSTIC_SHARED_ALIAS_NOT_ABI_FIX pid=62728 dev=16777242 ino=77441 len=0x144000 old_flags=0x2
  ```
  实测确证：`elfuse` 在底层拦截该映射，并强行将其转为 `MAP_SHARED` 走宿主文件覆盖层。
- **实测标准输出完整三行（逐字精确引用）**：
  ```text
  [DIAG_TEST_A] Modifying file page 0 to 0xAA...
  [DIAG_TEST_A_PASS] Live file modification visible: 0xaa
  [DIAG_TEST_B] Guest writes 0x55 to page 1, file modified to 0xBB...
  [DIAG_TEST_B_FAIL] COW isolation BROKEN (MAP_SHARED leaked): 0xbb (expected 0x55, got file write)
  [DIAG_TEST_C] Verifying guest write does not write back to file...
  [DIAG_TEST_C_FAIL] Guest write LEAKED to file: pread got 0x77 (expected 0x10, wrote back 0x77)
  ```

---

## 三、 安全风险结论与历史 Vulkan 运行限定声明

### 1. 严重文件回写安全风险
实测数据毫无疑问地表明：`ELFUSE_DIAG_SESSION_SHARED=1` 虽然通过伪造 `MAP_SHARED` 使得活文件更新穿透到 guest，但代价是**彻底摧毁了写时复制（COW）隔离与私有写保护**：
- **COW 隔离破坏**：底层文件的后续写入会直接冲刷掉 guest 已经写入的内存数据（如 Test B 中 guest 写入的 `0x55` 直接被底层写入覆盖为 `0xbb`）；
- **文件回写与脏数据篡改**：guest 对映射内存的所有修改，都会通过宿主共享映射真实回写到底层文件（如 Test C 中 guest 写入的 `0x77` 被直接写回文件），**存在严重篡改被映射底层文件的风险行为**。

### 2. 既往 Vulkan 运行收据的显式限定声明 (Scope Limitation)
**在此郑重声明**：
此前所有依赖 `ELFUSE_DIAG_SESSION_SHARED=1` 运行的 Windows ARM64 Vulkan 测量（包括 `once-count`、`once-bypass`、`futex-args` 等轮次），其涉及 session section 的内存语义**均处于该「COW 破坏 + 物理文件直接回写」的非标准风险语义之下**；所有相关测量收据在引用时，必须严格标注此诊断限定，绝不可宣称为符合 Linux 标准 ABI 的运行环境。

### 3. 重要免责边界：末端 once 死锁结论完全不受影响
需要严谨澄清的是：
- 我们的末端挂起与死锁分析目标是 **`uaddr = 0x20102d440`**；
- 依据 Task-70 与 Task-82 的物理内存映射证据，`0x20102d440` 确凿位于匿名私有区间 `[0x200ffe000, 0x20106e000)`（`flags=0x22`，即 `MAP_PRIVATE | MAP_ANONYMOUS`），**完全是堆/匿名内存，根本不是文件映射**；
- `ELFUSE_DIAG_SESSION_SHARED` 门禁在 `mem.c` 中有严苛的前置过滤：`!(flags & LINUX_MAP_ANONYMOUS)` 与 `length == 0x144000`，**绝对不会对 `0x20102d440` 所在的匿名私有内存产生任何副作用**。
- 因此，“主线程在 `0x20102d440` 处由于 `pthread_once` 递归重入导致死锁”的物理确证结论完全独立、坚如磐石，不受此文件映射缺陷的影响，严禁过度外推。

---

## 四、 平台机理限制：macOS / Apple HVF 下的天然瓶颈

在探针实验中，已确认以下平台级事实：
1. **Apple Silicon HVF stage-2 机制**：宿主调用 `hv_vm_map` 传入由宿主 `mmap(MAP_PRIVATE)` 获得的 HVA 地址时，HVF 能够正常返回 0（`HV_SUCCESS`）；
2. **macOS XNU 统一虚拟内存 (UVM) 限制**：
   在 macOS 用户态中执行 `mmap(MAP_PRIVATE, fd)` 后，若宿主进程外部通过 `pwrite` 修改文件，由于 XNU 虚拟内存管理机制，只要页面被读取并实例化（Page Fault），后续针对文件的写入绝不会向该私有映射做反向失效（Reverse Invalidation），映射始终锁定在初次读取的值；
3. **架构推论**：
   因此，在 macOS / HVF 环境下，**绝不能简单寄希望于“直接依靠宿主内核的 MAP_PRIVATE 映射”来取得 Linux 规范的私有文件映射语义**，必须依赖 `elfuse` 在虚拟机内存管理层（如 stage-2 缺页中断捕获、私有副本分裂、动态脏页复制与同步）介入实现。
