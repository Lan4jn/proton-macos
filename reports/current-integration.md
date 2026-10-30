# 当前集成诊断状态报告：公开 Proton Package 与前置就绪度 (复审修订版)

**实验日期**：2026-10-15  
**执行员**：`proton-package-worker`  
**关联任务**：`task-15`（更新集成诊断以反映公开包真实状态）  
**宿主环境**：Apple Silicon macOS 27.0.1 (Build 26A434, arm64, Rosetta 2 可用, 磁盘可用空间 246 GiB)  
**交付物路径**：
- 前置就绪度诊断入口：`scripts/integration/check_prerequisites.py`
- 诊断工具单元测试：`scripts/integration/test_prerequisites.py`
- 真实执行与测试日志：`logs/current-integration/`
  - `direct_mode_run.log` (默认直接模式实测输出，退出码 20)
  - `public_mode_run.log` (公开清单模式实测输出，退出码 10)
  - `public_mode_json.log` (公开清单模式 JSON 实测输出，退出码 10)
  - `unittest.log` (14 项单元与 CLI 测试全量通过记录)

---

## 1. 任务背景与核心结论

### 1.1 核心问题定位
在早期基线阶段，`scripts/integration/check_prerequisites.py` 仅硬编码读取 `artifacts/proton/identity.json`，由于官方 Steam App 4427310 / Depot 4427311 受匿名订阅拦截，诊断一概输出 `package unavailable (Exit 20)`，未能反映后续已由公开再分发渠道获取并校验通过的公开包（`artifacts/public-proton/bundle.json`）现状。

### 1.2 本次整改结论 (Key Verdicts)
1. **多模式诊断分流与真实性保持**：
   - **默认直接路径（Direct Steam Mode）**：保持完全向后兼容，忠实反映官方 Steam 匿名拉取阻断事实（退出码 `20`），绝不篡改历史元数据伪造官方直下包。
   - **公开清单模式（Public Manifest Mode，`--public-manifest`）**：调用 `scripts.backend.bundle.verify_bundle` 对关键二进制（`wine`, `wineserver`, `ntdll.so`, `libarm64ecfex.so`）进行 SHA-256 哈希校验与 ELF 头校验。
2. **严谨的保守状态分类（Strict Semantic Separation）**：
   - **`package_status: PUBLIC_REDISTRIBUTION_VERIFIED`**：明确发布者（`The412Banner/winlator-contents`）摘要一致，来源声称为 Valve 原版，但**明确注明未经独立 Valve 官方签名**（`independent_valve_signature_verified: false`）。在包损坏/校验失败时（`CORRUPTED`），`package_detail` 真实报错，严禁仍称“checksums verified”。
   - **`wine_execution_status: COMPONENT_EXECUTION_NOT_CHECKED`**：诊断工具定位为前置包与运行环境检查，不越权硬编码组件执行假象。
   - **`full_proton_status: FULL_PROTON_NOT_VALIDATED`**：Proton Python 启动脚本执行未经本工具运行时验证（历史实验记录于 `reports/public-proton.md` 与 `logs/runtime/`，仅作引用，不作为本工具现场核验证据）。
   - **`x64_execution_status: X64_NOT_VERIFIED`**：Windows x64 控制台程序（`hello-x64.exe`）经 FEX 翻译执行目前仍处于验证中（未取得期望的 `X64_FEX_OK` / exit 0），**绝不将 `PLAN_READY` 混淆为运行成功**。
3. **真实非零退出码保障**：
   - 在公开清单模式下，因运行时执行测试（full Proton / x64 PE）未经现场验证通过，CLI 真实退出码明确返回 **`Exit 10`**。工具不提供虚假的自动通过入口，文档不承诺未来必然自动转 0，保持工程严谨性。

---

## 2. 状态映射与退出码矩阵

| 模式 | 判定条件 | 状态标识 | CLI 退出码 | 含义 |
| :--- | :--- | :--- | :---: | :--- |
| **直接 Steam 模式** | `identity.json` 标记 download_blocked=True | `package_status: BLOCKED` | **20** | 官方 Steam Depot 4427311 需要账号订阅授权，匿名获取受阻 |
| **直接 Steam 模式** | 本地包已提供且校验通过，elfuse 通过 | `package_status: READY` | **0** | **仅表示前置环境与包已就绪**，可进入执行测试（绝不证明 Windows 游戏已运行成功） |
| **公开清单模式** | bundle 校验失败或文件丢失 | `package_status: CORRUPTED` | **20** | 公开分发包损坏或缺少关键 ELF 组件（明确报错，不称校验通过） |
| **公开清单模式** | elfuse 基线构建/运行失败 | `elfuse_status: FAILED` | **1** | macOS Hypervisor / elfuse 底层运行能力失效 |
| **公开清单模式** | bundle 校验通过，但全量执行未验证 | `package_status: PUBLIC_REDISTRIBUTION_VERIFIED`<br>`wine_execution_status: COMPONENT_EXECUTION_NOT_CHECKED`<br>`x64_execution_status: X64_NOT_VERIFIED` | **10** | **当前实际状态**：包摘要校验通过，但组件执行未检验、全量 Proton 与 x64 未通过验证；本前置工具不采集 x64 现场执行，因此无自动成功路线，稳定返回 Exit 10 |

---

## 3. 真实 CLI 诊断实测回显

### 3.1 公开清单文本模式实测（退出码 10）
```bash
$ python3 scripts/integration/check_prerequisites.py --public-manifest artifacts/public-proton/bundle.json
==========================================================
Proton Integration Prerequisite Check (Public Manifest Mode)
==========================================================
ELF Runtime Baseline (elfuse) : VERIFIED (hello)
Package Acquisition Status    : PUBLIC_REDISTRIBUTION_VERIFIED
Publisher / Provenance        : The412Banner/winlator-contents (PUBLIC_REDISTRIBUTOR_CHECKSUM_VERIFIED_VALVE_ORIGIN_CLAIMED)
Independent Valve Signature   : False
Wine Component Execution      : COMPONENT_EXECUTION_NOT_CHECKED
Full Proton Launcher Status   : FULL_PROTON_NOT_VALIDATED
FEX x64 Emulation Status      : X64_NOT_VERIFIED
==========================================================
Conclusion: Public Proton package checksums verified by publisher manifest (Exit 10).
            Status: PUBLIC_REDISTRIBUTION_VERIFIED
            Valve origin claimed but NOT independently signed by Valve.
            Wine Component Execution : COMPONENT_EXECUTION_NOT_CHECKED
            Full Proton Launcher     : FULL_PROTON_NOT_VALIDATED
            Windows x64 Execution    : X64_NOT_VERIFIED
            Notice: A command plan or package checksum is NOT evidence of Windows execution success.
            CLI returns Exit 10 (unvalidated runtime state); no automated passing is claimed.
```
*真实进程退出码：`10`*

### 3.2 默认直接 Steam 模式实测（退出码 20，向后兼容）
```bash
$ python3 scripts/integration/check_prerequisites.py
==========================================================
Proton Integration Prerequisite Check (Direct Steam Mode)
==========================================================
ELF Runtime Baseline (elfuse) : VERIFIED (hello)
Proton Package Acquisition    : BLOCKED
  - Reason: Official package missing: Steam depot App 4427310 / Depot 4427311 requires authenticated subscription (ownersonly).
Wine / wineserver Execution   : NOT_RUN
FEX x64 Emulation Execution   : NOT_RUN
==========================================================
Conclusion: Execution blocked at official package acquisition (Exit 20).
            No third-party packages substituted.
            ELF execution capability verified; Wine / FEX tests NOT RUN.
```
*真实进程退出码：`20`*

---

## 4. 测试套件与验证证据

在 `scripts/integration/test_prerequisites.py` 中扩充了针对 `--public-manifest` 的全面单测与 CLI 子进程集成测试：
```bash
$ python3 -m unittest scripts/integration/test_prerequisites.py -v
test_cli_exit_code_missing_identity_returns_2 (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_cli_exit_code_real_lab_root_returns_20 (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_cli_public_manifest_missing_returns_2 (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_cli_public_manifest_real_returns_10 (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_dynamic_conclusions (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_elfuse_failed_even_if_package_ready (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_empty_string_package_path_blocked (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_evaluate_public_manifest_classifications (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_local_path_present_unverified (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_missing_package_blocked (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_nonexistent_local_path_blocked (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_public_manifest_corrupted_has_accurate_detail_and_exit_20 (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_public_manifest_elfuse_failed_returns_1 (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok
test_unverified_elfuse_marks_elfuse_failed (scripts.integration.test_prerequisites.TestIntegrationPrerequisites) ... ok

----------------------------------------------------------------------
Ran 14 tests in 0.211s

OK
```
全量 14 项测试全部通过，无任何跳过或失败用例。
特别覆盖了：
- 真实公开包校验通过但声明 `COMPONENT_EXECUTION_NOT_CHECKED` 与 `X64_NOT_VERIFIED`（避免假冒执行验证）；
- 伪造损坏包在 `CORRUPTED` 分支下真实报错，不再声称“checksums verified”，稳定返回 exit 20。

---

## 5. 对下游任务与 Lead 的交付说明

1. **统一诊断入口调用方式**：
   ```bash
   python3 scripts/integration/check_prerequisites.py --public-manifest artifacts/public-proton/bundle.json
   ```
   只要全量 Proton 与 Windows x64 PE 运行尚未通过现场测试，该命令必将稳定退出 `10`。
2. **防假死与防伪造保证**：
   - 严禁将 `backend.bundle.build_plan` 返回的 `PLAN_READY` 篡改为运行成功；
   - 严禁将底层组件存在或历史实验片断等同于当前现场核验通过；
   - 本工具恪守前置检查边界，不虚构自动化直通能力。
