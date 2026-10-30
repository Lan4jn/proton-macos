# 私有文件映射语义测试与 ELFUSE_DIAG_SESSION_SHARED 诊断门禁深度审计报告 (Task-87)

**责任人**：futex-owner-r36 (执行员)  
**遵循规范**：`test-driven-development`（Red-First 真实缺陷驱动验证、严禁伪造通过、实测数据留证）  
**关联任务**：Task-87（建立私有文件映射可执行测试并尝试移除诊断门禁）

---

## 一、 背景与既往技术假设

在此前针对 Wine ARM64 Vulkan 执行链的分析中，Wine 在初始化只读 session section 时使用了 `PROT_READ | PROT_WRITE` 与 `MAP_PRIVATE` 文件映射（映射长度 `0x144000`，偏移 0）。
Linux 规范对于可写私有文件映射（`MAP_PRIVATE`）的标准语义包括：
1. **语义 (a) - 活文件可见性 (Live File Visibility)**：对于 guest 尚未写入过的页面，底层文件的后续修改应当能够反映到映射内存中；
2. **语义 (b) - 写时复制隔离 (COW Isolation)**：一旦 guest 首次写入某一页面，该页面脱离底层文件独立分配（COW），底层文件后续写入不再影响该页；
3. **语义 (c) - 绝不回写文件 (Never Write-Back)**：guest 对私有映射的任何写入，绝对不得回写到底层文件。

为了在缺少完整 COW 支持的 `elfuse` 运行时中让 Wine 能看见 session section 的动态初始化，此前在 `src/syscall/mem.c` 中引入了 `ELFUSE_DIAG_SESSION_SHARED=1` 门禁：
```c
if (getenv("ELFUSE_DIAG_SESSION_SHARED") && fd >= 0 &&
    length == 0x144000 && offset == 0 && prot == (LINUX_PROT_READ | LINUX_PROT_WRITE) &&
    (flags & LINUX_MAP_PRIVATE) && !(flags & LINUX_MAP_ANONYMOUS)) {
    // 强制将 MAP_PRIVATE 转换为 MAP_SHARED，走底层 host mmap overlay
    flags = (flags & ~LINUX_MAP_PRIVATE) | LINUX_MAP_SHARED;
}
```
代码明确注释：**`NOT AN ABI FIX: gated causal experiment sacrificing private-write isolation`**（非 ABI 修复，而是牺牲私有写隔离的因果诊断实验）。

---

## 二、 Red-First 语义测试套件设计与判定标准

在 `scripts/runtime/private_cow/` 目录下构建了两个严格的自动化测试用例，并在 `elfuse` ARM64 裸 Linux 环境下实测：

### 1. 通用私有映射测试：`test_private_cow.c`
- **测试环境**：ARM64 Linux ELF 动态链接二进制，由 Zig 交叉编译至 `scripts/runtime/private_cow/test_private_cow` (SHA256: `a518e9407cd66617e961b9ee8140b02db76073775705ccc70a2324554580b08d`)；
- **测试步骤**：
  - 创建 4 页文件，各页填充 `0x10 + page_index`；
  - `mmap(NULL, 16KB, PROT_READ|PROT_WRITE, MAP_PRIVATE, fd, 0)`；
  - **Test (a)**：通过文件 fd 向 Page 0 写入 `0xAA`，检验映射是否呈现 `0xAA`；
  - **Test (b)**：guest 向 Page 1 写入 `0x55`，随后文件 fd 向 Page 1 写入 `0xBB`，检验 guest 是否依然保持 `0x55`（COW 隔离）；
  - **Test (c)**：guest 向 Page 2 写入 `0x77`，执行 `msync`，随后通过 `pread` 读取文件对应位置，检验文件是否保持原值 `0x12`（未被污染）。

### 2. 门禁参数专用对照测试：`test_diag_gate.c`
- **测试特征**：精准对齐门禁判定条件：`length == 0x144000` (1,327,104 字节)，`offset == 0`，`unlink(file)` 造成 `st_nlink == 0`，`O_RDWR`；
- **编译产物**：`scripts/runtime/private_cow/test_diag_gate` (SHA256: `e547f5dbcbd9d7737bbab8b19b4b17ca82707cd63da3ac5e3046b4c97f6c7de9`)。

---

## 三、 实测结果与缺口留证 (Red Results)

使用当前基线二进制 `sources/elfuse-once-count-derived/build/elfuse` (SHA256: `24b488983f4c1be058657355c4ce894e446451e2dfa902a1fd5b618b81fe9b16`) 执行自动化对比测试：

### 1. 通用私有映射测试结果 (`test_private_cow`)
测试脚本：`scripts/runtime/private_cow/run_test.py`，收据：`logs/private-cow/red_baseline_summary.json`

```text
=== 运行一：关闭诊断门禁 (extra_env: {}) ===
[TEST_A] Modifying file page 0 to 0xAA after MAP_PRIVATE...
[TEST_A_FAIL] Live file modification INVISIBLE: got 0x10 (expected 0xAA, stuck at snapshot 0x10)
[TEST_B] Guest writes 0x55 to page 1, then file modified to 0xBB...
[TEST_B_PASS] COW isolation intact: guest sees 0x55 (expected 0x55)
[TEST_C] Verifying guest write does not write back to file...
[TEST_C_PASS] File not modified: pread got 0x12 (expected 0x12, not 0x77)
PRIVATE_COW_TESTS_FAILED failure_mask=0x1 (Exit Code: 1) -> [RED]

=== 运行二：开启诊断门禁 (extra_env: {'ELFUSE_DIAG_SESSION_SHARED': '1'}) ===
[由于通用测试长度为 16KB != 0x144000，未命中门禁判定，行为与运行一完全相同]
PRIVATE_COW_TESTS_FAILED failure_mask=0x1 (Exit Code: 1) -> [RED]
```

**缺陷定性 (RED)**：
- 未设置门禁或长度不匹配时，`elfuse` 内部实现走的是第 3595 行的 **`pread` 快照模式**；
- 页面数据在 `mmap` 调用瞬间从文件全量复制入匿名内存。底层文件随后的任何动态写入，guest 内存完全**无法感知**（保持首次快照值 `0x10`）；
- **语义 (a) 失败，产出第 1 个核心缺陷留证 (RED)**。

---

### 2. 诊断门禁对照测试结果 (`test_diag_gate`)
测试脚本：`scripts/runtime/private_cow/run_diag_test.py`，收据：`logs/private-cow/diag/diag_comparison_summary.json`

| 测试项 | 未开启门禁 (extra_env: {}) | 开启门禁 (ELFUSE_DIAG_SESSION_SHARED=1) |
| :--- | :---: | :---: |
| **退出码** | **`1` (Fail)** | **`6` (Fail)** |
| **Test (a): 活文件可见性** | ❌ **FAIL** (读出 0x10，不可见) | ✅ **PASS** (读出 0xaa，可见) |
| **Test (b): 写后 COW 隔离** | ✅ **PASS** (保持 0x55) | ❌ **FAIL** (被文件改写为 0xbb，隔离破坏！) |
| **Test (c): 绝不回写文件** | ✅ **PASS** (文件仍为 0x10) | ❌ **FAIL** (文件被回写为 0x77，文件污染！) |
| **内核日志** | (无输出) | `DIAGNOSTIC_SHARED_ALIAS_NOT_ABI_FIX pid=... len=0x144000` |

**门禁机理深度定性**：
- `ELFUSE_DIAG_SESSION_SHARED=1` 通过将私有映射伪造为共享映射（`MAP_SHARED`），使得 host page cache 的修改通过共享页表直接穿透到 guest，从而“强行满足”了语义 (a)；
- 但代价是**彻底毁灭了语义 (b) 与 (c)**：guest 的写入变成了直接写入文件底层，而底层文件的后续写入也会强行冲刷掉 guest 本地写入！

---

## 四、 macOS / Apple HVF 平台机理探究与移除诊断门禁尝试

为了探索能否在 `sources/elfuse-private-cow-derived` 内存层移除门禁、实现真正的写时复制，执行员使用 macOS 原生 Hypervisor API 与 XNU 内核机制进行了探针实验：

### 1. 探针实验：Apple HVF 是否接受 `MAP_PRIVATE` 的宿主 HVA？
编写原生测试程序并在派生目录下用 entitlements 签名执行：
- `hva = mmap(NULL, size, PROT_READ|PROT_WRITE, MAP_PRIVATE, fd, 0)`；
- `ret = hv_vm_map(hva, ipa, size, HV_MEMORY_READ | HV_MEMORY_WRITE | HV_MEMORY_EXEC)`；
- **实测结果**：**`ret == 0 (HV_SUCCESS)`**。
- 这证明：**Apple Silicon HVF 在 stage-2 映射层面并不拒绝宿主提供一个 MAP_PRIVATE 建立的 HVA 页面**。

### 2. 深入阻碍：macOS XNU 统一虚拟内存 (UVM) 的单向 COW 机制
紧接着对 macOS XNU 内核在 host userspace 下的真实行为进行实测（见 `/tmp/test_host_cow` 与 `/tmp/test_mmap_darwin`）：
- **实测现象**：
  在 macOS 上执行 `mmap(MAP_PRIVATE)` 后，若宿主外部通过 `pwrite` 修改底层文件，映射在 **即使从未被写入过** 的情况下，由于 macOS 内核页缓存的预读与懒加载机制，**一旦该页被读取 fault 载入，后续文件的 pwrite 就不再自动同步到该 private mapping 中**（实测读取始终保持初值 `0x11`，无法看到 `0xaa`）。
- **技术瓶颈**：
  在 Linux 原生内核中，私有只读缺页异常（Read Fault）直接映射到 Page Cache 的物理页（因此文件的持续修改对只读私有页完全可见），只有在发生写入缺页异常（Write Fault）时才真正分配独立匿名页并发生拷贝。
  然而在 macOS 上：
  1. XNU 的 `MAP_PRIVATE` 语义在页面一旦实例化后，并不会在底层文件修改时自动刷新宿主私有页缓存；
  2. 即使在 stage-2 将宿主私有页映射进虚拟机，宿主内核也不支持针对已映射给 HVF 的私有页发起外部一致性反向失效（Reverse Invalidation）。

---

## 五、 结论、影响评估与回滚说明

### 1. 测试现状结论
- **语义缺口证据确立 (RED)**：
  - 在无诊断门禁的纯净环境下，`elfuse` 对私有文件映射采用 `pread` 快照，**语义 (a) 必然失败（Test A FAIL）**；
  - 在开启诊断门禁下，虽然语义 (a) 伪造通过，但**语义 (b) 与 (c) 双重崩溃（Test B FAIL, Test C FAIL）**；
  - 该实测结果完全符合预期，彻底证实了“私有文件映射语义不完整”的缺口客观存在。

### 2. 为什么不可贸然直接移除诊断门禁？
- Wine 会话管理（Session Section）高度依赖在多个组件间通过文件协同更新共享状态。若在没有完善的 Stage-2 缺页拦截重写（Page Fault Trap & Copy）机制前直接移除 `ELFUSE_DIAG_SESSION_SHARED`，Wine 的只读 session 映射将直接退化为静态快照，导致 Wine 在早期初始化阶段即无法感知会话变更而直接挂起。
- 因此，当前阶段 **`ELFUSE_DIAG_SESSION_SHARED=1` 必须继续保留为诊断门禁**，绝不可作为默认产品逻辑，亦不可简单删除。

### 3. 制品与回滚说明
- 所有探针实验代码与测试套件均封装在独立路径：
  - `scripts/runtime/private_cow/`（测试用例与自动化对比运行器）
  - `logs/private-cow/`（测试收据与输出日志）
  - `sources/elfuse-private-cow-derived/`（独立派生目录，仅做探针与验证，未篡改已验收源码）
- 既有已验收的二进制制品（如 `sources/elfuse-once-count-derived/build/elfuse`）及所有测试收据**未受任何修改**，项目全局随时可零成本完全回滚。
