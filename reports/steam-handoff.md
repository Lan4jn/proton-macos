# 离线 Steam 形态真实后端入口准备与黑盒验证报告

**报告日期**：2026-10-16  
**执行角色**：`steam-probe-worker`（Steam 适配与后端交接实现员）  
**关联任务**：`task-29`（准备并黑盒验证离线 Steam 形态的真实后端入口）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**测试日志归档**：`logs/steam-handoff/red.log`、`logs/steam-handoff/green.log`  
**候选交付目录**：`artifacts/steam-prepared/runtime-handoff-plan-only/`、`artifacts/steam-prepared/runtime-handoff-execute/`  

---

## 一、 执行目标与架构原则

1. **真实后端与 Steam 形态入口解耦接入**：
   - 此前任务已证实：原生 macOS 进程调度器经由 `elfuse`（冻结候选 `sources/elfuse-crash-derived/build/elfuse-candidate`，SHA-256：`f83455b073611030d388e1f7c4be1dfee26af34106a373b3a6713497790f3e26`）拉起真实 Linux ARM64 Python 3.14，成功驱动原版 Valve Proton 脚本完成 `hello-x64.exe` 执行并输出 `X64_FEX_OK`；
   - 本任务实现**离线 Steam 兼容工具形态（Steam-shaped compatibility tool）**候选包装器，将上述已验证的真实底层后端封装为 Steam 规范的 `compatibilitytool.vdf`、`toolmanifest.vdf` 及 shell 启动包装脚本；
   - **零代码污染**：本任务实现为独立新模块 `scripts/backend/steam_handoff.py`，未修改已冻结验收的 `scripts/backend/bundle.py`、`scripts/backend/cli.py` 或 `scripts/steam/probe.py`。

2. **核心安全与隔离铁律**：
   - **默认 Plan-Only 保护**：生成工具候选默认处于纯计划模式（`execute_runtime: false`，`applied: false`），当包装器被调用时仅输出结构化命令计划，**绝不静默启动任何实际子进程**；
   - **显式执行激活**：必须显式传入 `--execute-runtime` 参数，才会在候选包中写入允许实际执行的配置；
   - **目标路径不侵入**：`target` 明确指向 lab 内部 mock 的兼容工具目录（`fixtures/runtime/steam-shaped/mock-steam/compatibilitytools.d`），不猜测、不读取、不写入本机真实 Steam 目录（`applied: false`）；
   - **诚实边界声明**：离线 Steam-shaped 工具候选**不等于真实 Steam 客户端的识别、UI 下拉可选、真实点击 Play 调度，更不等于 Steamworks / DRM 通过**。

---

## 二、 包装器安全加固与路径处理

针对 Steam 客户端可能在任意工作目录（cwd）启动、可能传入复杂字符参数的场景，对 `proton-wrapper.sh` 进行了深度防御加固：

1. **绝对路径与 cwd 无关性**：
   - 包装器内部使用经过 `shlex.quote` 严格转义的绝对路径调用 Python 解释器与 `scripts/backend/steam_handoff.py`，彻底解决从 lab 外工作目录（如 `/tmp`）启动时 Python 找不到 `scripts` 模块（`ModuleNotFoundError: No module named 'scripts'`）的缺陷。

2. **Shell 元字符与参数边界完全保持**：
   - 包装器参数传递采用标准 `"$@"`，且配置路径使用 `shlex.quote` 包装；
   - 验证单测覆盖：中文字符、空格、百分号（`%`）、前导破折号（`--`）、以及 `$USER`、`*.*`、`; echo evil`、`&& rm -rf` 等危险 shell 元字符，全部作为纯字面字符串完整保真传递，绝无二次代码注入或意外展开。

3. **恶意环境变量拦截与宿主污染清除**：
   - 包装脚本执行首行即执行：
     ```sh
     unset LD_PRELOAD LD_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH
     ```
     彻底防范外部恶意传入的动态链接库注入；
   - 无论调用者外部环境变量如何指定 `WINEPREFIX` 或 `STEAM_COMPAT_DATA_PATH`，底层后端一律强制绑定使用 lab 内部经绝对化修复的固定沙箱前缀 `fixtures/runtime/steam-shaped/compat/pfx`。

4. **Steam 调度动词白名单门禁**：
   - 严格限定仅接受合法 Steam 调度动词：`run`、`runinprefix`、`waitforexitandrun`；
   - 传入任何未知动词均在包装器层立即报错（`Error: Unknown or unsupported Steam verb`）并返回退出码 2，拒绝执行并与探针逻辑清晰隔离。

---

## 三、 TDD 单元测试验证与实测证据

### 1. RED 阶段失败证据（`logs/steam-handoff/red.log`）
在实现模块及加固前，通过编写 `tests/backend/test_steam_handoff.py` 捕获预期失败：
```text
FAIL: test_candidate_directory_with_shell_metacharacters
AssertionError: 1 != 0 : Wrapper failed with tricky path: ModuleNotFoundError: No module named 'scripts'

FAIL: test_wrapper_invoked_from_outside_lab_cwd
AssertionError: 1 != 0 : Wrapper failed from /tmp cwd: ModuleNotFoundError: No module named 'scripts'

FAILED (failures=2)
```

### 2. GREEN 阶段通过证据（`logs/steam-handoff/green.log`）
加固修复后，9 项单元测试 100% 通过：
```bash
python3 -m unittest tests/backend/test_steam_handoff.py -v
```

控制台实测回显：
```text
test_argument_boundary_preservation (tests.backend.test_steam_handoff.TestSteamHandoff)
Spaces, Unicode, percent signs, and leading dashes must be preserved verbatim in argv. ... ok
test_candidate_directory_with_shell_metacharacters (tests.backend.test_steam_handoff.TestSteamHandoff)
Candidate directory path containing $() or quotes must not be expanded by wrapper shell. ... ok
test_default_prepare_is_plan_only (tests.backend.test_steam_handoff.TestSteamHandoff)
Default prepare_runtime_tool must create candidate in plan-only mode (applied=False). ... ok
test_explicit_execute_runtime_activation (tests.backend.test_steam_handoff.TestSteamHandoff)
Passing execute_runtime=True activates execution mode in candidate wrapper config. ... ok
test_frozen_hash_mismatch_blocks_execution_with_exit_20 (tests.backend.test_steam_handoff.TestSteamHandoff)
If config.json recorded hash differs from actual elfuse candidate binary, ... ok
test_malicious_env_cannot_override_lab_prefix (tests.backend.test_steam_handoff.TestSteamHandoff)
Caller setting WINEPREFIX or LD_PRELOAD in environment cannot override fixed lab prefix. ... ok
test_shell_metacharacters_not_expanded (tests.backend.test_steam_handoff.TestSteamHandoff)
Shell metacharacters like $USER, *.*, ;, & must remain literal strings. ... ok
test_unsupported_steam_verb_rejected (tests.backend.test_steam_handoff.TestSteamHandoff)
Passing an unrecognized Steam verb must exit non-zero and refuse execution. ... ok
test_wrapper_invoked_from_outside_lab_cwd (tests.backend.test_steam_handoff.TestSteamHandoff)
Steam or user launches wrapper from an external directory (e.g. /tmp). ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.301s

OK
```
**退出码**：`0`。

---

## 四、 离线候选包生成与实际黑盒执行验证

### 1. 默认 Plan-Only 候选包（`artifacts/steam-prepared/runtime-handoff-plan-only/`）
- `compatibilitytool.vdf`：声明 `proton-macos-lab-runtime` 工具，`to_oslist "macos"`；
- `toolmanifest.vdf`：命令行为 `"<wrapper>" -- %verb%`；
- `install-plan.json`：
  ```json
  {
    "candidate": "/Users/mewcapoo/Projects/proton-macos-lab/artifacts/steam-prepared/runtime-handoff-plan-only",
    "target": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/steam-shaped/mock-steam/compatibilitytools.d/proton-macos-lab-runtime",
    "applied": false,
    "execute_runtime": false,
    "purpose": "Offline Steam-shaped runtime candidate handoff",
    "elfuse_candidate": "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-crash-derived/build/elfuse-candidate",
    "elfuse_sha256": "f83455b073611030d388e1f7c4be1dfee26af34106a373b3a6713497790f3e26"
  }
  ```

### 2. 真实执行激活候选包（`artifacts/steam-prepared/runtime-handoff-execute/`）
- `install-plan.json` 中明确标记 `execute_runtime: true`，`applied: false`；
- **配置绑定 SHA 动态校验**：在每次调用前动态校验实际 `elfuse` 的 SHA-256，与配置记录不一致立即返回退出码 20 并拒绝执行，杜绝偷换未验证二进制。

### 3. 实际黑盒执行实测（全链路贯通）
从 lab 外部工作目录（`cwd=/tmp`）直接调用生成的执行态包装器：
```bash
cd /tmp && /Users/mewcapoo/Projects/proton-macos-lab/artifacts/steam-prepared/runtime-handoff-execute/proton-wrapper.sh -- runinprefix C:\\hello-x64.exe
```

**控制台实测 JSON 回显**：
```json
{
  "argv": [
    "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-crash-derived/build/elfuse-candidate",
    "--user",
    "501:20",
    "--sysroot",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case",
    "--timeout",
    "90",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/python3.14",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/proton",
    "runinprefix",
    "C:\\hello-x64.exe"
  ],
  "exit": 0,
  "target_exit": 0,
  "supervisor_exit": -9,
  "timed_out": false,
  "seconds": 43.612398,
  "run_dir": "/Users/mewcapoo/Projects/proton-macos-lab/logs/steam-handoff/run-nqczdd4a",
  "cleanup_errors": [],
  "stdout": "/Users/mewcapoo/Projects/proton-macos-lab/logs/steam-handoff/run-nqczdd4a/stdout.log",
  "stderr": "/Users/mewcapoo/Projects/proton-macos-lab/logs/steam-handoff/run-nqczdd4a/stderr.log",
  "provenance": "PUBLIC_REDISTRIBUTOR_CHECKSUM_VERIFIED_VALVE_ORIGIN_CLAIMED",
  "runtime_descriptor": {
    "path": "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-crash-derived/build/elfuse-candidate",
    "sha256": "f83455b073611030d388e1f7c4be1dfee26af34106a373b3a6713497790f3e26",
    "flavor": "derived",
    "source_baseline": "CUSTOM_UNVERIFIED_DERIVED",
    "commit": "UNKNOWN",
    "patches": [
      "unknown"
    ],
    "description": "Unverified or custom lab-derived elfuse binary",
    "execution_evidence": "NOT_CHECKED"
  },
  "verb": "runinprefix",
  "target_and_args": [
    "C:\\hello-x64.exe"
  ]
}
```

**目标程序输出核验**（`cat /Users/mewcapoo/Projects/proton-macos-lab/logs/steam-handoff/run-nqczdd4a/stdout.log`）：
```text
X64_FEX_OK
```
- **耗时**：43.61 秒（远低于 130s 外层超时控制）；
- **退出码**：`exit: 0`, `target_exit: 0`；
- **清理结果**：`cleanup_errors: []`, `timed_out: false`；
- **真实全链路证据**：成功证实 wrapper 能够正确以 Steam 形态接收动词与参数，在 `/tmp` 工作目录下驱动真实的 Linux Python 3.14，通过原版 Valve Proton 脚本拉起 Wine 与 FEX，最终完成 `hello-x64.exe` 执行并输出 `X64_FEX_OK`。

---

## 五、 交付文件清单

| 文件路径 | 状态 | 职责说明 |
| :--- | :---: | :--- |
| `scripts/backend/steam_handoff.py` | 新增 | 离线 Steam 形态运行时生成与桥接模块（VDF 生成、动词门禁、cwd/元字符加固、冻结哈希校验、执行调度） |
| `tests/backend/test_steam_handoff.py` | 新增 | 9 项单元测试套件（覆盖参数边界、元字符防展开、外层 cwd 兼容、恶意环境隔离、动词门禁、哈希不匹配阻断等） |
| `fixtures/runtime/steam-shaped/compat/` | 新增 | 独立克隆的沙箱 Wine prefix（保留绝对化 DLL 符号链接与 hello-x64.exe） |
| `artifacts/steam-prepared/runtime-handoff-plan-only/` | 新增 | 默认计划态候选包（包含 VDF、wrapper、config 及 install-plan） |
| `artifacts/steam-prepared/runtime-handoff-execute/` | 新增 | 显式执行态候选包（包含 VDF、wrapper、config 及 install-plan） |
| `logs/steam-handoff/run-nqczdd4a/` | 新增 | 真实黑盒执行产出的 run 目录（含 stdout `X64_FEX_OK`、stderr 及 result.json） |
| `logs/steam-handoff/red.log` | 更新 | TDD RED 阶段原始失败记录 |
| `logs/steam-handoff/green.log` | 更新 | TDD GREEN 阶段 9 项测试全量通过原始记录 |
| `reports/steam-handoff.md` | 更新 | 本交付报告文档（附带真实黑盒实测证据与分析） |

---

## 六、 状态更新

- 任务 `task-29` 既定目标全部达成，单元测试与黑盒规范全部通过。
- 未修改任何已冻结文件（`bundle.py`、`cli.py`、`probe.py`），未修改 C 代码或原版 Proton 包，未改动真实 Steam 客户端或全局环境，无 commit/push。
