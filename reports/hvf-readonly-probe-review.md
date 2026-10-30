# HVF 只读宿主页映射对照探针独立复审报告

## 1. 任务背景与复审边界
- **实验目标**：探究在 macOS Apple Silicon 上，当宿主文件以 `O_RDONLY` + `PROT_READ` + `MAP_SHARED` 映射时，调用 Hypervisor.framework 的 `hv_vm_map` 赋予 `HV_MEMORY_READ`（只读）权限是否能够通过内核准入（Host API Admission），还是同样被内核拒绝（返回错误码）。
- **前序背景**：此前 `mem.c`（2312-2448）中 host 文件 overlay 采用 `PROT_READ|PROT_WRITE` + `MAP_SHARED|MAP_FIXED`，`hv_vm_map` 统一采用 `HV_MEMORY_READ|HV_MEMORY_WRITE|HV_MEMORY_EXEC`，导致 `O_RDONLY` 被预先排除。本实验聚焦于纯粹的 Host API 准入判定，不假定旧 RWX 的失败等同于 R-only 也会失败。
- **复审约束**：
  - Lead 仅负责协调、代码复核、纯测试核验与真实日志收据审查，不替执行员编写实现。
  - 范围严格限制在 `scripts/runtime/hvf_readonly_probe/`、`fixtures/runtime/hvf-readonly-probe/`、`logs/hvf-readonly-probe/`、`reports/hvf-readonly-probe.md`。
  - 严禁触碰任何真实 Steam/系统/全局包，禁止修改原 elfuse/Proton 源码，禁止 commit/push。
  - 即使 API 准入成功，亦不代表 guest 数据可读、Linux ABI 一致性或 Wine 已修复；本实验不包含 vCPU/guest 执行、Wine 或长负载。

---

## 2. 代码与安全规范复审

### 2.1 独立微探针 C 实现 (`scripts/runtime/hvf_readonly_probe/probe.c`)
- **生命周期管理**：
  - 调用 `hv_vm_create(NULL)` 显式创建独立的 VM 实例，并在退出前调用 `hv_vm_destroy()`。
  - 4 个 sequential case 均使用同一个对齐的中间物理地址 `IPA_ALIGNED = 0x20000000ULL`，映射长度为 `MAP_SIZE = 65536ULL`（4 个 16KB 宿主物理页）。
  - 采用动态检测 `getpagesize()`（Apple Silicon 上实测 `16384` 字节），严格核验宿主 mmap 地址页对齐。
- **安全映射与资源复用保护**：
  - 宿主 mmap 均由操作系统自动分配（`mmap(NULL, ...)`），未采用 `MAP_FIXED` 覆盖未知宿主虚拟地址。
  - 映射清理逻辑严格遵守防御式设计：**仅在 `hv_vm_map` 成功返回 `HV_SUCCESS` 时，才调用 `hv_vm_unmap`**；若 `hv_vm_map` 失败，则不盲目调用 unmap。
  - 一旦出现 unmap 失败或 munmap 失败等未知资源状态，探针立即中断后续所有 case（`abort_further_cases = true`），严禁盲目复用（Blind Reuse）。
  - 探针全程未向文件映射区执行任何写操作，确保文件不可变性。

### 2.2 签名与 Entitlement (`fixtures/runtime/hvf-readonly-probe/entitlements.plist`)
- 仅申请了 Hypervisor.framework 必需权限：
  ```xml
  <dict>
      <key>com.apple.security.hypervisor</key>
      <true/>
  </dict>
  ```
- 签名仅应用于新构建的二进制文件 `fixtures/runtime/hvf-readonly-probe/probe`，原项目及系统组件未受任何影响。

### 2.3 分类器与单测套件 (`classifier.py`, `test_classifier.py`)
- 分类器涵盖 5 大类核心准入与异常条件：
  1. `ADMITTED`：正对照（Case A 与 Case D）成功，且只读映射（Case B）成功。
  2. `REJECTED`：正对照成功，且只读映射（Case B）被 HVF 内核拒绝（`0xfae94001`）。
  3. `INCONCLUSIVE`：正对照失败（Case A 或 Case D 失败）、VM 创建失败或测试 case 不完整（缺项）。
  4. `CLEANUP_FAILURE`：unmap/munmap/vm_destroy 失败，资源状态异常。
- 11 个独立单元测试覆盖了各种分支边界，经 Lead 独立运行确认全部 PASS（11/11）。

---

## 3. 真实运行证据核验 (Ground Truth Receipts)

### 3.1 关键构件 SHA-256 完整性记录
- **探针源码 SHA-256** (`probe.c`)：
  `eb7cd40a0a1e108734223d0b2d849ec5fdec3dbd1a655d196a2bd594bb52d81c`
- **编译构件 SHA-256** (`probe`)：
  `3694ff312e47ac9d92e7bb8e1909d9d45d4d8c5cefbcb7e1062d81b6270e42d3`
- **宿主文件 SHA-256 运行前后校验** (`backing_seed.bin`, 65536 字节)：
  - 运行前：`1fde717d808c7e06c2e08ea843c4c8214ba82e63ff07ab731a2da3bd489e15de`
  - 运行后：`1fde717d808c7e06c2e08ea843c4c8214ba82e63ff07ab731a2da3bd489e15de`
  - **结论**：哈希严格匹配，实测运行期间宿主文件未被污染或更改。

### 3.2 真实单次探针运行数据 (`logs/hvf-readonly-probe/probe.jsonl`)
- **VM 实例**：`hv_vm_create` 返回 `0x00000000` (HV_SUCCESS)，`hv_vm_destroy` 返回 `0x00000000` (HV_SUCCESS)。
- **各测试用例实测对照表**：

| Case ID | 映射类型与宿主权限配置 | 映射标志与地址对齐 | 请求的 HV 内存权限 | `hv_vm_map` 返回值 | `hv_unmap` 返回值 | 判定结果 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Case A**<br>(匿名正对照) | 匿名内存<br>`PROT_READ\|PROT_WRITE`<br>`MAP_ANON\|MAP_PRIVATE` | 宿主页: 16KB<br>IPA: 0x20000000<br>对齐: YES | `HV_MEMORY_READ \|`<br>`HV_MEMORY_WRITE \|`<br>`HV_MEMORY_EXEC` (0x7) | `0x00000000`<br>(HV_SUCCESS) | `0x00000000`<br>(HV_SUCCESS) | **OK (通过)** |
| **Case B**<br>(只读目标组) | 文件只读<br>`O_RDONLY`<br>`PROT_READ`<br>`MAP_SHARED` | 宿主页: 16KB<br>IPA: 0x20000000<br>对齐: YES | `HV_MEMORY_READ`<br>(0x1) | `0xfae94001`<br>(HV_ERROR) | *未调用*<br>(符合防御原则) | **MAP_FAILED<br>(拒绝准入)** |
| **Case C**<br>(只读对比组) | 文件只读<br>`O_RDONLY`<br>`PROT_READ`<br>`MAP_SHARED` | 宿主页: 16KB<br>IPA: 0x20000000<br>对齐: YES | `HV_MEMORY_READ \|`<br>`HV_MEMORY_WRITE \|`<br>`HV_MEMORY_EXEC` (0x7) | `0xfae94001`<br>(HV_ERROR) | *未调用*<br>(符合防御原则) | **MAP_FAILED<br>(拒绝准入)** |
| **Case D**<br>(文件读写正对照) | 文件可读写<br>`O_RDWR`<br>`PROT_READ\|PROT_WRITE`<br>`MAP_SHARED` | 宿主页: 16KB<br>IPA: 0x20000000<br>对齐: YES | `HV_MEMORY_READ \|`<br>`HV_MEMORY_WRITE \|`<br>`HV_MEMORY_EXEC` (0x7) | `0x00000000`<br>(HV_SUCCESS) | `0x00000000`<br>(HV_SUCCESS) | **OK (通过)** |

---

## 4. 复审分析与核心结论

1. **正对照完全成立**：
   - Case A（匿名宿主 RWX 映射）与 Case D（宿主文件 RWX 映射）均成功获得准入（返回 `0x00000000`），并成功完成 unmap，证明实验环境中的 Hypervisor.framework 权限、代码签名、内核接口调用通道及物理/中间物理地址对齐完全有效。
2. **只读宿主页内核拒绝准入锁定**：
   - 在正对照有效的前提下，Case B 显示：即使 `hv_vm_map` 仅请求 `HV_MEMORY_READ`，当底层宿主虚拟内存页仅具备 `PROT_READ` 且由只读文件（`O_RDONLY`）backing 时，macOS Hypervisor 内核 API 仍然拒绝准入，明确返回错误码 `0xfae94001` (HV_ERROR)。
   - 该现象并非参数配置不当导致，因为同样的 backing seed 文件在以 `O_RDWR` + `PROT_READ|PROT_WRITE` 打开并映射时（Case D）能够立刻成功准入。
3. **架构与设计指导意义**：
   - **否定了“降低 hv_vm_map 权限到 HV_MEMORY_READ 即可支持宿主只读文件页”的直接假设**。macOS HVF 内核内部在 stage-2 EPT/NPT 映射建立时，对底层 Mach/BSD 宿主虚拟内存页的权限存在更底层的硬性校验或约束（要求宿主映射具备写权限或特定的 vm_map_entry 属性）。
   - **禁止盲目直接 patch**：在没有进一步隔离机制（例如 private shadow COW、匿名中转页或只读内存重构）前，原 `mem.c` 2312-2448 中预先排除 `O_RDONLY` 并强制要求 `PROT_READ|WRITE` 属于底层内核限制驱动的行为。不可在宿主层对只读文件直接开启 `hv_vm_map`。

---

## 5. 验收结论与状态
- **子卡交付质量**：符合全部实验边界规范，单测 100% 通过，数据完备无遗漏，未发生任何非预期修改。
- **任务看板同步**：子卡任务 `a703d2eb-2fb0-4120-9c53-798a68a10d5e` 已正式核验完成并记录为 `done`。
- **验收评定**：**复审通过 (PASSED)**。
