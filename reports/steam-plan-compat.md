# Patched win32u 兼容模块纳入可逆安装计划与端到端验证报告 (task-129)

- **任务编号**：task-129
- **执行角色**：wine-guard-verifier (Proton macOS Lab Team)
- **实施目标**：
  1. 将已验证的自然对齐补丁模块 `patched win32u.so`（SHA256: `59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed`）作为兼容性模块，无缝接入既有可逆安装计划链路（`scripts/backend/steam_plan.py`）；
  2. 遵循严格 TDD 规范，先编写包含 6 项细化场景的失败测试（RED），再以最小代码改动转绿（GREEN）；
  3. 确保既有 69 项 backend 测试无任何倒退，全套 75 项测试 100% 稳定通过；
  4. 在临时隔离 fixture Steam 根上执行真实工件的端到端完整闭环（`plan -> apply -> verify -> rollback`），提供字节级指纹前后对比及宿主路径零外部写入实证；
  5. 明确记录用户部署操作规范、回滚步骤、版本绑定红线与已知未做项。

---

## 1. 核心判定与执行摘要 (Executive Summary & Verdict)

> **核心技术判定**：**`COMPAT_MODULE_REVERSIBLE_INSTALLATION_FULLY_VERIFIED`（兼容模块可逆安装与回滚链路全生命周期验证通过）**  
>   
> **五大核心物理证据闭环**：  
> 1. **严格 TDD 研发落地**：新增测试文件 `tests/backend/test_steam_plan_compat.py`，包含 6 大用例，经历明确的 RED 失败态后顺利转绿（GREEN）；  
> 2. **无缝扩展既有安装模型**：在 `steam_plan.py` 中实现 `create_compat_module_plan` 与 `validate_elf_architecture`，扩充 `replace_compat_module` 步骤类型，既有接口与安全约束 100% 保持；  
> 3. **全量测试套件 100% 通过**：既有 69 项 backend 单测与新增 6 项 compat 单测合计 **75 项测试全部通过（Ran 75 tests in 5.847s, OK）**；  
> 4. **端到端字节级可逆实测通过**：在 `logs/steam-plan-compat/fixture_steam_root` 临时根内，目标文件从原版（SHA: `4f6013fa...`）安全替换为补丁版（SHA: `59a76b05...`），校验通过后执行回滚，目标文件 100% 恢复为原版（SHA: `4f6013fa...`），前后目录指纹完全一致；  
> 5. **宿主安全零泄露**：实测前后对 `/tmp`、`/Applications` 与 `~/Library/Application Support` 等宿主路径进行物理快照对比，确证**零写入、零越界、未触及真实 Steam**。

---

## 2. 既有接口扩展点与最小实现 (Architecture & Extension Points)

### 2.1 扩展设计原则
既有 `steam_plan.py` 设计用于整包工具树安装（`install_file`、`create_directory`）。兼容性补丁模块的特性是：**替换已存在的单个特定动态库，备份原文件，且必须严格限制在指定架构（如 aarch64）与受控子路径内**。

### 2.2 扩展点实现明细
1. **架构预校验 (`validate_elf_architecture`)**：
   - 读取目标 ELF 前 20 字节，通过 `e_machine`（偏移 18-19）校验架构（`183` 为 AArch64）；若目标架构不符（如误选 x86_64 目录）立即抛出 `SteamPlanError`，拒绝静默错配。
2. **计划生成 (`create_compat_module_plan`)**：
   - 校验目标相对路径，硬性拒绝绝对路径、`..` 越界路径以及指向 fixture 根外的符号链接逃逸（symlink escape）；
   - 核验源模块与目标前置文件存在性，校验原文件期望 SHA256；
   - 生成纯粹、无副作用的 JSON 计划，步骤类型为 `replace_compat_module`。
3. **计划执行 (`apply_installation_plan`)**：
   - 执行前二次安全扫描；备份目标原文件至 `.compat_backups/backup_<hash>_<name>`；
   - 将补丁文件原子拷贝至目标位置，设置权限，校验替换后 SHA256；
   - 在 manifest 中单独记录 `compat_modules` 清单与 `backups` 恢复元数据。
4. **完整性校验 (`verify_installation_manifest`)**：
   - 校验目标替换模块的存在性、SHA256 与文件大小；同时核验备份文件未受损。
5. **完全回滚 (`rollback_installation_manifest`)**：
   - 根据 `backups` 记录，将原始文件从备份路径安全写回目标路径，验证恢复后哈希，清理备份文件及空备份目录。

---

## 3. TDD 测试套件与全量运行证据 (TDD & Test Execution)

### 3.1 新增测试用例清单 (`tests/backend/test_steam_plan_compat.py`)

| 用例名称 | 验证场景与验收条款 | 状态 |
| :--- | :--- | :---: |
| `test_a_create_compat_plan_structure` | 计划包含相对路径、源 SHA256、目标大小与原始期望指纹 (Acceptance 1a) | **PASS** |
| `test_b_apply_compat_plan_replaces_and_matches_sha` | apply 严格在隔离根替换，替换后 SHA256 匹配并生成有效备份 (Acceptance 1b) | **PASS** |
| `test_c_verify_detects_tampering_or_missing` | verify 能精准检出目标文件被篡改或被意外删除 (Acceptance 1c) | **PASS** |
| `test_d_rollback_restores_original_byte_for_byte` | rollback 字节级恢复原版 SHA256，目录指纹前后完全一致 (Acceptance 1d) | **PASS** |
| `test_e_security_rejects_escape_and_traversal` | 严格拦截绝对路径、`..` 目录穿越及外部符号链接逃逸 (Acceptance 1e) | **PASS** |
| `test_f_precondition_failures_explicit` | 目标缺失、原始哈希失配或 ELF 架构不符时显式报错 (Acceptance 1f) | **PASS** |

### 3.2 全量 Backend 测试执行真实命令与输出
执行命令：
```bash
python3 -m unittest discover -s tests/backend -p "test_*.py" -v
```

真实控制台输出摘录：
```text
test_default_plan_has_no_absock_base_env (test_absock_base.TestAbsockBase) ... ok
... (既有 69 项测试全部 ok) ...
test_a_create_compat_plan_structure (test_steam_plan_compat.TestSteamPlanCompat) ... ok
test_b_apply_compat_plan_replaces_and_matches_sha (test_steam_plan_compat.TestSteamPlanCompat) ... ok
test_c_verify_detects_tampering_or_missing (test_steam_plan_compat.TestSteamPlanCompat) ... ok
test_d_rollback_restores_original_byte_for_byte (test_steam_plan_compat.TestSteamPlanCompat) ... ok
test_e_security_rejects_escape_and_traversal (test_steam_plan_compat.TestSteamPlanCompat) ... ok
test_f_precondition_failures_explicit (test_steam_plan_compat.TestSteamPlanCompat) ... ok

----------------------------------------------------------------------
Ran 75 tests in 5.847s

OK
```
**结论**：全套 **75 项测试全部通过**，未降低或破坏任何既有测试覆盖。

---

## 4. 端到端可逆实测物理证据 (End-to-End Real Artifact Verification)

端到端执行脚本：`scripts/backend/run_steam_plan_compat_e2e.py`。  
测试使用真实物理工件：
- 真实补丁模块：`sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so` (SHA: `59a76b05...`)
- 真实原版模块：`fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/win32u.so` (SHA: `4f6013fa...`)
- 临时隔离根：`logs/steam-plan-compat/fixture_steam_root`

### 4.1 阶段流转物理数据表

| 阶段 | 目标文件状态 | 目标 SHA256 校验和 | 树指纹文件 | 判定 |
| :--- | :--- | :--- | :--- | :---: |
| **0. 部署前** | 原版 `win32u.so` | `4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5` | `fingerprint_pre.json` | 初始基线 |
| **1. 生成计划** | 生成 `plan.json`，无文件修改 | `4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5` | - | 零副作用 |
| **2. 应用计划** | 安全替换为补丁库，生成备份 | `59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed` | `fingerprint_applied.json` | 替换成功 |
| **3. 校验清单** | 验证 `manifest.json` | `59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed` | `verify_result.json` | `is_valid: True` |
| **4. 完全回滚** | 执行 `rollback`，恢复原文件 | `4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5` | `fingerprint_post.json` | 字节级完全还原 |

### 4.2 树指纹前后对比与零外部写入确证
- **前后指纹比对**：`fingerprint_pre.json` 与 `fingerprint_post.json` 的 JSON 内容 **100% 逐字节一致**；
- **宿主零写入实证**：实测对 `/tmp`、`/Applications` 与 `~/Library/Application Support` 在安装前与回滚后的文件列表进行比对，文件集合完全无变动，确证未触及任何宿主系统路径。

---

## 5. 用户操作指南：计划生成、部署与回滚 (User Operation Manual)

> **声明**：以下为技术操作规范指南，在当前实验阶段仅作为交付文档描述，**严禁在未经授权的生产 Steam 环境下盲目执行**。

### 5.1 计划生成步骤
使用 Python 脚本生成只读计划：
```python
from pathlib import Path
from scripts.backend.steam_plan import create_compat_module_plan

# 1. 指定目标 Steam Proton 根目录与相对库路径
steam_proton_root = Path("/path/to/Steam/compatibilitytools.d/Proton-Experimental")
target_rel_path = "files/lib/wine/aarch64-unix/win32u.so"

# 2. 指定已验证的自然对齐补丁模块
patched_module = Path("/Users/mewcapoo/Projects/proton-macos-lab/sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so")

# 3. 生成只读计划 (无文件系统修改)
plan = create_compat_module_plan(
    fixture_steam_root=steam_proton_root,
    target_rel_path=target_rel_path,
    source_module_path=patched_module,
    expected_orig_sha256="4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5",
    expected_arch="aarch64"
)
```

### 5.2 安全部署步骤
```python
from scripts.backend.steam_plan import apply_installation_plan

# 执行计划并保存返回的 manifest (包含备份元数据)
manifest = apply_installation_plan(plan, steam_proton_root)
Path("/path/to/backup/manifest.json").write_text(json.dumps(manifest, indent=2))
```

### 5.3 完整性校验步骤
```python
from scripts.backend.steam_plan import verify_installation_manifest

valid, errors = verify_installation_manifest(manifest, steam_proton_root)
if not valid:
    print(f"Deployment corrupted: {errors}")
```

### 5.4 一键完全回滚步骤
若需要卸载补丁或恢复官方原版：
```python
from scripts.backend.steam_plan import rollback_installation_manifest

# 读取当时生成的 manifest 执行一键回滚
rollback_report = rollback_installation_manifest(manifest, steam_proton_root)
print("Rollback completed successfully, original file restored!")
```

---

## 6. 版本绑定风险与红线规则 (Version Binding Risks)

1. **版本漂移风险（严禁跨大版本盲目覆盖）**：
   - 如 `reports/vulkan-guard-handoff.md` 详述，Wine 的 `win32u.so` 与 `winevulkan.so` 存在紧密耦合的内部结构体 `struct vulkan_instance`；
   - 本补丁库（`59a76b05...`）严格绑定于 Valve Wine commit `adea6cbac` 及 Vulkan 1.4.357 规范（偏移 `0x2e0 / 0x2e8`）；
   - **红线**：如果用户升级了 Proton 版本，原版 `win32u.so` 哈希将发生改变，`create_compat_module_plan` 会因 `expected_orig_sha256` 不匹配**自动拒绝部署**；严禁绕过哈希检查强行覆盖，否则可能再次引发指针被当设备计数的内存越界故障（`0x103efc0` 类错误）。
2. **PE-Unix 跨边界一致性**：
   - 本安装链路仅替换 Unix 端 `win32u.so`，严禁替换 PE 端 `winevulkan.dll` 或改变枚举表。

---

## 7. 显式未做项披露 (Explicit Unknowns)

本任务严格遵循工程纪律，以下事项在此阶段**明确未做**并维持未知：
1. **真实 Steam 客户端集成**：未向真实 Steam 目录安装工具，未启动真实 Steam 客户端；
2. **游戏启动与商业凭据**：未调用 Steam 启动真实游戏，未涉及任何用户账户与 Steamworks DRM；
3. **GDI Display Cache 自然恢复**：状态维持 **`UNKNOWN`**；
4. **x64 PE / FEX 二进制翻译执行**：状态维持 **`UNKNOWN`**。

---

## 8. 证据索引清册 (Evidence Manifest)

| 证据类别 | 本地物理文件路径 | 关键校验和 / 记录 | 说明 |
| :--- | :--- | :--- | :--- |
| **新增测试用例** | `tests/backend/test_steam_plan_compat.py` | - | 6 个用例全覆盖 |
| **扩展实现代码** | `scripts/backend/steam_plan.py` | - | 增加 compat 模块可逆计划支持 |
| **E2E 自动化脚本** | `scripts/backend/run_steam_plan_compat_e2e.py` | - | 端到端实测运行脚本 |
| **E2E 执行总结** | `logs/steam-plan-compat/e2e_summary.json` | `status: SUCCESS` | 记录完整生命周期状态 |
| **E2E 计划文件** | `logs/steam-plan-compat/plan.json` | - | 只读 JSON 计划 |
| **E2E 清单文件** | `logs/steam-plan-compat/manifest.json` | - | 包含备份与 SHA 记录 |
| **E2E 回滚报告** | `logs/steam-plan-compat/rollback_report.json` | `status: success` | 记录恢复详情 |
| **安装前指纹** | `logs/steam-plan-compat/fingerprint_pre.json` | - | 原始目录结构指纹 |
| **回滚后指纹** | `logs/steam-plan-compat/fingerprint_post.json` | - | 与 pre 完全一致 |
| **补丁源模块** | `sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so` | `59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed` | 交付补丁模块 |
| **原版基准模块** | `fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/win32u.so` | `4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5` | 原始基准模块 |
