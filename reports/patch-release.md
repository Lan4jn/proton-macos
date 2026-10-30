# Wine Win32u Vulkan 递归重入死锁修复发布补丁包与复现报告 (v2 严格限定审计版)

- **任务编号**：task-131
- **执行角色**：wine-recovery-reviewer (Team Teammate)
- **审查目标**：将已验证通过的 win32u Vulkan 重入自死锁修复方案整理为符合上游规范、可评审、可提交的补丁发布包（`sources/patch-release/`）与完整复现指引，供工程归档与向上游 Valve/Wine 反馈。
- **发布目录**：`sources/patch-release/`
- **目标上游仓库**：`https://github.com/ValveSoftware/wine`
- **目标 Commit**：`adea6cbac9d00bb22910145354d00c463fcf3afc` (Committer: 2026-09-24T00:51:45Z)
- **结构等价区间**：`[66ee546cbea4f15d9098bc146312a818c356f9e5 .. adea6cbac9d00bb22910145354d00c463fcf3afc]`
- **源码 Pin 定性声明**：Commit `adea6cbac` 是经由结构尺寸、偏移常量及运行通过验证的**兼容基线**，并非经 Valve 官方 submodule 指针证明的唯一精确构建源。

---

## 1. 发布包工件清单与 SHA256 校验和 (Package Manifest)

发布目录 `sources/patch-release/` 下包含 5 个标准化归档文件，全部经过物理校验：

| 文件名称 | 文件大小 (Bytes) | SHA256 校验和 | 功能说明 |
| :--- | :---: | :--- | :--- |
| **`wine-vulkan-reentrancy-guard-adea6cbac.patch`** | 8,875 | `a22655b6f7b77edabbf0796fe6ad9d613a01cb2282dd27b1d09c29cadc7443a2` | 标准化 unified diff (`-p1` a/b 格式)，仅包含 reentrancy guard，**0 结构体改动** |
| **`commit-message.txt`** | 5,877 | `da330d650c7a6b15f0495a37d9bbbbb3635b9ac988ea94d97091fc22d269b0af` | 符合 Git 规范的完整提交说明，含问题、根因、defer 机制阐述与严格三方实测对照 |
| **`README.md`** | 10,113 | `bb90e048f4e9723333b0ed70785a6d6f3d464860d0df1c7e9973d008428962a7` | 包含源码 Pin 依据、端到端复现命令、构建参数、部署说明、字节对比与完整边界限制 |
| **`evidence-summary.json`** | 5,038 | `3927f2d153f46fa551ba955a3c70c3e0c0293474a3aecfa231928517ceb680fd` | 机器可读证据摘要（关键日志行号、二进制指纹、ABI 结构体偏移量、环境 caveat） |
| **`apply-check.log`** | 2,173 | `b8f91590b5bdaf04ee701f6c0cfe8ec2ff57c58501afa876a2b8f8a4d387a495` | 对 pristine 源码执行 `git apply --check`、`patch -p1 --dry-run` 及**逐文件 SHA 对比**的真实零错误输出日志 |

---

## 2. 补丁字节同一性独立审计 (Byte-Identical Verification)

为排除补丁由于路径前缀（`a/b` vs `pristine/patched`）重写或格式差异引入语义偏差，在独立工作目录中将发布补丁 `wine-vulkan-reentrancy-guard-adea6cbac.patch` 与原始实验补丁分别应用于未经修改的 pristine 源码，并与此前已构建验证的 `sources/wine-pin-adea/patched/` 源码进行全文件 SHA256 逐一哈希碰撞比对：

| 修改文件 | 真实构建源码 (`patched/`) SHA256 | 发布 Patch 应用后 SHA256 | 差异 (diff) | 语义与字节判定 |
| :--- | :--- | :--- | :---: | :---: |
| `dlls/win32u/d3dkmt.c` | `2281833cd4b95353651044b059fece64a6716fc521befca32ed0e53c576917df` | `2281833cd4b95353651044b059fece64a6716fc521befca32ed0e53c576917df` | **0 字节差异** | **IDENTICAL (完全同一)** |
| `dlls/win32u/vulkan.c` | `8bdc516db04b6a542f8a7975148622812df9167c2ee522c0c4522360dd3e336e` | `8bdc516db04b6a542f8a7975148622812df9167c2ee522c0c4522360dd3e336e` | **0 字节差异** | **IDENTICAL (完全同一)** |
| `dlls/win32u/win32u_private.h` | `7f504dd51cb94bc5e1a4eea31e431df765fd9644e797ac464c16f3cb007ec368` | `7f504dd51cb94bc5e1a4eea31e431df765fd9644e797ac464c16f3cb007ec368` | **0 字节差异** | **IDENTICAL (完全同一)** |

**结论**：发布补丁与已实测运行的原始补丁在代码内容与语义上 **100% 字节级一致**。

---

## 3. 三方二进制严格区分与实测对照 (Three-Way Binary Differentiation)

报告对三份相关 `win32u.so` 二进制实体进行严格隔离与区分，杜绝混淆：

1. **原版 Shipped 二进制 (`4f6013fa...`)**：
   - 来源：Valve 官方 Proton `experimental-11.0-20260924-arm64` 容器预制自带；
   - 作用：基线死锁复现对照组（`run-73d055tk`）；
   - 结果：在 Step 3 `vkCreateInstance` 处卡死死锁，65.12s 后看门狗超时强杀（Exit Code: 124）。
2. **Pristine adea 编译二进制 (`96de5f0a...`)**：
   - 来源：从 `adea6cbac` 源码树未经补丁直接编译；
   - 作用：**仅用于静态反汇编自检**，确证自然结构体偏移常量（`0x2f8 / 0x2e0 / 0x2e8 / 0x288 / 0x368`）与原版一致；未用于端到端动态测试。
3. **Patched adea 编译二进制 (`59a76b05...`)**：
   - 来源：从 `adea6cbac` 源码树应用本 Guard 补丁后编译；
   - 作用：修复组端到端动态验证（`run-sjo653xi`）；
   - 结果：48.18s 自然正常退出（Exit Code: 0），成功进入 Step 4/5，枚举出物理设备 `llvmpipe`。

### 对照表

| 检验项 | Shipped Original 基准组 (`FAIL`) | Patched adea6cbac 修复组 (`PASS`) |
| :--- | :--- | :--- |
| **实测运行目录** | `logs/wine-pin/shipped_baseline/run-73d055tk/` | `logs/wine-pin/patched_adea/run-sjo653xi/` |
| **测试所用二进制** | Shipped 原版 (`4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5`) | Patched adea (`59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed`) |
| **vkCreateInstance** | **未返回**（卡死在 Step 3） | **成功返回 `VK_SUCCESS`** |
| **探针推进阶段** | 停滞于 Step 3 | **完整通过 Step 1 至 Step 5** |
| **物理设备数量** | 0 个输出 | **`Physical device count: 1`** |
| **物理设备名称** | 无 | **`deviceName: llvmpipe (LLVM 23.1.1, 128 bits)`** |
| **退出状态与耗时** | **Exit Code: 124** (Watchdog 超时强杀，65.12s) | **Exit Code: 0** (自然正常退出，48.18s) |
| **终态判定 (Status)** | **DEADLOCK_REPRODUCED** | **`WIN_ARM64_VULKAN_OK`** |
| **死锁现场行号** | Line 54 (word=0) -> Line 71 (word=1) on `0x201039970` | 零阻塞等待，Guard 经 `pthread_cleanup_push/pop` 平稳清理 |

---

## 4. 关键技术 Caveats 深度核实

### 1. 运行环境诊断标记偏离 (`ELFUSE_DIAG_SESSION_SHARED=1`)
实测日志确证，基线组与补丁组运行中均包含了 `DIAGNOSTIC_SHARED_ALIAS_NOT_ABI_FIX` 输出，表明两组实验均在启用 `ELFUSE_DIAG_SESSION_SHARED=1` 环境下执行：
- **语义说明**：该环境变量是 elfuse 针对 winstation 共享节的临时别名诊断映射，与真正的 Linux private page cache copy-on-write (COW) 语义存在偏离；
- **边界划分**：本补丁验证成功排他性地证明了**进程内 Vulkan 驱动初始化递归自死锁已被彻底消除**；而跨进程 COW 内存一致性属于独立的宿主虚拟化运行时考量，两者不可混为一谈。

### 2. 编译器 TLS (`__thread`) 的动态分配认知细化
- 补丁使用 `static __thread int vulkan_init_depth;`（分配在 `.tbss` 节）消除了 POSIX 动态键表耗尽（`EAGAIN/ENOMEM`）风险；
- **边界细化**：在动态加载共享库（`dlopen` 加载 `win32u.so`）场景下，TLS 访问需经由动态线程向量 (DTV) 与 `__tls_get_addr` 机制，在某些 libc 运行时下仍可能伴随 DTV 内存块的动态分配或扩容。因此，不能简单将 `.tbss` 表述为“在所有动态链接边缘情况下绝对零内存分配”，但其完全规避了应用态显式 `pthread_key` 的生命周期管理缺陷。

---

## 5. Commit Message 全文 (commit-message.txt)

```text
win32u: Defer Vulkan GPU enumeration during driver initialization to break recursive self-deadlock

Problem:
When running Windows ARM64 Vulkan applications (such as vk_enum_arm64.exe)
under Valve Proton on Apple Silicon macOS via user-space virtualization
(HVF/elfuse), calling vkCreateInstance() causes the process to hang silently
until the watchdog kills it with a timeout (Exit Code 124).

Root Cause:
In dlls/win32u, initializing the Vulkan driver involves a cyclic dependency
between graphics driver loading and display device enumeration on the same
thread:
1. vkCreateInstance() calls __wine_get_vulkan_driver(), which invokes
   pthread_once(&init_once, vulkan_init_once). The once state transitions to
   IN_PROGRESS (word = 1).
2. vulkan_init_once() loads the user graphics driver, which calls
   lock_display_devices() -> get_vulkan_gpus().
3. get_vulkan_gpus() calls get_d3dkmt_vulkan_instance() ->
   d3dkmt_init_vulkan() -> vulkan_instance_create().
4. vulkan_instance_create() calls __wine_get_vulkan_driver(), which invokes
   pthread_once(&init_once, vulkan_init_once) on the SAME thread.
5. Because the once is already IN_PROGRESS by the calling thread, glibc/musl
   pthread_once issues futex(uaddr=0x201039970, FUTEX_WAIT_PRIVATE, val=1).
   Since the thread is waiting for itself to complete, it deadlocks permanently.

Why Deferring GPU Enumeration vs NOP or Fake Completion:
- Binary NOP: Simply patching the inner pthread_once instruction with NOP
  bypasses the initial futex wait, but causes execution to fall through into
  partially initialized driver function tables, triggering downstream secondary
  re-entrancy deadlocks on secondary once variables (e.g. 0x20102d478) or
  null pointer dereferences (e.g. ldr x1, [x8, #0x10]; br x1).
- Fake Completion: Marking the once variable completed prematurely poisons
  the once state, causing subsequent calls to assume initialization succeeded
  before function pointers are populated. This leads to unbounded tail-call
  spins (over 528,000 iterations observed in prior experiments) or crashes.
- Deferred GPU Enumeration (this patch): Semantically breaks the circular edge
  cleanly. When lock_display_devices() queries get_vulkan_gpus() while the
  current thread is already executing vulkan_init_once(), get_vulkan_gpus()
  immediately returns FALSE via is_vulkan_init_in_progress().
  The display subsystem natively falls back to get_opengl_gpus() or default
  virtual display adapters (lock_display_devices already handles FALSE
  gracefully).
  Crucially, d3dkmt_init_vulkan() is NOT invoked during this phase, meaning its
  own once state remains unpoisoned (PTHREAD_ONCE_INIT). Once primary driver
  initialization completes and the re-entrancy depth counter drops to zero,
  subsequent D3DKMT calls can legitimately create the Vulkan instance and
  enumerate physical GPUs.

Thread-Local Storage Implementation Note:
The reentrancy guard uses compiler thread-local storage
(static __thread int vulkan_init_depth;) wrapped by pthread_cleanup_push/pop.
This eliminates POSIX dynamic key table exhaustion risks (EAGAIN/ENOMEM) and
key management complexity. In dynamically loaded shared libraries (dlopen),
thread-local accesses may rely on dynamic thread vector (DTV) allocation
via __tls_get_addr; thus, .tbss does not imply absolute zero-allocation
under all dynamic linking edge cases, but it avoids manual pthread_key
allocation points.

Verification & Empirical Evidence:
- Shipped Baseline Control (logs/wine-pin/shipped_baseline/run-73d055tk/):
  * Executed with Valve shipped original win32u.so (SHA256: 4f6013fa...).
  * Line 54: ONCE_ENTRY_COUNT ts_us=1573370812999 uaddr=0x201039970 word=0
  * Line 71: ONCE_ENTRY_COUNT ts_us=1573379932582 uaddr=0x201039970 word=1
  * Thread enters FUTEX_WAIT_PRIVATE on 0x201039970 waiting on itself.
  * Hangs at Step 3 (vkCreateInstance) until timeout (Exit Code: 124).
- Patched adea6cbac Build (logs/wine-pin/patched_adea/run-sjo653xi/):
  * Executed with patched adea6cbac win32u.so (SHA256: 59a76b05...).
  * Reentrancy guard actively suppresses recursive D3DKMT instance creation.
  * Driver initializes smoothly, progresses through Step 1 to Step 5.
  * Successfully queries physical devices: "Physical device count: 1".
  * Enumerates device: "deviceName: llvmpipe (LLVM 23.1.1, 128 bits)".
  * Clean exit (Exit Code: 0, Duration: 48.18s, FINAL_STATUS: WIN_ARM64_VULKAN_OK).
- Binary & ABI Offset Verification:
  * Pristine adea6cbac build (SHA256: 96de5f0a...) verified natural struct
    alignment with shipped winevulkan.so (2786ca6f...):
    - sizeof(struct vulkan_instance) == 0x2f8 (760 bytes)
    - offsetof(physical_devices) == 0x2e0 (736 bytes)
    - offsetof(physical_device_count) == 0x2e8 (744 bytes)
    - sizeof(struct vulkan_physical_device) == 0x288 (648 bytes)
    - sizeof(struct instance) == 0x368 (872 bytes)
    - ALL_VK_INSTANCE_FUNCS count == 82
  * Zero struct layout modifications; patch modifies only thread-local depth
    counters and cleanup handlers.

Scope & Caveats:
- Target commit adea6cbac9d00bb22910145354d00c463fcf3afc represents an
  empirically verified structural and runtime compatible baseline within the
  equivalent commit range [66ee546cbea4..adea6cbac], but is not formally
  certified as Valve's exact build submodule commit.
- Verification was conducted in a runtime environment with
  ELFUSE_DIAG_SESSION_SHARED=1 active (diagnostic shared alias mapping for
  winstation sections, which diverges from true Linux private page cache COW
  semantics). The guard fix resolves in-process reentrancy deadlock, while
  cross-process COW semantics remain an orthogonal host concern.
- This patch specifically addresses the recursive self-deadlock during driver
  initialization; it does not claim upstream endorsement or to resolve all
  Vulkan compatibility issues across arbitrary applications.

```

---

## 6. 自检真实验证输出 (apply-check.log)

```text
=======================================================================
Patch Apply & Byte-Identity Verification Log
Target Patch: /Users/mewcapoo/Projects/proton-macos-lab/sources/patch-release/wine-vulkan-reentrancy-guard-adea6cbac.patch
Target Source Tree: /Users/mewcapoo/Projects/proton-macos-lab/sources/wine-pin-adea/pristine/wine-adea6cbac9d00bb22910145354d00c463fcf3afc
Target Commit: adea6cbac9d00bb22910145354d00c463fcf3afc
Timestamp: 2026-10-27T00:59:11Z
=======================================================================

=== 1. patch -p1 --dry-run Test ===
patching file 'dlls/win32u/d3dkmt.c'
patching file 'dlls/win32u/vulkan.c'
patching file 'dlls/win32u/win32u_private.h'
patch -p1 --dry-run exit code: 0

=== 2. git apply --check Test (in isolated git repository) ===
git apply --check exit code: 0

=== 3. Actual git apply & Stat ===
 M dlls/win32u/d3dkmt.c
 M dlls/win32u/vulkan.c
 M dlls/win32u/win32u_private.h

Modified lines summary:
 dlls/win32u/d3dkmt.c         |  33 +++++++++++
 dlls/win32u/vulkan.c         | 130 +++++++++++++++++++++++++++----------------
 dlls/win32u/win32u_private.h |   4 ++
 3 files changed, 120 insertions(+), 47 deletions(-)

=== 4. Byte-for-Byte SHA256 Comparison with Tested Patched Tree ===
Target A: sources/wine-pin-adea/patched/ (tested runtime build)
Target B: Freshly applied release patch on pristine adea6cbac

File: dlls/win32u/d3dkmt.c
  Tested Patched SHA: 2281833cd4b95353651044b059fece64a6716fc521befca32ed0e53c576917df
  Applied Patch  SHA: 2281833cd4b95353651044b059fece64a6716fc521befca32ed0e53c576917df
  Status: IDENTICAL (Match)

File: dlls/win32u/vulkan.c
  Tested Patched SHA: 8bdc516db04b6a542f8a7975148622812df9167c2ee522c0c4522360dd3e336e
  Applied Patch  SHA: 8bdc516db04b6a542f8a7975148622812df9167c2ee522c0c4522360dd3e336e
  Status: IDENTICAL (Match)

File: dlls/win32u/win32u_private.h
  Tested Patched SHA: 7f504dd51cb94bc5e1a4eea31e431df765fd9644e797ac464c16f3cb007ec368
  Applied Patch  SHA: 7f504dd51cb94bc5e1a4eea31e431df765fd9644e797ac464c16f3cb007ec368
  Status: IDENTICAL (Match)

VERDICT: ALL VERIFICATIONS PASSED (Clean apply, zero errors, byte-identical to tested runtime)

```

---

## 7. 本轮修订变更清单 (Changelog for Task-131 Audit)

根据 Lead 审查意见，本轮补丁发布包实施的具体修改如下：

1. **修正 Shipped Baseline 与 Pristine adea 混淆**：
   - 明确 `run-73d055tk` 运行的是 Valve 原版 shipped `win32u.so` (`4f6013fa...`)，与未打补丁源码编译的 `adea_pristine_win32u` (`96de5f0a...`) 严格分立；
2. **补充补丁应用后逐文件字节哈希同一性证明**：
   - 在独立临时目录中分别对 pristine 源码应用 release patch 与 original patch，实测输出三份修改文件的 SHA256 并证实 100% 字节匹配；
3. **披露 `ELFUSE_DIAG_SESSION_SHARED=1` 运行环境 Caveat**：
   - 在 README、commit-message、evidence-summary 与本报告中明确披露诊断映射状态，澄清其与 COW 偏离边界；
4. **收敛 Commit adea 的来源定性**：
   - 将“唯一精确构建源”更正为“经结构与运行验证的兼容基线区间 [66ee546cbea4..adea6cbac] 的代表提交”；
5. **细化 TLS 动态分配风险陈述**：
   - 纠正了 `.tbss` 即意味着“绝对零分配”的过强陈述，指出 dlopen/DTV 机制下的潜在动态分配特征。
