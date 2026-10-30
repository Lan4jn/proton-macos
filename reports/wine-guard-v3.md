# Wine 初始化防重入 Guard v3 验证与三层定性报告

- **任务编号**：task-114
- **执行角色**：wine-guard-verifier (Team Teammate)
- **审查与验证目标**：
  1. 根治 v2 因动态资源分配（pthread_key_create / pthread_setspecific）导致的 **Callback Once-Poisoning（单次初始化污染）** 致命架构缺陷；
  2. 采用编译器原生线程局部存储（__thread 深度计数器），消除 Guard 对 POSIX 动态 TLS 键的依赖；
  3. 执行 AArch64 Linux ELF 与 Mach-O 交叉 TLS Section 及重定位类型验证；
  4. 从打好 v3 补丁的真实应用源码中物理截取 Guard 与 Callback 控制流，在真实回调内部完整词法配对 pthread_cleanup_push / pthread_cleanup_pop；
  5. 明确三层验证状态：Host native PASS / AArch64 object PASS / Linux ELF runtime NOT_RUN，恪守科学边界，不宣称无条件运行时可用。
- **实验工件根目录**：/Users/mewcapoo/Projects/proton-macos-lab
- **关联工件与物理哈希**：
  - 机器可读综合收据：logs/wine-guard-v3/receipt.json
  - v3 标准候选补丁：sources/wine-init-guard-v3/wine_vulkan_reentrancy_guard_v3.patch (8,694 字节, SHA256: ba06a9ba493ec204babd40b9c70b970bfce7ababa6541f5508510f5578818895)
  - 自动提取真实源码：sources/wine-init-guard-v3/extracted_guard_v3.c (SHA256: c55dc8679508f3057bb3807f9a2543f2d0ce35c13d471f632bf4e3fb9c42d750)
  - 提取脚本：scripts/runtime/wine_guard_v3/extract_guard_v3.py
  - 完整回归套件：scripts/runtime/wine_guard_v3/run_guard_v3_suite.py
  - 8 大场景原生测试源码：sources/wine-init-guard-v3/test_guard_v3.c (SHA256: 4141bdd43f3b9fea5617278abe8f25f32e69d714e063a2f246fd776e1bf4f948)
  - 测试套件全量日志：logs/wine-guard-v3/test_guard_v3.log
  - 交叉编译 ELF TLS 探针目标：sources/wine-init-guard-v3/test_tls_probe_pic.o
  - 交叉链接 ELF 动态库目标：sources/wine-init-guard-v3/libguard_tls.so

---

## 1. 核心分层裁定矩阵 (Layered Scope Verdicts)

按 Team Lead 审查标准，明确界定三层验证事实与边界状态，严禁无条件泛称“PASS 整合”：

| 检验层次 / 维度 | 裁定结果 | 详细依据与技术边界 |
| :--- | :---: | :--- |
| **第一层：Host Native 测试** | **PASS** | 基于原生提取代码与最小 shim，8/8 用例全部通过（exit 0）。同线程深度平衡、两线程条件变量隔离、真实回调控制流、回调内取消清理、动态 key 错误注入免疫、Once-Poisoning 根治验证完毕。 |
| **第二层：AArch64 Object 静态验证** | **PASS** | 经 clang -target aarch64-linux-gnu -fPIC 交叉编译，成功生成 .tbss 节与 R_AARCH64_TLSDESC 静态重定位；经 ld.lld -nostdlib -shared 交叉链接，成功生成包含 R_AARCH64_TLSDESC 的动态共享库 libguard_tls.so。 |
| **第三层：Linux ELF Runtime 动态运行** | **NOT_RUN** | 尚未在实际 AArch64 Linux / elfuse + glibc 运行时环境中执行动态加载验证（见第 6 节下一阶段实验规划）。 |
| **Guard 资源失败语义客观界定** | **QUALIFIED** | 采用 __thread 彻底消除了应用层调用 pthread_key_create / setspecific 的运行期分配失败，但**动态库 PIC TLS (TLSDESC) 在首次访问时仍依赖动态链接器 (ld.so) 分配 DTV (Dynamic Thread Vector)**，在极度缺内存时仍有潜在分配风险，不可泛称“绝无任何资源失败”。 |
| **v2 RED → v3 GREEN 回归** | **PASS** | v2 用例 8 中因动态 key 失败引发的 pthread_once 永久污染在 v3 中被彻底消除。首次调用正常初始化，二次调用返回缓存，底层调用计数为 1。 |
| **嵌套调用深度平衡 (Depth Balancing)** | **PASS** | 采用整型计数器替代 v2 单布尔标记，嵌套进入后退出内层，外部临界区仍受保护（depth=1 > 0），外层退出后归零。 |
| **真实 Callback 内部取消注册** | **PASS** | vulkan_init_once 与 d3dkmt_init_vulkan 实际源码内部词法作用域完整嵌入 pthread_cleanup_push / pthread_cleanup_pop(1)，重构为单一出口，无任何 goto/return 跨越宏范围。 |
| **Wine 完整动态库构建 (Full Build)** | **NOT_RUN** | 隔离实验环境中无完整 Wine 构建依赖与 configure 配置，恪守规则标记 full_build=not_run。 |
| **GDI Display Cache 自然恢复** | **UNKNOWN** | GDI 缓存恢复仍取决于外部显示事件（WM_DISPLAYCHANGE），状态维持 UNKNOWN。 |
| **Wine 全链路调用与死锁解决** | **UNKNOWN** | 仅证明 Guard 本体及其直接 Callback 控制流在隔离单元测试中自洽，不妄称 Wine 全链路死锁已解决。 |

---

## 2. 机制选型与 ELF TLS 静态验证事实

### 2.1 选型依据
针对 v2 暴露的“运行时资源准备失败导致业务 once 永久完成”缺陷，评估并确立了**编译器原生线程局部存储（__thread）**为最小且最优解：
- 避免二次 once 掩盖：若仍采用 POSIX pthread_key_t，将可失败资源放在业务 pthread_once 之外，依然需要一个前置的 key_once；若 key_once 失败，仍会导致永久不可用，无法达成真正的重试；
- 避免运行期显式 key 创建与注销开销。

### 2.2 AArch64 ELF 静态重定位与共享库生成事实
- 探针源码：sources/wine-init-guard-v3/test_tls_probe.c
- 交叉编译命令：`clang -target aarch64-linux-gnu -fPIC -c test_tls_probe.c -o test_tls_probe_pic.o`
- 静态重定位检验（objdump -r test_tls_probe_pic.o）：
  - RELOCATION RECORDS FOR [.text]:
    - 0000000000000008 R_AARCH64_TLSDESC_ADR_PAGE21 vulkan_init_depth
    - 000000000000000c R_AARCH64_TLSDESC_LD64_LO12 vulkan_init_depth
    - 0000000000000010 R_AARCH64_TLSDESC_ADD_LO12 vulkan_init_depth
    - 0000000000000014 R_AARCH64_TLSDESC_CALL vulkan_init_depth
  - 节区检验（objdump -h）：
    - .tbss: 00000004 0000000000000000 BSS
- 交叉链接共享库（使用 tools/elfuse/bin/ld.lld）：
  `clang -target aarch64-linux-gnu -fuse-ld=/opt/homebrew/Cellar/lld@21/21.1.8_1/bin/ld.lld -nostdlib -shared test_tls_probe_pic.o -o libguard_tls.so`
- 动态重定位检验（objdump -R libguard_tls.so）：
  - DYNAMIC RELOCATION RECORDS:
    - 0000000000020528 R_AARCH64_TLSDESC *ABS*

---

## 3. 真实应用源码 Callback 重构与取消清理

在 upstream 真实源码中重构 vulkan_init_once 与 d3dkmt_init_vulkan，引入标准的 POSIX 取消与异常清理保护：

```c
/* d3dkmt.c 实际重构代码 */
static void d3dkmt_init_vulkan(void)
{
    static const struct vulkan_instance_extensions extensions =
    {
        .has_VK_KHR_get_physical_device_properties2 = 1,
        .has_VK_KHR_external_memory_capabilities = 1,
    };

    d3dkmt_init_guard_enter();
    pthread_cleanup_push( d3dkmt_init_guard_cleanup, NULL );

    d3dkmt_vulkan_instance = vulkan_instance_create( &extensions );
    if (!d3dkmt_vulkan_instance) WARN( "Failed to create the vulkan instance\n" );

    pthread_cleanup_pop( 1 );
}
```

在 vulkan.c 的 vulkan_init_once 中，消除原先杂乱分散的 return 与 goto failed，重构为嵌套条件分支与 break 结构，确保：
- 无任何 return 或 goto 跨越 pthread_cleanup_push / pthread_cleanup_pop 宏的作用域；
- 无论初始化成功、发生错误、抑或在取消点被取消，pthread_cleanup_pop(1) 均保证 Guard 计数绝对归零。

---

## 4. 8 大场景测试汇总与 v2 RED → v3 GREEN 映射

| 测试用例 / 场景 | v2 行为与结果 | v3 行为与结果 | 架构演进与根治机制 |
| :--- | :--- | :--- | :--- |
| **场景 7 (Once-Poisoning 回归)** | **FAIL (Exit 134 / SIGABRT)**<br>动态 key_create 失败使回调直接 return，外层 pthread_once 标为完成，二次调用永久为 NULL。 | **PASS (GREEN)**<br>首次调用返回有效实例（0x10257c000），二次调用返回缓存，底层调用计数为 1。 | 采用原生 TLS，消除运行期分配，动态 key 错误注入对 Guard 零影响。 |
| **场景 3 (嵌套调用支持)** | **RESTRICTED**<br>单布尔标记在内层 exit 时误将 TLS 归零，外层失保。 | **PASS (GREEN)**<br>采用整型计数器，内层 exit 深度为 1，外层保持保护，外层 exit 深度归零。 | 严格支持任意深度的同线程嵌套调用与平衡展开。 |
| **场景 5 (实际取消点清理)** | **UNKNOWN**<br>源码未注册 cleanup，仅 harness 单独测试。 | **PASS (GREEN)**<br>工作线程在回调内部被取消，pthread_cleanup_push 强制重置深度至 0。 | 真实源码回调内部完整嵌入清理块。 |
| **场景 6 (动态 Key 免疫)** | **N/A**<br>v2 依赖 key。 | **PASS (GREEN)**<br>验证 pthread_key_create 调用次数为严格的 0。 | 完全脱离 POSIX 动态 TLS 键子系统。 |
| **场景 8 (业务失败契约)** | **N/A** | **PASS (GREEN)**<br>底层返回 NULL 时，二次调用依然返回 NULL，符合原版 Wine 业务契约。 | 仅消除 Guard 引入的资源缺陷，不改动业务 Vulkan 既有语义。 |

---

## 5. 交付工件与指纹清册

```text
├── sources/wine-init-guard-v3/
│   ├── wine_vulkan_reentrancy_guard_v3.patch (SHA256: ba06a9ba493ec204babd40b9c70b970bfce7ababa6541f5508510f5578818895, 246 行)
│   ├── extracted_guard_v3.c                  (SHA256: c55dc8679508f3057bb3807f9a2543f2d0ce35c13d471f632bf4e3fb9c42d750)
│   ├── test_guard_v3.c                       (SHA256: 4141bdd43f3b9fea5617278abe8f25f32e69d714e063a2f246fd776e1bf4f948)
│   ├── test_guard_v3                         (ARM64 Mach-O 原生测试二进制, 8/8 PASS)
│   ├── test_tls_probe.c                      (ELF TLS 探针源码)
│   ├── test_tls_probe_pic.o                  (AArch64 Linux ELF 静态重定位验证目标文件)
│   └── libguard_tls.so                       (AArch64 Linux ELF 动态链接库目标文件)
├── scripts/runtime/wine_guard_v3/
│   ├── extract_guard_v3.py                   (物理提取真实源码 Guard 与 Callback 流)
│   └── run_guard_v3_suite.py                 (自动化端到端测试与收据生成套件)
├── logs/wine-guard-v3/
│   ├── extraction_meta.json                  (提取行号与源码哈希元数据)
│   ├── test_guard_v3.log                     (8 大场景执行全量日志)
│   └── receipt.json                          (机器可读综合收据)
└── reports/wine-guard-v3.md                  (本报告)
```

---

## 6. 下一阶段可执行实验前置条件与规划建议

Lead 提出的下一可执行实验规划：**Guest 动态 glibc + __thread 动态共享库 dlopen/dlsym + 两 pthread 隔离/depth/cleanup 验证**。

### 6.1 工具链与环境可行性勘测
1. **交叉编译器与链接器**：
   - 编译器：`clang -target aarch64-linux-gnu` 可用；
   - 链接器：`/opt/homebrew/Cellar/lld@21/21.1.8_1/bin/ld.lld` 与 `./tools/elfuse/bin/ld.lld` (LLD 21.1.8) 均已就绪，实测可生成符合 AArch64 ELF 规范的共享库；
2. **Guest libc 与动态链接器**：
   - 物理路径：`sources/elfuse-derived/externals/test-fixtures/glibc/2.36-9+deb12u14/libc.so.6` 与 `ld-linux-aarch64.so.1` 均存在；
3. **执行引擎**：
   - 物理路径：`sources/elfuse-derived/build/elfuse` 可用。

### 6.2 建议步骤
在后续任务中，可构建独立的最小 guest 探针 `guest_tls_runner`（包含主执行文件与 `libguard_tls.so`），由 `elfuse` 加载运行，完成真正的 Linux ELF 动态运行时验证。
