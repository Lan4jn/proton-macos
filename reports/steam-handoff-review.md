# 离线 Steam 后端入口与参数边界独立验收报告

**报告日期**：2026-10-16  
**验收角色**：`final-lab-reviewer`（独立审查员）  
**关联任务**：`task-31`（独立验收离线Steam后端入口与参数边界）  
**被审任务**：`task-29`（准备并黑盒验证离线Steam形态的真实后端入口）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**独立测试前缀**：`fixtures/runtime/steam-review/compat/pfx/`（自 `task-25` 独立克隆，保留绝对化符号链接）  
**独立测试候选目录**：
- 计划态候选：`artifacts/steam-prepared/runtime-handoff-review-plan/`
- 执行态候选 (f834)：`artifacts/steam-prepared/runtime-handoff-review-exec/`
- 执行态候选 (f2)：`artifacts/steam-prepared/runtime-handoff-review-f2-exec/`  
**审查归档日志**：`logs/steam-handoff-review/`  

---

## 一、 执行摘要与总体验收判定

1. **验收目标与对象**：
   - 对 `task-29` 交付的新模块 `scripts/backend/steam_handoff.py`、单元测试套件 `tests/backend/test_steam_handoff.py` 及其第 1 轮返工加固项（动态哈希校验、外层 cwd 绝对路径、元字符转义保护、真实 wrapper 跨层执行）进行独立代码审查与沙箱黑盒复验；
   - 重点验证：默认 Plan-Only 门禁、显式 `--execute-runtime` 激活、参数字面量边界保真（Unicode/空格/百分号/前导破折号/Shell元字符）、恶意环境隔离（`WINEPREFIX`/`LD_*`/`DYLD_*` 擦除）、配置内哈希失配拒绝（Exit 20）、以及在完全独立克隆的 prefix 下实际黑盒调用 `proton-wrapper.sh` 驱动真实 Linux Python + 原版 Proton + FEX 运行 `hello-x64.exe`。
2. **核心验收结论**：**批准通过（APPROVED）**。
   - **单测全绿**：全量后端单测 50 项全部通过（耗时 5.6s，Exit 0）；
   - **参数与环境防护完备**：从 `/tmp` 外部目录调用包装器，中文空格路径、百分号、Shell 元字符（`$USER`, `*.*`, `; echo evil`）全部作为纯字面量无损传递；外部恶意 `WINEPREFIX` 或 `LD_*` 均被有效清洗，强制绑定 lab 内固定沙箱前缀；
   - **哈希绑定有效**：当 `config.json` 记录的 `elfuse_sha256` 与实际二进制不匹配时，包装器坚决拒绝执行，返回 Exit 20 (`status: BLOCKED`)，零子进程启动；
   - **独立端到端执行通过（双 Runtime 交叉确证）**：
     - 在独立前缀 `fixtures/runtime/steam-review/compat` 下从 `/tmp` 实际调用生成的 `proton-wrapper.sh runinprefix C:\hello-x64.exe`：
       * **Candidate f834**（`run-nr78jmso`）：耗时 52.22s，`exit: 0`, `target_exit: 0`, 目标标准输出确认打出 **`X64_FEX_OK`**；
       * **Lifecycle f2**（`run-9wflgjgy`）：耗时 40.47s，`exit: 0`, `target_exit: 0`, 目标标准输出确认打出 **`X64_FEX_OK`**；
     - 均在 110s 超时上限内由现有受控 supervisor 平稳回收，零僵尸残留。
3. **真实边界与诚实声明**：
   - 本套件交付物为**离线 Steam-shaped 兼容工具形态包装器与候选文件**；
   - **绝不代表真实 macOS Steam 客户端的自动识别、UI 兼容工具下拉展示、真实点击 Play 调度，更不代表 Steamworks API 初始化与 DRM 验证通过**。

---

## 二、 第一阶段：规格合规审查（Specification Review）

| 审查维度 | 规范约束与红线 | 审查发现与代码证据 | 判定 |
| :--- | :--- | :--- | :---: |
| **默认 Plan-Only 保护** | 准备兼容工具默认必须处于计划态，绝不可静默启动实际执行。 | `prepare_runtime_tool` 默认生成 `execute_runtime: false`, `applied: false`；包装器调用默认只输出结构化 `PLAN_READY` JSON，不调用 `run_isolated`。 | **PASS** |
| **显式执行激活** | 仅当显式传入 `--execute-runtime` 时，生成的候选包才允许执行。 | `execute_from_config:226` 严格判定 `if not cfg.get("execute_runtime", False): return 0`；只有置位 `true` 时才进入执行通道。 | **PASS** |
| **真实 Linux Python** | 驱动 Proton 脚本必须使用真实 Linux Python，严禁 macOS Python 替代。 | `config.json` 绑定 `fixtures/runtime/arch-case/usr/bin/python3.14`，在 `elfuse` 下解释运行原版 Proton，无宿主 Python 冒充。 | **PASS** |
| **目标目录零侵入** | 兼容工具安装计划绝不修改本机真实 Steam 配置，必须保持 `applied: false`。 | `target` 严格限定于 lab 内部 mock 目录（`fixtures/runtime/steam-review/mock-steam/...`），`install-plan.json` 明确标识 `applied: false`，提供备份回滚描述。 | **PASS** |
| **运行时哈希强绑定** | 包装器配置中记录的哈希与实际二进制不符时，必须拒绝运行并返回 Exit 20。 | `execute_from_config:186-208` 显式比对 `current_desc["sha256"]` 与 `cfg["elfuse_sha256"]`；失配立即返回 `status: BLOCKED` 与 Exit 20。 | **PASS** |
| **环境变量清洗与前缀锁定**| 必须清除 `LD_*`/`DYLD_*`，且外部环境变量不得覆盖 lab 沙箱前缀。 | `proton-wrapper.sh` 首行清除 `LD_PRELOAD LD_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH`；`build_plan` 强制使用配置指定的 lab 前缀。 | **PASS** |
| **动词门禁机制** | 仅放行已知 Steam 动词（`run`, `runinprefix`, `waitforexitandrun`）。 | `execute_from_config:175-180` 校验 `verb in KNOWN_STEAM_VERBS`，未知动词返回错误并以退出码 2 退出。 | **PASS** |

---

## 三、 第二阶段：代码质量与黑盒边界测试审查（Quality & Blackbox Review）

### 1. 全量后端单测套件实测（50/50 PASS）
审查员在工作区根目录执行全量后端单元测试（包含 bundle、process、supervisor、regressions、runtime selection 及 steam handoff）：
```bash
python3 -m unittest discover -s tests/backend -v
```
**实测回显**（归档于 `logs/steam-handoff-review/1_backend_full_suite.log`）：
- 累计运行 **50 项测试**，耗时 **5.626s**；
- 失败数 0，错误数 0，退出码 **0**；
- 验证涵盖了各种边界：恶意前缀逃逸拦截、supervisor 进程树回收无信号泄漏、ELF 符号版本布局解析、非 Mach-O 及非 ARM64 二进制阻断、动态哈希失配 Exit 20 拦截等。

### 2. 外部 cwd 与复杂参数字面量保真验证
审查员在外部目录 `/tmp` 下，调用独立生成的计划态包装器：
`artifacts/steam-prepared/runtime-handoff-review-plan/proton-wrapper.sh`
传入包含中文、空格、百分号、前导破折号、Shell 危险字符以及恶意环境变量的测试调用：
```bash
cd /tmp && artifacts/steam-prepared/runtime-handoff-review-plan/proton-wrapper.sh \
  runinprefix "C:\Games\黑神话 悟空\game.exe" -option%name "--custom-flag=val with spaces" \
  '$USER' '*.*' '; echo evil' '&& rm -rf' -- -sub_flag
```
**实测结果**（归档于 `logs/steam-handoff-review/2_plan_only_blackbox.log`）：
- 返回码：`0`；
- `status`: `PLAN_READY`，`execution_performed`: `false`；
- `argv` 逐项保真：
  * `C:\Games\黑神话 悟空\game.exe`（中文原生 UTF-8 与空格完整保留）
  * `-option%name`（百分号无损保留）
  * `--custom-flag=val with spaces`（空格无损保留）
  * `$USER`、`*.*`、`; echo evil`、`&& rm -rf`（全部作为纯字面量传递，未被 shell 展开或注入）
  * `-sub_flag`（`--` 后续参数完整保留）
- `env.WINEPREFIX`：严格指向 `fixtures/runtime/steam-review/compat/pfx`，外部传入的 `/tmp/evil_external_prefix` 完全被屏蔽。

### 3. 动态哈希失配负例验证
在 `artifacts/steam-prepared/scratch_mismatch/` 中生成候选并人为篡改 `config.json` 中的 `elfuse_sha256` 为 `deadbeef...`：
```bash
cd /tmp && artifacts/steam-prepared/scratch_mismatch/proton-wrapper.sh runinprefix C:\hello-x64.exe
```
**实测结果**（归档于 `logs/steam-handoff-review/3_hash_mismatch.log`）：
- 返回码：**`20`**；
- 标准输出：
  ```json
  {
    "status": "BLOCKED",
    "reason": "Frozen elfuse hash mismatch: expected deadbeef..., observed f83455b0...",
    "execution_performed": false
  }
  ```
- 确证运行时哈希防篡改防护生效，未启动任何子进程。

---

## 四、 第三阶段：独立端到端黑盒执行复验（Actual Execution）

审查员使用完全独立的隔离前缀 `fixtures/runtime/steam-review/compat`（自 `task-25` 克隆，DLL 符号链接保持绝对路径且 `hello-x64.exe` 存在），在 `/tmp` 工作目录下实际调用执行态包装器：

### 1. 候选执行（Candidate f834: `run-nr78jmso`）
- **候选配置**：
  - 二进制：`sources/elfuse-crash-derived/build/elfuse-candidate`
  - SHA-256：`f83455b073611030d388e1f7c4be1dfee26af34106a373b3a6713497790f3e26`
- **执行命令**：
  ```bash
  cd /tmp && artifacts/steam-prepared/runtime-handoff-review-exec/proton-wrapper.sh runinprefix C:\hello-x64.exe
  ```
- **实测表现**（归档于 `logs/steam-handoff-review/4_actual_execution.log`）：
  - 包装器退出码：`0`；
  - 整体耗时：**`52.22s`**（远低于 110s 超时上限）；
  - `exit`: `0`, `target_exit`: `0`, `timed_out`: `false`, `cleanup_errors`: `[]`；
  - 目标 `stdout.log` 内容确证：**`X64_FEX_OK`**。

### 2. 生命周期执行（Lifecycle f2: `run-9wflgjgy`）
- **候选配置**：
  - 二进制：`sources/elfuse-lifecycle-derived/build/elfuse`
  - SHA-256：`f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`
- **执行命令**：
  ```bash
  cd /tmp && artifacts/steam-prepared/runtime-handoff-review-f2-exec/proton-wrapper.sh runinprefix C:\hello-x64.exe
  ```
- **实测表现**（归档于 `logs/steam-handoff-review/5_actual_f2_execution.log`）：
  - 包装器退出码：`0`；
  - 整体耗时：**`40.47s`**（平稳快速）；
  - `exit`: `0`, `target_exit`: `0`, `timed_out`: `false`, `cleanup_errors`: `[]`；
  - 目标 `stdout.log` 内容确证：**`X64_FEX_OK`**。

双 Runtime 交叉黑盒复验确证：离线 Steam-shaped 包装器不仅能可靠调度单次执行，且在接入最新的生命周期停机修复（f2）时依然保持毫秒级参数解析与高效稳定的执行链传导。

---

## 五、 关键工件哈希与交付清单

1. **工件哈希清单**：
   - Candidate f834: `f83455b073611030d388e1f7c4be1dfee26af34106a373b3a6713497790f3e26`
   - Lifecycle f2: `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`
   - Linux Python (`fixtures/runtime/arch-case/usr/bin/python3.14`): `c6bc1ef497b896b7575c546b13f9bafe52e2066f184fdd3fec6af4b5b6349947` (采自 `sha256sum /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/python3.14`)
   - Target hello-x64: `26cccc8ced8bb2037b2589f7d7af204ad98a27c4f7919bc7fc0dc21e032be9e7`
2. **独立验收归档产物**：
   - 审查报告：`reports/steam-handoff-review.md`
   - 归档日志：`logs/steam-handoff-review/`（含 `1_backend_full_suite.log`、`2_plan_only_blackbox.log`、`3_hash_mismatch.log`、`4_actual_execution.log`、`5_actual_f2_execution.log` 及运行目录 `run-nr78jmso`、`run-9wflgjgy`）
   - 候选生成物：
     - `artifacts/steam-prepared/runtime-handoff-review-plan/`
     - `artifacts/steam-prepared/runtime-handoff-review-exec/`
     - `artifacts/steam-prepared/runtime-handoff-review-f2-exec/`
   - 独立克隆前缀：`fixtures/runtime/steam-review/compat/`
3. **签字结论**：
   - **审查员**：`final-lab-reviewer`
   - **验收状态**：**通过最终验收（APPROVED）**。
   - **任务状态**：`task-31` 满足完成条件。
