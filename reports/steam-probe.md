# Steam 探测适配器实现与离线验证报告

**报告日期**：2026-10-15  
**执行角色**：`steam-probe-worker`（Steam 适配器执行员）  
**关联任务**：`task-5`（实现离线 Steam 日志适配器与单元测试）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  

---

## 1. 执行摘要与安全承诺

本阶段工作已严格按照经用户批准的实施计划完成，所有工作均在隔离实验目录内进行：
1. **纯标准库实现**：完成 `scripts/steam/probe.py`，无任何第三方包依赖，纯离线运行。
2. **零副作用保证**：适配器**仅记录日志，绝不调用 exec 执行任何目标游戏，绝不发起任何网络请求**。
3. **Steam 状态诚实声明**：本阶段**未探测、未安装、未修改真实 Steam 客户端及其配置**。本机未进行任何全局包安装或 Git commit/push 操作。
4. **测试驱动开发（TDD）全绿交付**：完整经历了 RED（失败）→ GREEN（全部通过）的测试闭环，累计 20 项单元与集成测试 100% 通过（耗时 1.273s，退出码 0），覆盖探针核心逻辑与候选 VDF 生成器。

---

## 2. 文件职责与目录划分

| 文件/目录路径 | 职责与归属 | 说明 |
| :--- | :--- | :--- |
| `scripts/steam/probe.py` | 适配器主脚本（执行员） | 解析 `--log-dir`、脱敏 argv、过滤 Steam 环境白名单、以 0600 权限独占写入 JSON 日志 |
| `tests/steam/test_probe.py` | 适配器自动化测试套件（执行员） | 覆盖 15 项边界测试（编码、脱敏、并发、安全、环境白名单等），环境完全隔离在 lab 内 |
| `tests/steam/test_candidate.py` | 候选生成器测试套件（执行员） | 覆盖 5 项生成器测试（Valve 语法校验、`-- %verb%` 命令格式、带空格路径引号转义、Python 解释器有效性及端到端参数模拟） |
| `scripts/steam/candidate/` | 离线 VDF 候选模板（执行员） | 包含 `compatibilitytool.vdf.template`、`toolmanifest.vdf.template`、生成脚本及规范文档 |
| `logs/steam/` | 实验日志目录（执行员） | 包含单元测试与样本执行生成的真实 JSON 日志，权限受控 |
| `reports/steam-probe.md` | 交付报告（执行员） | 本报告文档 |

---

## 3. TDD 测试演进与实测证据

### 3.1 RED 阶段证据（编写测试后运行验证失败）

在实现各模块前，先编写自动化测试，捕获预期的失败（RED）：

**阶段一（初始 10 项探针接口用例，未实现脚本前）**：
```text
test_env_sensitive_steam_vars_excluded (test_probe.TestSteamProbe) ... ERROR
test_env_whitelist (test_probe.TestSteamProbe) ... ERROR
test_exclusive_creation_and_concurrency (test_probe.TestSteamProbe) ... FAIL
test_game_not_executed (test_probe.TestSteamProbe) ... ERROR
test_json_validity_and_schema (test_probe.TestSteamProbe) ... ERROR
test_normal_argv_preserved (test_probe.TestSteamProbe) ... ERROR
test_path_error_missing_log_dir (test_probe.TestSteamProbe) ... FAIL
test_path_error_nonexistent_dir (test_probe.TestSteamProbe) ... FAIL
test_sensitive_argv_redaction (test_probe.TestSteamProbe) ... ERROR
test_unicode_and_spaces_in_argv (test_probe.TestSteamProbe) ... ERROR

Ran 10 tests in 0.421s
FAILED (failures=3, errors=7)
```

**阶段二（根据 Lead 架构审查，新增 5 项强化边界用例）**：
```text
test_auth_flag_with_dash_prefixed_secret (test_probe.TestSteamProbe) ... FAIL
test_authorization_headers (test_probe.TestSteamProbe) ... FAIL
test_double_dash_delimiter_preserves_game_log_dir (test_probe.TestSteamProbe) ... ERROR
test_file_permission_0600 (test_probe.TestSteamProbe) ... FAIL
test_url_userinfo_fragment_and_encoded_keys (test_probe.TestSteamProbe) ... FAIL

Ran 15 tests in 1.637s
FAILED (failures=4, errors=1)
```

**阶段三（复审反馈，为 VDF 生成器新增 5 项严格格式与转义用例）**：
```text
ImportError: cannot import name 'format_vdf_arg' from 'scripts.steam.candidate.generate_candidate'
FAILED (errors=1)
```

### 3.2 GREEN 阶段证据（最小实现与边界覆盖后全量通过）

实现所有要求后，重新执行全量测试套件：

**执行命令**：
```bash
python3 -m unittest discover -s tests/steam -v
```

**控制台实测完整回显**：
```text
test_default_generation_structure (test_candidate.TestCandidateVdfGenerator)
Test default candidate generation creates files with required fields. ... ok
test_format_vdf_arg_quoting (test_candidate.TestCandidateVdfGenerator)
Test that paths with spaces or special characters are properly quoted and escaped. ... ok
test_generation_with_spaces_in_paths (test_candidate.TestCandidateVdfGenerator)
Test candidate generation when paths contain spaces. ... ok
test_python_executable_exists_and_usable (test_candidate.TestCandidateVdfGenerator)
Verify the Python interpreter used in candidate is existing and functional. ... ok
test_simulated_steam_verb_substitution_and_game_log_dir (test_candidate.TestCandidateVdfGenerator)
Simulate Steam executing commandline by substituting %verb% with ... ok
test_auth_flag_with_dash_prefixed_secret (test_probe.TestSteamProbe)
Test that sensitive flags like --auth redacts values even if they start with a dash. ... ok
test_authorization_headers (test_probe.TestSteamProbe)
Test that Authorization, Cookie, and sensitive HTTP headers are redacted. ... ok
test_double_dash_delimiter_preserves_game_log_dir (test_probe.TestSteamProbe)
Test that '--' delimiter protects game-level --log-dir flags from being consumed by probe. ... ok
test_env_sensitive_steam_vars_excluded (test_probe.TestSteamProbe)
Test that sensitive Steam-prefixed variables are excluded even if they look like Steam env. ... ok
test_env_whitelist (test_probe.TestSteamProbe)
Test strict Steam environment whitelisting: only safe Steam keys captured, general env dropped. ... ok
test_exclusive_creation_and_concurrency (test_probe.TestSteamProbe)
Test that concurrent invocations create exclusive log files without collision or overwriting. ... ok
test_file_permission_0600 (test_probe.TestSteamProbe)
Test that created log file has secure 0600 file permissions. ... ok
test_game_not_executed (test_probe.TestSteamProbe)
Test that probe only logs and NEVER executes the target executable or shell script. ... ok
test_json_validity_and_schema (test_probe.TestSteamProbe)
Test that log file is strictly valid JSON containing timestamp, pid, cwd, argv, env. ... ok
test_normal_argv_preserved (test_probe.TestSteamProbe)
Test that regular gaming and Steam command-line options are never falsely redacted. ... ok
test_path_error_missing_log_dir (test_probe.TestSteamProbe)
Test that omitting --log-dir returns non-zero error. ... ok
test_path_error_nonexistent_dir (test_probe.TestSteamProbe)
Test that invalid or non-existent log directory returns non-zero error. ... ok
test_sensitive_argv_redaction (test_probe.TestSteamProbe)
Test that sensitive tokens, passwords, tickets, and URLs are redacted. ... ok
test_unicode_and_spaces_in_argv (test_probe.TestSteamProbe)
Test that Chinese characters and spaces in parameters are preserved verbatim. ... ok
test_url_userinfo_fragment_and_encoded_keys (test_probe.TestSteamProbe)
Test URL sanitization: userinfo username/pass, fragment tokens, accessToken, and percent-encoded keys. ... ok

----------------------------------------------------------------------
Ran 20 tests in 1.273s

OK
```
**退出状态码**：`0`。原始输出落盘于 `logs/steam/unittest_green.log`。

### 3.3 真实样本调用与日志输出检验

在 `logs/steam/` 下实际运行单次探测调用：
```bash
STEAM_COMPAT_APP_ID=12345 \
STEAM_COMPAT_CLIENT_INSTALL_PATH="/Users/mewcapoo/Library/Application Support/Steam" \
python3 scripts/steam/probe.py --log-dir /Users/mewcapoo/Projects/proton-macos-lab/logs/steam \
  -- waitforexitandrun "/SteamLibrary/steamapps/common/黑神话 悟空/b1.exe" \
  -novid -lang zh-CN -H "Authorization: Bearer mock_secret_token" --auth -dash_secret
```

生成的文件 `/Users/mewcapoo/Projects/proton-macos-lab/logs/steam/probe-20261015-010232-591119-13334-35779a9b.json`（权限 `-rw-------`，即 0600）内容如下：
```json
{
  "timestamp": "2026-10-15T01:02:32.591119+00:00",
  "pid": 13334,
  "cwd": "/Users/mewcapoo/Projects/proton-macos-lab",
  "argv": [
    "waitforexitandrun",
    "/SteamLibrary/steamapps/common/黑神话 悟空/b1.exe",
    "-novid",
    "-lang",
    "zh-CN",
    "-H",
    "Authorization: Bearer [REDACTED]",
    "--auth",
    "[REDACTED]"
  ],
  "env": {
    "STEAM_COMPAT_CLIENT_INSTALL_PATH": "/Users/mewcapoo/Library/Application Support/Steam",
    "STEAM_COMPAT_APP_ID": "12345"
  }
}
```

---

## 4. 关键特性与设计细节

1. **中文与空格完整保留**：
   - 参数中的中文、空格（如 `/SteamLibrary/steamapps/common/黑神话 悟空/b1.exe`、`带 空格 和 中文 的 启动参数`）完全按原始字符串保留，不转义、不丢失。
2. **敏感信息模式脱敏（启发式与最佳实践）**：
   - 键值对脱敏：支持 camelCase（如 `accessToken`）、kebab-case（如 `--connect-token`）、snake_case（如 `session_ticket`）及百分号编码（如 `access%5Ftoken`）。
   - 独立敏感 flag 脱敏：如 `--token secret`、`--auth -dash_secret`，无论后续参数是否带前缀连字符，均安全脱敏为 `[REDACTED]`。
   - 协议头脱敏：识别 `-H` / `--header` 及独立的 HTTP 认证头（如 `Authorization: Bearer ...`、`Cookie: ...`、`X-Api-Key: ...`）。
   - URL 脱敏：将完整的 userinfo（包含用户名与密码）统一脱敏为 `[REDACTED]@`，并覆盖 Query 与 Fragment（`#`）中的敏感字段。
   - 声明：本适配器执行确定性的模式匹配与过滤，不对任意无规律自然语言文本提供自然语言理解级保证。
3. **严格的环境白名单**：
   - 绝不记录操作系统全量环境（彻底排除 `USER`, `HOME`, `PATH`, `SHELL`, 云凭据, 环境变量等）。
   - 仅白名单收录已知的 Proton/Steam 运行变量（如 `STEAM_COMPAT_APP_ID`, `STEAM_COMPAT_DATA_PATH` 等安全路径与 ID）。
   - 即使以 `STEAM_` 开头，只要含有 `TOKEN`, `TICKET`, `PASSWORD`, `COOKIE`, `AUTH` 等敏感特征，一律自动剔除。
4. **高并发独占创建**：
   - 命名格式：`probe-{UTC_TIMESTAMP}-{PID}-{UUID8}.json`。
   - 底层使用 `os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)` 进行原子排他创建，从文件系统层面杜绝同名覆盖或竞争条件破坏。
5. **CLI 稳健性**：
   - 支持标准 POSIX `--` 选项分隔符：`--` 之后的参数完全归属游戏 argv，即使游戏自带 `--log-dir` 选项也不会被探针错误吞噬。
   - 缺失 `--log-dir` 或指向非法/不存在路径时，输出清晰的 stderr 错误信息并返回退出码 1。

---

## 5. 候选 VDF 规范与离线模板设计

在 `scripts/steam/candidate/` 目录下提供了完整的规范文档与离线生成工具：

### 5.1 三阶段独立性辨析（不可混淆）

在未来进行客户端探测时，必须严格区分以下三个完全解耦的阶段：
1. **阶段 1：Manifest 发现（Discovery）**：
   - Steam 客户端启动时仅解析 `compatibilitytools.d/*/compatibilitytool.vdf`，确认工具注册语法。
2. **阶段 2：列表可选（UI Dropdown Selectable）**：
   - 客户端 UI 是否渲染并在兼容性下拉列表中展示该工具。macOS 客户端对 Windows-only 游戏有原生 UI 过滤机制，阶段 1 成功绝不保证阶段 2 可见。
3. **阶段 3：Play 实际调用（Play Invocation）**：
   - 用户点击「Play」后，Steam 是否真正调用 `toolmanifest.vdf` 中定义的 `commandline`。调用成功仅代表外壳调度成功，绝不等于游戏本体能在 macOS 架构下正常渲染或运行，更不代表 Steamworks API / DRM 校验通过。

### 5.2 `to_oslist "macos"` 属性说明

- Valve 的 `steam-compat-tool-interface.md` 中虽然存在 `to_oslist` 字段，但在 macOS 平台声明 `"to_oslist" "macos"` **纯属语法元数据，绝非 Valve 官方对客户端功能或运行时调度的技术承诺**。

### 5.3 社区历史先验辨析（Kaon 路径纠偏）

社区项目（如 `natbro/kaon` 2025 年初的探索记录）包含若干历史遗留问题：
- **路径拼写笔误**：社区文档中存在非标准的目录大小写与路径层级笔误。本项目严格遵守 Valve 官方标准，不盲从社区笔误。
- **未经验证的假设**：包括 `steam_dev.cfg` 平台覆盖、`appinfo.vdf` 启动项重定向、在 Wine 内部额外嵌套 Windows Steam 客户端承担 Steamworks 通信等设想。这些机制在当前最新版 macOS Steam 客户端中均属**未经实测验证的社区假设**，严禁伪装为可直接落地的方案。

### 5.4 真实路径候选生成器与 `-- %verb%` 规范

提供 `scripts/steam/candidate/generate_candidate.py`，能够自动根据 lab 内部的绝对路径生成无占位假变量的真实样例：
- `compatibilitytool.vdf`：
  ```vdf
  "compatibilitytools"
  {
    "compat_tools"
    {
      "proton_macos_probe"
      {
        "install_path" "."
        "display_name" "macOS Proton Probe (Offline Research Tool)"
        "from_oslist"  "windows"
        "to_oslist"    "macos"
      }
    }
  }
  ```
- `toolmanifest.vdf`：
  ```vdf
  "manifest"
  {
    "commandline" "/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9 /Users/mewcapoo/Projects/proton-macos-lab/scripts/steam/probe.py --log-dir /Users/mewcapoo/Projects/proton-macos-lab/logs/steam -- %verb%"
    "version" "2"
    "use_sessions" "1"
  }
  ```

#### 关键技术规范说明：
1. **`-- %verb%` 结构与调度保障**：
   - Valve 兼容工具接口定义中，Steam 客户端调用工具时会将 `%verb%` 替换为具体动作词（通常为 `waitforexitandrun` 或 `run`）及随后的游戏路径与启动参数。
   - 将 `--` 置于 `--log-dir` 参数之后、`%verb%` 之前：使得探针在解析完自身 `--log-dir` 选项后立即终结选项扫描，确保 Steam 动词成为记录的 `argv[0]`，并从根本上防止游戏自有的 `--log-dir` 或带破折号的参数被探针误吞。
2. **带空格与引号路径的自动转义**：
   - 生成脚本内置 `format_vdf_arg`，当路径中存在空格或特殊字符时，自动在 VDF 内转义为 `\"...\"`，并通过自动化测试套件 `test_candidate.py` 进行严格断言验证。
3. **解释器环境真实记录**：
   - 采用本机真实存在的 Python 解释器绝对路径（`sys.executable`），并通过测试断言该解释器具备实际可执行权限。同时明确记录其依赖，不脱离宿主环境伪造全局 `/usr/bin/python3`。

---

## 6. 下一阶段客户端实测需用户确认的提案

若后续用户决定对宿主 macOS Steam 客户端开展探测，必须遵循以下前置约束并获得用户逐项确认：

### 6.1 具体拟修改操作（最小接触面）
- 目标目录：`~/Library/Application Support/Steam/compatibilitytools.d/proton_macos_probe/`。
- 拟写入文件：仅限上述生成的 `compatibilitytool.vdf` 与 `toolmanifest.vdf`。
- 严禁行为：严禁修改 Steam 客户端主程序、任何 `appinfo.vdf`、`packageinfo.vdf` 或主库配置文件。

### 6.2 备份与回滚方案
- **备份方案**：在放置任何候选文件前，自动备份现有的整个 `compatibilitytools.d` 目录（若存在）及 Steam 用户配置。
- **一键回滚**：提供单行撤销命令：
  ```bash
  rm -rf ~/Library/Application\ Support/Steam/compatibilitytools.d/proton_macos_probe
  ```
  保证只需删除该子目录即可 100% 恢复客户端原始状态。

### 6.3 宿主环境基线记录要求
- 在任何探测开始前，必须由独立脚本记录宿主环境快照：
  - Steam 客户端版本（Client Build Date / Timestamp）
  - Steam 更新通道（Stable / Beta）
  - 宿主系统信息（macOS 版本、内核构建号、架构）

### 6.4 独立 Steam 库隔离
- 探测测试严禁在用户日常存放几十款游戏的主库中进行。
- 必须在实验目录内新建一个独立的 Steam Library Folder（例如 `/Users/mewcapoo/Projects/proton-macos-lab/steam_test_library`），仅用于安装 1 款经过授权的轻量级 Windows-only 测试游戏，将实验影响彻底控制在沙箱内部。

---

## 7. 结论

`task-5` 的所有既定目标已全部达成。适配器脚本已交付并经过严密自测，离线 VDF 规范与回滚提案齐备，随时可供独立审查员（Reviewer）进行二次复核。
