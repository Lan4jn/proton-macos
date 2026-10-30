# 定位安装适配器 Vulkan 负9错误并恢复 CPU 枚举验证报告 (task-133)

- **任务编号**：task-133
- **执行角色**：wine-guard-verifier (Proton macOS Lab Team)
- **核心结论**：**`VK_RESULT_MINUS_9_ROOT_CAUSE_CONFIRMED_AND_ENUMERATION_RESTORED`**

---

## 1. 核心判定与执行摘要 (Executive Summary & Verdict)

> **分层状态判定 (Layered Verdicts)**：
> - **安装计划管线 (`installation_pass`)**：**PASS**（计划生成、部署、校验与完全回滚全生命周期 100% 验证）
> - **适配器执行管线 (`adapter_execution_pass`)**：**PASS**（源目录移走后，安装目标 wrapper 独立拉起 elfuse + Linux Python + Proton + Wine）
> - **Vulkan CPU 设备枚举 (`vulkan_enumeration_pass`)**：
>   * **Trial A (未修复基线)**：**FAIL** (VkResult=-9 / exit 12，首错为缺少 Guest 动态库搜索路径导致驱动加载失败)
>   * **Trial B (已修复组)**：**PASS** (VkResult=0 / exit 0，成功枚举 llvmpipe CPU 物理设备)

---

## 2. 根因物理证据分析 (Smoking Gun & Loader Root Cause)

### 2.1 动态链接器首错日志 (Trial A Raw Error)
在开启 `VK_LOADER_DEBUG=all` 的基线运行中，Vulkan Loader 输出直接捕获到驱动加载崩溃点：
```text
[Vulkan Loader] ERROR | DRIVER: loader_icd_scan: Failed loading library associated with ICD JSON /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/lib/libvulkan_lvp.so. Ignoring this JSON
[Vulkan Loader] ERROR | DRIVER: vkCreateInstance: Found no drivers!
0024:warn:vulkan:win32u_vkCreateInstance Failed to create vulkan instance, res -9
```

### 2.2 深入符号与依赖解析确证
使用 `llvm-readelf -d` 与 Python `ctypes.CDLL` 在 Linux Guest 环境下单步加载测试：
1. `libvulkan_lvp.so` 声明了动态链接依赖：`0x0000000000000001 (NEEDED) Shared library: [libLLVM.so.23.1]`；
2. `libvulkan_lvp.so` 本身**无任何 RPATH 或 RUNPATH**；
3. sysroot (`fixtures/runtime/arch-case/usr/lib`) 仅内置了 `libLLVM.so.22.1`，而配套的 `libLLVM.so.23.1` 位于独立目录 `fixtures/runtime/lavapipe-derived/usr/lib`；
4. 在未配置 Guest `LD_LIBRARY_PATH` 时直接调用 `dlopen`，Linux 动态链接器直接报错：
   `OSError: libLLVM.so.23.1: cannot open shared object file: No such file or directory`；
5. 驱动库加载失败后，Vulkan Loader 判定为无可用驱动，向 Wine 返回 `VK_ERROR_INCOMPATIBLE_DRIVER (-9)`，导致 `vk_enum_arm64.exe` 退出码为 12。

### 2.3 宿主与客态安全隔离冲突机制
- **宿主防护机制**：`scripts/backend/process.py`（第 42-44 行）对宿主传入的 `extra_env` 进行严格白名单过滤：`if 'LD_PRELOAD' in k or 'LD_LIBRARY_PATH' in k: raise ValueError('Host loader injection variables are excluded')`，保护宿主 macOS 环境免受动态库注入攻击；
- **隔离穿透缺失**：此前 `steam_handoff.py` 未提供针对 Guest 环境的独立参数通道，试图将 `LD_LIBRARY_PATH` 混入宿主 `diagnostic_env` 导致被宿主拦截，移除后又导致客态缺失，从而引发了 -9 错误；
- **最小合法解**：在 `steam_handoff.py` 中引入 `guest_env` 参数，**严格在宿主隔离层外将键值转为 `elfuse` 的 `--env KEY=VALUE` 命令行参数**，直接注入至 Guest Linux 解释器前，既保证宿主 100% 免疫注入，又为客态动态链接器提供必需的库解析路径。

---

## 3. 严格单变量对照实验物理证据 (Strict Single-Variable Experiment)

### 3.1 严格固化的一致环境 (Controlled Identical Environment)
两组 Trial 均在安装目标目录运行（源目录在执行前已彻底移走 `source_pkg_MOVED_AWAY`），且严格共享以下环境：
1. **Prefix 完全一致**：均克隆自 `fixtures/runtime/futex-args-vulkan/pfx`，且保留 `creation_sync_guard`，规避 `setup_prefix` 重复写入；
2. **default_pfx 完整在位**：工具树内均完整同步 `files/share/default_pfx_arm64`，双双跳过耗时 40-50s 的全量 `wineboot`；
3. **模块指纹完全相同**：`win32u.so` (`59a76b05...`)、`winevulkan.so` (`2786ca6f...`)、`elfuse` (`81803322...`)；
4. **宿主诊断门控一致**：均开启 `ELFUSE_DIAG_SESSION_SHARED=1`（维持 winstation 会话共享别名映射）。

### 3.2 唯一变更变量 (Unique Changed Variable)
- **唯一变量**：`guest_env['LD_LIBRARY_PATH']`（仅在 Trial B 中注入 `fixtures/runtime/lavapipe-derived/usr/lib:...`）。

### 3.3 运行结果详细对比表 (Comparison Matrix)

| 关键观测维度 | Trial A (Baseline 未修复组) | Trial B (Fixed 已修复组) | 判定与差异说明 |
| :--- | :--- | :--- | :--- |
| **Guest 注入环境** | `{'VK_LOADER_DEBUG': 'all'}` | `{'LD_LIBRARY_PATH': '.../lavapipe-derived/usr/lib:...', 'VK_LOADER_DEBUG': 'all'}` | **唯一自变量** |
| **Wrapper 运行耗时** | 45.54s | 47.36s | 两组耗时一致（均无重复 wineboot） |
| **Loader 动态链接** | 抛出 `Failed loading library ... libvulkan_lvp.so` | 成功 dlopen，无错误 | 根因行消除 |
| **VkInstance 状态** | `ERROR: vkCreateInstance failed! VkResult=-9` | `SUCCESS: VkInstance created at 0x007d1be0` | 实例创建成功 |
| **物理设备计数** | 未到达 (0) | `Physical device count: 1` | 成功获取物理设备 |
| **枚举设备名称** | 未到达 (None) | `llvmpipe (LLVM 23.1.1, 128 bits)` | 确认 CPU lavapipe 驱动 |
| **最终状态标记** | 未到达 | `FINAL_STATUS: WIN_ARM64_VULKAN_OK` | 阶段完成 |
| **子进程退出码** | **Exit 12** | **Exit 0** | 恢复正常退出 |
| **枚举分层判定** | **FAIL** | **PASS** | 明确分层，不泛化 SUCCESS |

### 3.4 Trial B 真实探针标准输出证据 (Raw stdout.log)
```text
==========================================================
[WIN_ARM64_VK] Starting Windows ARM64 Vulkan Enumeration Test
==========================================================
[WIN_ARM64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
[WIN_ARM64_VK] SUCCESS: vulkan-1.dll loaded at 0xfc4f0000
[WIN_ARM64_VK] Step 2: Resolving Vulkan function pointers...
[WIN_ARM64_VK] SUCCESS: All function pointers resolved.
[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
[WIN_ARM64_VK] SUCCESS: VkInstance created at 0x007d1be0
[WIN_ARM64_VK] Step 4: Querying physical device count...
[WIN_ARM64_VK] Physical device count: 1
[WIN_ARM64_VK] Step 5: Getting physical device properties for device 0...
[WIN_ARM64_VK] Device Properties:
  - deviceName: llvmpipe (LLVM 23.1.1, 128 bits)
  - deviceType: 4 (VK_PHYSICAL_DEVICE_TYPE_CPU)
  - vendorID  : 0x00000005
  - deviceID  : 0x00000000
  - apiVersion: 1.4.354
[WIN_ARM64_VK] SUCCESS: Verified CPU lavapipe/llvmpipe device.
[WIN_ARM64_VK] VkInstance destroyed cleanly.
==========================================================
[WIN_ARM64_VK] FINAL_STATUS: WIN_ARM64_VULKAN_OK
==========================================================
```

---

## 4. TDD 测试套件与回归验证 (TDD Verification & Full Suite Pass)

在 `tests/backend/test_steam_handoff.py` 中新增 5 个专项用例，严格验证各项安全边界：
1. `test_guest_env_injected_into_elfuse_argv`: 验证 `--env KEY=VALUE` 注入在 `linux_python` 之前；
2. `test_guest_env_validation_rejects_invalid_inputs`: 覆盖非 dict 类型、非字符串、key 包含 `=`、key/value 包含 NUL 字节、空 key 等场景，均显式抛出 `TypeError`/`ValueError`；
3. `test_guest_env_bidirectional_isolation`: 确证宿主环境不接收客态变量，且宿主 `diagnostic_env` 试图传入 `LD_LIBRARY_PATH` 时仍被 `process.py` 原规则拦截；
4. `test_guest_env_preserves_spaces_and_unicode_verbatim`: 确证空格与中文路径等 Unicode 参数保持原样不被截断；
5. `test_empty_guest_env_preserves_legacy_argv`: 确证空字典或 None 保持旧有 `argv` 结构一致。

### 全量测试执行真实命令与输出
```bash
python3 -m unittest discover -s tests/backend -p "test_*.py" -v
```
控制台真实输出结果：
```text
----------------------------------------------------------------------
Ran 90 tests in 6.169s

OK
```
**测试结论**：既有 84 项测试 + 新增 6 项测试合计 **90 项测试 100% 稳定通过**，0 失败、0 回归。
包括消除脆弱魔数 `insert_idx=7` 的专项回归测试 `test_guest_env_unmatched_interpreter_blocks_with_exit_20`：当 `linux_python` 无法在 plan argv 定位时，显式阻断并以退出码 20 报错，彻底杜绝静默错误注入。

---

## 5. 完整性回滚与限定观测锚点验证 (Rollback & Bounded Host Verification)

1. **字节级精确回滚验证**：
   - Trial A 回滚报告：`rollback_report.json` 状态为 `success`，前后树指纹逐字节完全一致；
   - Trial B 回滚报告：`rollback_report.json` 状态为 `success`，前后树指纹逐字节完全一致。
2. **限定观测范围锚点确证**：
   - 严格限定观测范围为：`~/Library/Application Support/Steam`、`~/Library/Application Support` 与 `/Applications`；
   - 运行前后顶层条目快照比对证实：**锚点目录顶层文件名无任何增删，未触及真实 Steam（注：本检查证实顶层条目无名称增删，不泛化证明宿主系统全部文件内容零修改）**。

---

## 6. 证据索引清册 (Evidence Manifest)

| 证据类别 | 物理文件路径 | 关键校验和 / 记录 | 说明 |
| :--- | :--- | :--- | :--- |
| **对照实验收据** | `logs/adapter-vulkan-config/receipt.json` | `status: COMPLETED` | 包含两组分层判定与参数 |
| **Trial A 标准输出** | `logs/adapter-vulkan-config/runs/trial_a_unfixed/stdout.log` | `VkResult=-9` | 包含失败现场输出 |
| **Trial A 错误输出** | `logs/adapter-vulkan-config/runs/trial_a_unfixed/stderr.log` | `Found no drivers!` | 包含 Loader 驱动加载失败根因行 |
| **Trial B 标准输出** | `logs/adapter-vulkan-config/runs/trial_b_fixed/stdout.log` | `WIN_ARM64_VULKAN_OK` | 包含 Step 1-5 完整枚举输出 |
| **Trial B 错误输出** | `logs/adapter-vulkan-config/runs/trial_b_fixed/stderr.log` | `exit_group x0=0x0` | 包含正常退出调用跟踪 |
| **单变量验证脚本** | `scripts/backend/run_adapter_vulkan_config.py` | - | 完整复现实验执行脚本 |
| **补丁源模块** | `sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so` | `59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed` | 自然对齐补丁库 (9.0MB) |
| **原版配套 Vulkan** | `fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/winevulkan.so` | `2786ca6f5f440821972e91a371e609d2d482597a8b6d75bcf02e287f83eea9ab` | Shipped 原版配套库 |
| **宿主运行时** | `sources/elfuse-once-panorama2-derived/build/elfuse` | `8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda` | 开启诊断会话共享映射 |
| **测试探针程序** | `fixtures/runtime/futex-args-vulkan/pfx/drive_c/vk_enum_arm64.exe` | `f82f4e7987ae1dc4ef20674c2f24809b4e7c88bbd4b902fb754a8dc0a8ec6b62` | Windows ARM64 Vulkan 探针 |
