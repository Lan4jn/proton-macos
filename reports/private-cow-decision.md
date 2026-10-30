# 私有文件映射语义架构级决策评估报告 (Task-98)

**评估员**：futex-owner-r36 (执行方决策评估)  
**评估性质**：严谨架构级工程评估（决策级可行性与回归边界分析，绝非虚构修复宣称）  
**关联任务**：Task-98（私有映射语义决策评估: 可达性 / 改动面 / 验收标准）  
**支撑收据**：
1. `logs/private-cow-decision/red_baseline_summary.json` (纯净无门禁基线赤字收据)
2. `logs/private-cow-decision/diag_comparison_summary.json` (门禁破坏 COW 与文件回写对照收据)
3. `reports/private-cow.md`、`reports/private-cow-status.md` (已验收实测事实)

---

## 一、 现状基线与核心矛盾确证 (Established Baseline & The Dilemma)

依据 Task-87 与 Task-88 的物理实测与收据留证：
1. **纯净基线状态 (extra_env: {})**：
   - `elfuse` 内部实现严格走 `src/syscall/mem.c:3595` 的 `pread` 静态快照路径；
   - 映射内存只在 `mmap` 瞬间复制文件内容。底层文件的后续任何动态更新，内存完全不可见（`test_private_cow` 实测退出码 `exit=1`，报 `[TEST_A_FAIL] Live file modification INVISIBLE: got 0x10 (expected 0xAA)`）；
2. **开启诊断门禁状态 (`ELFUSE_DIAG_SESSION_SHARED=1`)**：
   - `mem.c:2909` 强行将符合条件的私有文件映射转为 `MAP_SHARED` 走宿主文件覆盖层；
   - 虽然强行满足了文件修改穿透可见（Test A 伪造通过），但代价是**彻底摧毁了写时复制（COW）隔离与私有写保护**：底层文件的后续写入会直接冲刷覆盖 guest 的私有写入（Test B FAIL，`got 0xbb expected 0x55`），且 guest 的内存写入通过共享映射直接被 `msync` 回写到底层物理文件（Test C FAIL，`pread got 0x77 expected 0x10`，**存在篡改/污染物理文件的不可接受风险**，实测退出码 `exit=6`)。

---

## 二、 MAP_PRIVATE 三条核心语义在当前 elfuse 架构下的可达性清单

根据 Linux 内核标准规范（`mmap(2)`）与 POSIX 标准，对私有文件映射的三条语义在当前 `elfuse` 架构下的可达性进行逐条技术剖析：

| 语义项 | Linux 内核标准语义要求 | 当前 elfuse 架构下结论 | 所需底层技术机制与理由 |
| :--- | :--- | :---: | :--- |
| **(a) 活文件修改可见性** | 对 guest 尚未写入过的页面，底层文件的后续修改必须能实时反映在内存中 | **当前不可达<br>(Not Achievable Directly)** | **所需机制**：必须拥有针对未写页面的宿主到客体动态缺页与外部失效通道。<br>**理由**：当前走 `pread` 快照断绝了与文件缓存的联系；若走宿主 `MAP_PRIVATE`，macOS XNU 内核一旦通过读缺页将页面载入虚拟内存，后续宿主 `pwrite` 绝不向虚拟机私有页反向失效（Reverse Invalidation）。除非宿主端有文件变更监视（`kqueue`/`fsevents`）并主动逐页驱逐虚拟机 Stage-2 PTE，否则无法感知活文件修改。 |
| **(b) 写后 COW 隔离** | 一旦 guest 首次写入某一页面，该页面必须脱离底层文件独立分配，后续文件修改不再影响该页 | **部分可达 / 条件可达<br>(Partially Achievable)** | **所需机制**：Stage-2 Write-Fault 拦截器与动态物理页分裂（Split-on-Write）。<br>**理由**：在快照模式下，由于各页本身即为独立匿名内存，写后不受文件影响（因而快照模式下 Test B 能 PASS）；但在任何支持活文件穿透的共享方案中，必须将 stage-2 映射初始置为只读（Read-Only），在 guest 触发 Data Abort (Write) 时捕获异常，分配全新匿名页、复制 16KB 数据并重新挂载为 RW，方能实现真 COW。 |
| **(c) 绝不回写底层文件** | guest 对私有映射的任何写入（无论是否显式调用 `msync`），绝对不得回写到磁盘文件 | **可达<br>(Achievable)** | **所需机制**：内存与文件解耦保证。<br>**理由**：快照模式天然满足（Test C PASS）。在任何改进机制中，只要写入操作始终作用于匿名内存或未绑定宿主共享映射的副本页，即可 100% 杜绝脏数据回写底层文件。 |

---

## 三、 改动面剖析：所需组件、代码规模与全局回归风险

要在 `elfuse` 彻底实现工业级私有文件映射写时复制（COW），需要对虚拟机内存管理核心层实施深层次结构性重构：

### 1. 核心改动组件与文件范围（真实路径与函数）
1. **虚拟机二级页表与 Stage-2 映射层**：
   - `src/core/mmu.c` / `src/core/guest.c`：需要扩展 `hvf_vm_map` 与 `guest_region_t` 结构，增加 `REGION_TYPE_FILE_PRIVATE_COW` 专属标志与页级位图（`uint8_t cow_bitmap[]`）；
   - `src/syscall/mem.c` (`hvf_apply_file_overlay_quiesced`, `sys_mmap`): 增加针对私有文件映射的初始只读 stage-2 挂载逻辑；
2. **异常捕获与缺页处理引擎 (Data Abort Trap)**：
   - `src/syscall/proc.c` (`vcpu_handle_el0_fault`, `vcpu_handle_exception_exit`)：目前 `elfuse` 仅处理 `EC=0x20/0x21` 的普通缺页并向 guest 递送 `SIGSEGV`，没有内核级缺页补救循环（Demand Paging / COW Handler）；
   - 需实现：当发生 `ESR_EC_DABT_LOW` 且原因为写入只读 COW 页时，拦截异常、不递送信号、现场从文件拉取/复制 16KB 匿名块、更新 stage-2 页表权限为 RW 并恢复 vCPU 执行。
3. **文件变更动态同步桥（可选但最复杂）**：
   - 若要实现语义 (a)，需在宿主建立基于 `kqueue (VNODE_WRITE)` 的文件监控线程，在文件被改写时精确使未写页的 Stage-2 PTE 失效。

### 2. 代码改动规模评估
- 预计新增/改动核心 C 代码：**600 ~ 900 行**（涉及 `mmu.c`、`proc.c`、`mem.c`、`guest.h`）；
- 涉及底层汇编与异常恢复：需调整 `src/core/shim.S` 中的数据中止栈帧恢复逻辑。

### 3. 全局回归风险面深度评估（硬性红线）
实施上述改动存在极高的系统级回归风险：
1. **破坏已验收的匿名内存语义与堆分配**：
   - 扩展异常捕获循环极易与常规的 `SIGSEGV` 信号分发路径产生冲突，若把合法的用户态内存越界误判为 COW 异常，将导致崩溃无法上报；
2. **破坏 Futex 核心同步机制**：
   - `FUTEX_WAIT` 与 `FUTEX_WAKE` 依赖物理地址哈希桶（`futex_hash_bucket`）与单调递增的原子操作。若 COW 机制在 Futex 等待期间发生物理页重映射或地址变更，会导致等待队列失效、唤醒丢失或内核级死锁；
3. **破坏 Guest 信号帧递送与栈切换**：
   - 信号处理器运行依赖备用栈（`sigaltstack`）与精准的 `SP_EL0` 切换，异常处理器的任何时序延长都会直接影响实时信号与定时器（`setitimer`）的派发精度。

---

## 四、 验收标准设定（直接复用既有测试体系）

任何后续声称“已彻底解决私有文件映射 COW”的方案，**必须直接通过以下三项严格测试作为客观验收门槛**：

1. **测试用例 1（活文件可见性）**：
   - 运行 `scripts/runtime/private_cow/test_private_cow`，在 **未设置** `ELFUSE_DIAG_SESSION_SHARED` 环境变量下：
   - **转绿判据**：`[TEST_A_PASS] Live file modification visible: got 0xAA`；
2. **测试用例 2（写后 COW 隔离）**：
   - 运行 `scripts/runtime/private_cow/test_diag_gate`，在 **不开启破坏性门禁** 下：
   - **转绿判据**：`[DIAG_TEST_B_PASS] COW isolation intact: 0x55`；
3. **测试用例 3（绝不回写底层文件）**：
   - 在映射写入并执行 `msync` 后检查底层文件内容：
   - **转绿判据**：`[DIAG_TEST_C_PASS] File not modified: pread got 0x10`，底层文件哈希保持不变。
4. **整体退出码标准**：
   - 运行 `scripts/runtime/private_cow/run_test.py` 与 `run_diag_test.py`，两者的测试进程退出码**必须全部为 `exit: 0`**。

---

## 五、 在 macOS / Apple HVF 现有 API 下的可行性终局结论

### 1. 架构级可行性判定：**【当前不可实现完整语义 / 需替代性上层方案】**
- **判定依据**：
  1. **宿主 API 能力断层**：macOS Hypervisor.framework 仅提供粗粒度的 `hv_vm_map` 与物理页只读/可读写权限设置，不提供与 XNU 内核 Unified Buffer Cache (UBC) 的深度绑定接口；
  2. **跨平台语义矛盾**：Linux 的 `MAP_PRIVATE` 是由内核 VFS Page Cache 直接支撑的活映射；而 macOS XNU 的私有映射在实例化后即脱离文件动态更新。因此，单纯在宿主用户态“调参数”或“换 mmap 标志”**在数学逻辑与系统调用层上均无法取得原生 Linux 语义**；
  3. **投入产出比与架构稳定性**：为了一个特定于 Wine 会话通信的私有映射而在虚拟化引擎内重写一套完整的软件 MMU / Stage-2 COW 引擎，不仅工程量巨大（接近重写操作系统内核虚拟内存子系统），且会严重动摇已全绿的 Futex、信号与进程树稳定性。

### 2. 推荐的替代性工程演进方案 (Recommended Alternatives)
由于底层的物理瓶颈已被证明，在工程实践中建议采用以下更稳定、更轻量的替代路径：
1. **方案 A（会话文件宿主中继/协议桥）**：
   在 Wine 启动前，识别到需要跨组件协同的 Session 文件时，由用户态包装器（Wrapper）显式提供外部同步机制，或修改 Wine 编译配置使其在非 Linux 原生内核上使用命名管道（Named Pipe）而非私有内存段共享；
2. **方案 B（严格限定的诊断模式受控白名单）**：
   继续保留 `ELFUSE_DIAG_SESSION_SHARED=1` 作为仅在安全测试沙箱中使用的**受控诊断开关**，但在所有生产报告、接口文档中明确标注其“仅供特定 session section 诊断、具备文件回写风险”的边界，严禁扩展到普通文件。

### 3. 可反驳条件 (Falsification Conditions)
若后续有证据证明：
1. Apple 在 macOS Sequoia / 未来版本的 Hypervisor.framework 中暴露了直接监听文件 UBC 页面脏化并反向同步 Stage-2 映射的私有/公有接口；
2. 或者在不超过 150 行微小改动内、仅通过调整现有 `mem.c` 即可让上述三项自动化测试在无门禁下全部转绿（`exit 0`）且不引起 69 项后端测试任何回归；
则本“当前不可实现完整语义”的结论即被反驳。
