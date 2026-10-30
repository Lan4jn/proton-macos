# 端到端可逆安装方案、清单管理与负向边界测试报告 (Task-93)

**责任人**：futex-owner-r36 (执行员)  
**遵循规范**：`test-driven-development`（端到端闭环验证、零主机触碰、负向越界硬拦截）  
**关联任务**：Task-93（端到端可逆安装方案与清单，仅 fixture，不触碰真实 Steam）  
**代码产物**：
1. 方案核心模块：`scripts/backend/steam_plan.py`
2. 完整单元测试：`tests/backend/test_steam_plan.py` (6 项全绿)
3. 端到端执行运行器：`scripts/backend/run_e2e_steam_plan.py`
4. 物理收据目录：`logs/steam-plan/` (`plan.json`, `manifest.json`, `verify.json`, `rollback_report.json`, `receipt.json`)

---

## 一、 方案设计与核心保证 (Architecture & Guarantees)

在不改动既有 `scripts/backend/` 对外既有接口且保持全量既有测试（63 项）全绿的前提下，我们在 `scripts/backend/steam_plan.py` 中实现了一套生产级、端到端可逆的 Steam 兼容性工具安装管理机制：

1. **纯计划生成 (Side-Effect Free Plan Generation)**：
   - 输入：模拟的 fixture Steam 库根目录与候选包源目录；
   - 输出：完全确定性、结构化的安装计划（包含目标目录创建、逐文件源路径/目标路径/SHA256/大小/权限模式）；
   - **零副作用保证**：计划生成过程绝不创建任何文件、绝不修改任何目标目录，完全支持直接序列化导出为 JSON；
2. **安全封闭性与负向硬拒绝 (Path Enclosure & Host Steam Rejection)**：
   - 目标路径与 fixture 根必须严格限制在当前实验隔离区（LAB）内；
   - 任何试图指定真实主机 Steam 目录（`~/Library/Application Support/Steam`、`/Applications/Steam.app`）或系统路径（`/Applications`、`/usr`、`/etc`、`/System`、`/Library`）的操作，或者试图通过 `..` 路径遍历逃逸出 fixture 根的行为，**一律在计划应用前直接硬拦截并抛出 `SteamPlanError`，绝不执行任何写操作**；
3. **权威清单 (Authoritative Manifest)**：
   - 计划应用时，严格核对每一条操作，并生成自包含的 JSON 清单；
   - 记录所有安装的文件路径、SHA256 校验和、大小、权限，以及新创建的目录链；若涉及已有文件覆写，自动在独立备份目录中归档原文件及原 SHA256；
4. **按字节比对恢复原状 (Byte-for-Byte Exact Rollback)**：
   - 回滚机制完全由清单驱动，逐个删除安装的文件、还原备份文件，并按逆序精确清理新创建的空目录；
   - 回滚后对目标目录执行递归 SHA256 树指纹比对，确保与安装前基线 100% 字节一致。

---

## 二、 单元测试与 63 项全量回归实测结果

### 1. 新增单元测试：`tests/backend/test_steam_plan.py`
包含 6 个独立测试用例：
1. `test_plan_generation_pure_and_serializable`：验证计划生成的纯函数性与 JSON 导出（PASS）；
2. `test_end_to_end_closed_loop_and_byte_exact_rollback`：端到端闭环（Plan -> Apply -> Verify -> Rollback -> 字节级完全恢复）（PASS）；
3. `test_rejection_of_real_steam_path_in_plan`：针对真实 Steam 路径的负向硬拒绝（PASS）；
4. `test_rejection_of_system_paths`：针对系统路径（`/Applications`, `/usr`, `/etc`）的硬拒绝（PASS）；
5. `test_rejection_of_path_traversal_escaping_fixture_root`：针对 `..` 逃逸的硬拒绝（PASS）；
6. `test_idempotent_plan_generation`：计划多次生成的幂等性（PASS）。

**测试执行输出**：
```text
python3 -m unittest tests/backend/test_steam_plan.py
......
----------------------------------------------------------------------
Ran 6 tests in 0.020s

OK
```

### 2. 既有后端 63 项测试全量回归
执行命令：`python3 -m unittest discover -s tests/backend -p "test_*.py"`
实测结果：**Ran 69 tests in 6.841s (63 项历史测试 + 6 项新增测试，100% PASS，0 失败，0 回归)**。

### 3. 关联闭环套件：`scripts/backend/tests/test_steam_reversible_closure.py`
执行命令：`python3 -m unittest discover -s scripts/backend/tests -p "test_*.py"`
实测结果：**Ran 4 tests in 0.156s, OK**。

---

## 三、 端到端真实运行物理实测与收据留证 (E2E Master Receipt)

通过执行脚本 `scripts/backend/run_e2e_steam_plan.py`，在 `logs/steam-plan/` 建立了完整物理留证链：

### 1. 执行全流程时间与度量
- **[STEP 1] 基线指纹采集**：
  `compatibilitytools.d/existing_system_tool.txt`
  `steamapps/libraryfolders.vdf`
- **[STEP 2] 计划创建**：耗时 **0.78 ms**，生成 7 步操作计划，保存至 `logs/steam-plan/plan.json`；
  比对基线指纹：完全一致（纯净度 100%）；
- **[STEP 3] 计划应用**：耗时 **1.79 ms**，安装 4 个文件，创建 3 个目录，保存至 `logs/steam-plan/manifest.json`；
- **[STEP 4] 磁盘清单核实**：耗时 **0.35 ms**，校验 4 个文件 SHA256 与文件大小，`errors: []`，保存至 `logs/steam-plan/verify.json`；
- **[STEP 5] 依据清单回滚**：耗时 **1.51 ms**，安全移除 4 个已安装文件及创建的目录，保存至 `logs/steam-plan/rollback_report.json`；
- **[STEP 6] 回滚后字节比对**：
  `initial_fingerprint == post_rollback_fingerprint` **严格为 `True`**；
  安装目标目录 `proton_arm64_e2e` 完全清除，基线文件无任何损伤；
- **[STEP 7] 负向越界硬拒绝测试**：
  - 拒绝 `~/Library/Application Support/Steam`：`Security violation: targets forbidden host root`；
  - 拒绝 `/Applications`：`Security violation: targets forbidden host root`；
  - 拒绝 `/usr/local`：`Security violation: targets forbidden host root`；
  3 项安全测试 100% 拦截通过！

### 2. 汇总收据内容 (`logs/steam-plan/receipt.json`)
```json
{
  "plan_file": "/Users/mewcapoo/Projects/proton-macos-lab/logs/steam-plan/plan.json",
  "manifest_file": "/Users/mewcapoo/Projects/proton-macos-lab/logs/steam-plan/manifest.json",
  "verify_file": "/Users/mewcapoo/Projects/proton-macos-lab/logs/steam-plan/verify.json",
  "rollback_report_file": "/Users/mewcapoo/Projects/proton-macos-lab/logs/steam-plan/rollback_report.json",
  "total_plan_steps": 7,
  "installed_files_count": 4,
  "created_directories_count": 3,
  "verification_passed": true,
  "byte_exact_rollback": true,
  "forbidden_paths_rejected": 3,
  "status": "PASS"
}
```

---

## 四、 本方案未覆盖能力与环境限制说明 (Explicit Non-Coverage & Unknowns)

依据严谨原则，明确列出当前端到端安装准备方案**明确未覆盖**的能力与原因：
1. **真实 Steam 客户端登录与在线握手**：
   - **未覆盖**：未尝试连接 Steam 官方登录服务器、未拉取任何在线 app/depot 清单、未执行真实的 Steam 客户端进程间通信；
   - **原因**：受限于用户与项目的最高安全边界，实验环境必须保持离线且绝不修改真实 Steam 账户状态；
2. **原生 Steam 客户端 UI 交互 (点击 Play 实测)**：
   - **未覆盖**：Steam 客户端界面的“设置 -> 兼容性”工具下拉列表识别以及点击“运行”按钮由 Steam 派生子进程的交互；
   - **原因**：当前方案仅涵盖文件系统兼容性工具目录（`compatibilitytools.d`）的规格与清单就绪，真正的客户端加载依赖闭源 Steam 二进制的内部解析；
3. **真实 Steamworks API 运行时握手**：
   - **未覆盖**：`steam_api64.dll` 与原生 macOS Steam 守护进程在命名管道/抽象套接字上的鉴权通信。
