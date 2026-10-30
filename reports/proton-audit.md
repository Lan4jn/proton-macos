# 官方 Valve 原版 ARM64 Proton 获取与依赖审计报告 (第 2 轮复审修订版)

**实验日期**：2026-10-15  
**执行员**：`proton-package-worker`  
**关联任务**：`task-4`（原版 ARM64 Proton 身份与依赖审计）  
**宿主环境**：Apple Silicon macOS 27.0.1 (Build 26A434, arm64, Rosetta 2 可用, 磁盘可用空间 246 GiB)  
**交付物路径**：
- 元数据身份描述：`artifacts/proton/identity.json`
- 可复现获取/鉴权验证脚本：`scripts/proton/fetch_proton.sh`
- 超时保护包装器：`scripts/proton/tools/run_timeout.py`
- 纯标准库 ELF/PE 审计工具：`scripts/proton/audit_proton.py`
- 审计工具单测：`scripts/proton/test_audit_proton.py`
- 获取探测离线单测：`scripts/proton/test_fetch_proton.py`
- 原始验证基线日志：`logs/proton/steamcmd_app_info.log`, `logs/proton/steamcmd_download_anonymous.log`, `logs/proton/steamcmd_download_depot_anonymous.log`, `logs/proton/check.XXXXXX/`

---

## 1. 结论与执行摘要 (Executive Summary)

1. **版本身份核实与版本号解耦**：
   - 官方 Valve 原版 ARM64 Proton 在 Steam 发行体系中的正式身份确认为 **Steam App 4427310**（`Proton Experimental (ARM64)`），数据包为 **Depot 4427311**，当前已知 Steam 构建版本为 **Build ID: 25406135**（Change Number: 39839235）。
   - 上游 GitHub 官方源码仓库 `ValveSoftware/Proton` 最新稳定 Tag 为 `proton-11.0-2e`（支持 `--target-arch=arm64`）。**特别澄清**：该 tag 纯属源码仓库标签，绝不代表 Steam 二进制 Experimental 包的版本，不得混淆。
   - 本轮通过 GitHub REST API 枚举的前 30 个 releases 结果显示：所有 release 对象的 `assets` 字段均为空列表 `[]`，仅提供源代码 tarball，官方未在 GitHub Releases 提供预编译二进制包。
2. **本轮核实的预编译分发路径**：
   - 本轮核实到官方预编译 ARM64 二进制发行包的发行路径为 **Steam depot**（App `4427310` / Depot `4427311`）。
3. **获取阻断（First Blocker）与严格隔离**：
   - App `4427310` 的元数据标记为 `"section_type": "ownersonly"`，Steam 公开匿名通道（`anonymous`）无订阅权限，返回明确阻断：`Not for anonymous users. ERROR! Failed to install app '4427310' (No subscription)`。
   - 按照实验规范硬性约束，严格禁止读取宿主真实 Steam 账号、Token 或本地凭据库；严格禁止以 GloriousEggroll (GE) 或 CachyOS 等第三方编译包冒充 Valve 官方原版。
   - 实验内工具 `scripts/proton/fetch_proton.sh` 实行严格参数校验、有界超时（35秒）与独立 `TMPDIR`/`HOME` 隔离，并显式禁用实验内账号密码输入（`--username` 返回 exit 2 拒绝），避免凭据泄露。
   - 本阶段交付物收敛为 **`metadata-only`** 身份凭据、获取阻断证据、离线 ELF/PE 静态审计器与可复现验证脚本。本地包 SHA-256 按规范置为 `null`，严禁伪造。

---

## 2. 官方身份与发布源调查

### 2.1 GitHub 官方仓库 (`ValveSoftware/Proton`)
通过 GitHub REST API 对官方仓库 releases 进行枚举探测：
- 查询目标：`https://api.github.com/repos/ValveSoftware/Proton/releases`
- 观测结果：
  - 本轮枚举的最新的 30 个 Releases（涵盖 `proton-11.0-2e`, `proton-11.0-2`, `proton-11.0-1b`, `proton-11.0-1`, `proton-10.0-4b`, `proton-10.0-4`, `proton-9.0-4` 等）。
  - 该 30 个 release 的 `assets` 列表全部为空（`assets: []`）。
  - 结论：GitHub 官方仓库在本轮枚举范围内仅提供源代码包与 Release Notes，不作为预编译二进制包分发途径。

### 2.2 Steam App 4427310 与 Depot 4427311
结合前期 DroidDeck 组件源线索与 SteamDB 历史记录核实：
- **App ID**: `4427310`
- **App Name**: `Proton Experimental (ARM64)`
- **App Type**: `Tool`
- **Supported OS**: `Linux`
- **Depot ID**: `4427311`
- **Build ID**: `25406135` (公网更新记录：2026-09-21)
- **预估磁盘占用**: `~1.94 GiB` (约 2,083,000,000 字节)
- **预估下载体积**: `~474.41 MiB` (压缩数据)
- **前置容量评估说明**: 
  - `fetch_proton.sh --eval-size` 基于 2026-09-21 观测到的 SteamDB 历史元数据进行量级核查。
  - **声明**：该数值为历史元数据估算值，表明包量级远低于 8 GiB 报警上限（1.94 GiB <= 8 GiB），但不对当前远端实际包体积提供绝对下载上限保证。

---

## 3. 隔离保证与独立日志架构

### 3.1 严格环境隔离与超时机制
- **完全隔离环境**：SteamCMD 安装与运行前缀限定在 `scripts/proton/tools/steamcmd/`，`HOME` 强制重定向至 `scripts/proton/tools/steamcmd/home/`，`TMPDIR` 强制重定向至 `scripts/proton/tools/steamcmd/tmp/`。
- **零配置污染**：宿主 `~/Library/Application Support/Steam`、`~/.steam` 保持 100% 未读未写。
- **超时与子进程清理**：封装 `scripts/proton/tools/run_timeout.py`，为所有 SteamCMD 调用施加 35 秒上限，超时自动终止进程树并返回 exit 124，避免命令悬挂。

### 3.2 独立日志目录与 Stage 1/2 证据隔离
为确保审计证据不可篡改与可追溯性，`fetch_proton.sh` 实行以下日志规范：
1. **零删除 (No Deletion)**：脚本内全面移除 `rm -f` 操作，严禁覆盖历史基线证据。
2. **独立 Run 目录**：每次执行 `--check-only` 均通过 `mktemp -d logs/proton/check.XXXXXX` 创建唯一运行目录。
3. **分阶段独立日志**：
   - Stage 1（查询 App 元数据）：输出重定向至 `${run_dir}/stage1_app_info.log`。
   - Stage 2（探测应用更新与授权）：输出重定向至 `${run_dir}/stage2_app_update.log`。
   - 终验分类严格基于 Stage 2 的真实输出，两阶段日志相互隔离不覆盖。

### 3.3 状态码定义与故障分类
- **`0`**：前置容量预检通过 (`--eval-size`)。
- **`2`**：参数语法错误或调用已被禁用的功能（如 `--username` 返回 exit 2）。
- **`10`**：curl/tar 安装失败、非预期进程退出、网络无法连接 Steam 服务器或操作超时（`unknown / network failure`）。错误日志完整保留于目标目录。
- **`20`**：明确证实获取被 Steam 鉴权阻断（`blocked / No subscription`）。

---

## 4. 二进制分析器与单测自检证据

### 4.1 审计能力与规范覆盖 (`scripts/proton/audit_proton.py`)
分析器基于 Python 3 标准库，具备独立静态解析能力：
1. **ELF 模块审计**：
   - 验证 Magic `\x7fELF`、`ELFCLASS64`、Little-Endian、Machine 架构（`EM_AARCH64 = 183`）。
   - 提取 `PT_INTERP` 动态解释器路径（预期 `/lib/ld-linux-aarch64.so.1`）。
   - 遍历 `PT_DYNAMIC` 与 `.dynstr`，提取全量 `DT_NEEDED` 共享库依赖。
   - 解析 `.gnu.version_r` (Verneed/Vernaux) 结构，提取所依赖的最高 `GLIBC_2.xx` 及 `GLIBCXX_3.4.xx` 符号版本。
2. **PE / FEX 模块审计**：
   - 校验 DOS `MZ` 与 COFF `PE\0\0` 签名。
   - 识别 Machine 架构：`IMAGE_FILE_MACHINE_ARM64 (0xaa64)`、`IMAGE_FILE_MACHINE_ARM64EC (0xa641)`、`IMAGE_FILE_MACHINE_AMD64 (0x8664)`、`IMAGE_FILE_MACHINE_I386 (0x014c)`。
   - 提取 Subsystem 类型（Console vs GUI）。

### 4.2 单元测试验证全量通过 (毫秒级纯离线 Mock + 逻辑覆盖)
1. **审计工具测试 (`scripts/proton/test_audit_proton.py`)**：
   ```bash
   python3 -m unittest scripts/proton/test_audit_proton.py -v
   ```
   ```
   test_synthetic_elf64_aarch64 ... ok
   test_synthetic_pe_arm64ec ... ok
   Ran 2 tests in 0.001s, OK
   ```
2. **探测脚本离线测试 (`scripts/proton/test_fetch_proton.py`)**：
   无需外网依赖，在 0.29 秒内执行完成：
   ```bash
   python3 -m unittest scripts/proton/test_fetch_proton.py -v
   ```
   ```
   test_eval_size_exits_0_with_disclaimer ... ok (验证历史元数据免责声明与 8 GiB 阈值)
   test_help_exits_0 ... ok
   test_no_args_exits_2 ... ok
   test_unknown_flag_exits_2 ... ok
   test_username_flag_disabled_exits_2 ... ok (验证隔离保护与禁用提示)
   test_mock_auth_blocked_exit_20_and_separate_logs ... ok (验证 check.XXXXXX 唯一目录生成、stage1 与 stage2 独立日志互不覆盖、退出码 20)
   test_mock_network_failure_exit_10 ... ok (验证网络错误返回 10 且保留日志)
   test_mock_timeout_exit_10 ... ok (验证 35s 超时返回 10)
   test_mock_unknown_output_exit_10 ... ok (验证非预期输出返回 10)
   test_live_check_only_returns_blocked_20 ... skipped (真实网络测试默认跳过，仅在 RUN_LIVE_STEAM_TEST=1 时可选运行)
   Ran 10 tests in 0.298s, OK (skipped=1)
   ```

---

## 5. 用户提供官方包与集成交接指引

为避免在实验沙箱内输入用户个人 Steam 密码，同时确保后续集成测试可验证官方原版包，建议按以下流程操作：

1. **阻断复验（供集成执行员 / Reviewer）**：
   ```bash
   ./scripts/proton/fetch_proton.sh --check-only
   ```
   预期退出码为 `20`，在 `logs/proton/check.XXXXXX/` 内生成独立的 stage1/stage2 证据，表明公开匿名获取受阻。集成任务应如实将 Wine/FEX 真实执行标记为 **`not-run (blocked by official package acquisition)`**。
2. **用户手动提供官方包流程**：
   - 用户在自身具备 App 4427310 授权的 Steam 客户端环境下下载安装 `Proton Experimental (ARM64)`；
   - 将安装目录的文件完整复制至本实验目录的 `artifacts/proton/raw/`；
   - 运行纯标准库审计工具生成依赖报告：
     ```bash
     python3 scripts/proton/audit_proton.py artifacts/proton/raw/ --json --out artifacts/proton/audit_results.json
     ```
   - 审计工具将自动输出 `wine64`、`wineserver` 的 PT_INTERP、DT_NEEDED、GLIBC 版本以及 DLL 的 ARM64EC 属性。
