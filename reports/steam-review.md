# Steam 离线日志适配器独立代码审查报告

**报告日期**：2026-10-15  
**审查角色**：`lab-reviewer`（独立代码审查员）  
**被审角色**：`steam-probe-worker`（Steam 适配器执行员）  
**审查任务**：`task-8`（提前复审 Steam 离线日志适配器）  
**关联任务**：`task-5`（实现离线 Steam 日志适配器与单元测试）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  

---

## 1. 审查范围与原则

依据任务书定义与项目全局准则，本审查严格遵循以下界限与规范：
1. **审查目标与范围**：仅限 `scripts/steam/probe.py`、`tests/steam/*`、`scripts/steam/candidate/*` 及执行员交付的 `reports/steam-probe.md`。
2. **零环境污染与只读承诺**：本审查**未修改任何 Steam 客户端配置或系统全局环境**，**未修改生产代码与执行员测试用例**，**未执行任何 Git commit/push 操作**。
3. **两阶段审查法**：先规格合规审查（Specification Review），再代码质量审查（Code Quality Review）。
4. **验证在先原则（Verification-Before-Completion）**：所有审查结论均建立在独立环境命令执行与新鲜回显证据之上，绝不盲目采信执行员自述。
5. **测试环境绝对隔离**：所有测试与复现均在实验根目录下运行，`HOME` 与 `TMPDIR` 均重定向至 `logs/review/steam/` 内部。

---

## 2. 第一阶段：规格合规审查（Specification Review）

对照设计规范逐项进行静态代码溯源与逻辑核验：

| 规格要求项 | 实现位置与代码证据 | 审查判定 | 详情说明 |
| :--- | :--- | :--- | :--- |
| **1. 仅记录日志，绝不 exec 游戏** | `scripts/steam/probe.py:17-25, 318-335` | **通过 (PASS)** | 模块无 `subprocess`、`os.system`、`os.exec*` 等执行原语，仅提取参数与环境并写入 JSON 后以退出码 0 退出；`test_game_not_executed` 验证传入可执行脚本不会被触发执行。 |
| **2. 严格 Steam 环境白名单** | `scripts/steam/probe.py:61-82, 221-234` | **通过 (PASS)** | 定义静态常量集合 `SAFE_STEAM_ENV_WHITELIST`（包含 `STEAM_COMPAT_CLIENT_INSTALL_PATH`、`STEAM_COMPAT_APP_ID` 等 19 个安全路径与标识）；`filter_env` 彻底丢弃非白名单的系统变量（如 `PATH`, `USER`, `HOME`, 云凭证等），并二次校验排除带敏感词的 Steam 变量。 |
| **3. 常见凭据/Header/URL 脱敏** | `scripts/steam/probe.py:27-58, 85-150, 153-219` | **通过 (PASS)** | 覆盖 `token/ticket/cookie/password/passwd/auth/secret/credential/api-key` 等键名特征；覆盖 camelCase/kebab/snake/百分号编码；完整剔除 URL 中 `userinfo`（`[REDACTED]@`）及 Query/Fragment 敏感参数；对 `-H`/`--header` 及独立 HTTP Header（`Authorization: Bearer ...`, `Cookie: ...`）规范脱敏。 |
| **4. 正常 Unicode 与空格完整保留** | `scripts/steam/probe.py:214-218, 298` | **通过 (PASS)** | 非敏感参数直接原样 `append`，不进行多余转义或剥离；`json.dumps` 采用 `ensure_ascii=False`，保留中文原生 UTF-8 编码与各种空格（含全角空格、制表符、不间断空格等）。 |
| **5. `--` 分隔符不吞游戏参数** | `scripts/steam/probe.py:246-251` | **通过 (PASS)** | `parse_cli_args` 中一旦遇到 `--`，立即将后续所有参数加入 `remaining` 并中断探针选项解析，确保目标游戏的 `--log-dir` 等参数不会被探针错误吞噬。 |
| **6. 文件 0600 独占并发不覆盖** | `scripts/steam/probe.py:281-306` | **通过 (PASS)** | 文件名包含微秒级时间戳、PID 与 UUID8 前缀；底层通过 `os.open(..., os.O_CREAT \| os.O_EXCL \| os.O_WRONLY, 0o600)` 原子创建，若文件已存在直接抛出错误，权限严格限定为 `0600`（所有者独占读写）。 |
| **7. 异常退出码非零** | `scripts/steam/probe.py:254, 276, 279, 306, 313, 324` | **通过 (PASS)** | 缺少 `--log-dir`、目标目录不存在、路径非目录、文件创建失败、写入异常均输出清晰 `sys.stderr` 并以 `sys.exit(1)` 非零退出。 |
| **8. 候选 VDF 契约合规与环境依赖** | `scripts/steam/candidate/*` | **通过 (PASS)** | 经返工修复后，`commandline` 标准注入 `-- %verb%`；`format_vdf_arg` 正确转义带空格路径；解耦并明确界定三阶段；记录 Python 解释器实际路径依赖。 |

---

## 3. 第二阶段：代码质量与架构审查（Code Quality Review）

1. **依赖纯净度**：
   - `probe.py` 与 `candidate/generate_candidate.py` 仅使用 Python 3 标准库，无任何第三方运行时依赖，部署与离线调用摩擦为零。
2. **防注入与鲁棒性**：
   - 敏感标志处于参数末尾时（如 `--auth` 无后续值、`-H` 无后续值），索引守卫安全防止了 `IndexError` 越界异常；
   - 针对带连字符的凭据值（如 `--auth -dash_secret`），代码将其正确识别为待脱敏的值而非解析为下一个 flag，避免凭据泄漏。
3. **安全纵深防御**：
   - 文件写入使用独占文件描述符（`fd`）包装 `open(fd, "wb", closefd=True)`，即使多进程瞬间并发，文件系统层面也绝无重名覆盖或截断竞态。
4. **VDF 语法与参数转义稳健性**：
   - `generate_candidate.py` 内置 `format_vdf_arg`，当路径中包含空格、制表符或双引号时，自动进行 `\"...\"` 转义，避免 Steam VDF 解析器出现语法分裂。
   - `test_candidate.py` 中通过模拟 Steam 动词替换 `waitforexitandrun` 及包含游戏自有 `--log-dir /game/internal/logs` 参数，端到端实测验证探针准确捕捉 Steam 动词且游戏参数完全不受破坏。

---

## 4. 独立验证与实测证据（Verification Evidence）

审查员在隔离环境中独立执行两组测试套件，日志存放在 `logs/review/steam/` 目录下：

### 4.1 执行员套件独立全量重跑（20/20 PASS）

覆盖 `tests/steam/test_probe.py`（15 项）与 `tests/steam/test_candidate.py`（5 项）：

**执行命令**：
```bash
HOME=/Users/mewcapoo/Projects/proton-macos-lab/logs/review/steam/fake_home \
TMPDIR=/Users/mewcapoo/Projects/proton-macos-lab/logs/review/steam/fake_tmp \
python3 -m unittest discover -s tests/steam -v
```

**实测回显（记录于 `logs/review/steam/worker_test_final.log`）**：
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
Ran 20 tests in 1.324s

OK
```
- **测试结果**：20 项测试全量通过，失败数 0，错误数 0，退出码 0。

---

### 4.2 审查员自选额外边界测试（9/9 PASS）

审查员自选深度边界测试套件 `logs/review/steam/test_boundary_review.py`，覆盖全角空格（`\u3000`）、不间断空格（`\u00a0`）、Emoji/制表符保留、末尾敏感 flag 无越界、端口/编码 userinfo URL 脱敏、参数内嵌 URL 脱敏、等号语法、空参数输出、嵌套 `--` 保留、0600 权限位断言及 30 线程高并发零竞态测试。

**执行命令**：
```bash
HOME=/Users/mewcapoo/Projects/proton-macos-lab/logs/review/steam/fake_home \
TMPDIR=/Users/mewcapoo/Projects/proton-macos-lab/logs/review/steam/fake_tmp \
python3 /Users/mewcapoo/Projects/proton-macos-lab/logs/review/steam/test_boundary_review.py -v
```

**实测回显（记录于 `logs/review/steam/reviewer_boundary_test_final.log`）**：
```text
test_double_dash_followed_by_double_dash (__main__.TestReviewerBoundaryScenarios)
Verify probe preserves nested '--' meant for target game. ... ok
test_empty_argv_graceful (__main__.TestReviewerBoundaryScenarios)
Verify probe without game arguments produces valid log with empty argv list. ... ok
test_exact_permission_and_json_structure (__main__.TestReviewerBoundaryScenarios)
Verify exact 0600 mode and valid UTF-8 JSON without trailing corruption. ... ok
test_high_concurrency_stress_30 (__main__.TestReviewerBoundaryScenarios)
Stress test with 30 concurrent invocations ensuring zero collisions and exact counts. ... ok
test_log_dir_equals_syntax (__main__.TestReviewerBoundaryScenarios)
Verify probe accepts --log-dir=/path/to/logs syntax. ... ok
test_non_sensitive_flag_with_url_value (__main__.TestReviewerBoundaryScenarios)
Verify --web-endpoint=https://user:pass@host/callback?token=123 has URL sanitized inside val. ... ok
test_sensitive_flag_at_tail_no_crash (__main__.TestReviewerBoundaryScenarios)
Verify standalone sensitive flags at the end of argv do not cause index out of bounds. ... ok
test_unicode_and_special_spaces_preservation (__main__.TestReviewerBoundaryScenarios)
Verify normal spaces, multiple spaces, tabs, and full-width/non-breaking spaces are preserved verbatim. ... ok
test_url_with_port_userinfo_and_encoded_query (__main__.TestReviewerBoundaryScenarios)
Verify URL with port, complex percent-encoded userinfo, sensitive query, and sensitive fragment. ... ok

----------------------------------------------------------------------
Ran 9 tests in 1.061s

OK
```
- **测试结果**：9 项边界测试全部通过，失败数 0，错误数 0，退出码 0。

---

## 5. 审查闭环追踪（Defects Closed）

| 原始问题 | 修复状态 | 验证证据 |
| :--- | :--- | :--- |
| **`toolmanifest.vdf` 缺少 `%verb%` 与 `--` 分隔符** | **已闭环 (CLOSED)** | `toolmanifest.vdf.template` 与 `generate_candidate.py` 均更新为 `... --log-dir ... -- %verb%`；`test_simulated_steam_verb_substitution_and_game_log_dir` 端到端模拟 Steam 替换动词实测通过。 |
| **带空格/特殊字符路径的转义处理** | **已闭环 (CLOSED)** | `generate_candidate.py` 增加了 `format_vdf_arg`，当路径含空格或引号时自动添加 `\"...\"` 转义；`test_format_vdf_arg_quoting` 与 `test_generation_with_spaces_in_paths` 均通过。 |
| **Python 解释器环境记录与可执行检查** | **已闭环 (CLOSED)** | 真实记录当前解释器路径 `sys.executable` 并通过 `test_python_executable_exists_and_usable` 断言其存在与执行权限；在 `candidate/README.md` 与 `reports/steam-probe.md` 中诚实声明该本机环境依赖。 |

---

## 6. 审查结论与交付签字

1. **测试统计汇总**：
   - 执行员全量自动化测试（含 probe 与 candidate）：**20 / 20 通过**（通过率 100%）
   - 审查员独立边界测试：**9 / 9 通过**（通过率 100%）
   - 累计独立实测用例数：**29 / 29 全部通过**
2. **最终审查判定**：**批准通过 (APPROVED)**
   - `scripts/steam/probe.py` 严格履行了无副作用日志记录、确定性敏感信息脱敏、严格环境白名单、POSIX `--` 选项隔离、高并发 0600 独占写入及非零异常退出规范。
   - `candidate/` 模板、生成器与测试套件完全忠于 Valve 兼容工具 Version 2 接口规范，`-- %verb%` 契约落地严密，离线研究与阶段解耦说明详尽。
   - 本阶段审查闭环，`task-8` 正式完成，审查员转入就绪待命（inactive）状态，等待 Team Lead 唤醒认领 `task-7`（执行层整体验收）。
