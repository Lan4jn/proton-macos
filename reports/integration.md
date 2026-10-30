# Proton 官方原版 ARM64 执行层集成验证与阻断报告

**任务编号**: task-6  
**执行角色**: proton-integration-worker  
**工作区根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`  
**报告时间**: 2026-10-15  
**状态**: **BLOCKED (技术目标尚未达成：官方二进制包获取遭遇上游鉴权阻断)**  

---

## 一、 执行摘要与结论

本任务旨在基于已验证的 `elfuse` 底层基线与官方原版 Proton 包审计，在隔离的 `HOME`/`TMPDIR` 环境中，对原版 ARM64 Proton 的核心执行层（`wineserver`、`wine64`、FEX-Emu 及 Windows x64 PE 控制台程序）进行端到端集成验证。

### 核心结论
1. **技术目标状态**：**尚未达成（BLOCKED / NOT_RUN）**。
   - 阻断根因：Valve 官方原版 ARM64 Proton 预编译二进制包（Steam App `4427310` / Depot `4427311`）属于 `ownersonly` 资产，完全阻断匿名下载。在严格隔离、禁止读取宿主凭据的红线下，实验室内未取得官方二进制包。
   - 并非技术兼容失败：当前未执行 Wine/wineserver 及 FEX 测试，状态严格标记为 `NOT_RUN`，绝不可混淆为底层技术兼容性失败。
2. **底层基线状态**：**VERIFIED（已验证）**。
   - `elfuse`（基于 Hypervisor.framework 的 Mach-O arm64 二进制）及 entitlement 已就绪，且独立执行静态 Linux aarch64 ELF `fixtures/elfuse/hello` 成功输出 `hello`，退出码为 `0`。
3. **红线遵守情况**：
   - 零凭据交互：未读取、缓存或尝试任何 Steam 账号凭据或 `~/.steam`。
   - 零假包/假路径：未构造凭空的假 Wine 目录，未引入任何第三方构建（如 GE-Proton、CachyOS 等）冒充原版。
   - 严格沙箱隔离：所有 SteamCMD 探针均运行在独立的局部沙箱 `fixtures/integration/steamcmd_home` 与 `fixtures/integration/tmp` 下，限额超时 120 秒，进程清理限定自身。

---

## 二、 基础运行环境与 ELF 基线复验

在进入集成层检查前，首先核查并复验底层 ELF 执行容器。

### 1. 资产与二进制属性
- **二进制文件**: `sources/elfuse/build/elfuse`
- **文件格式**: Mach-O 64-bit executable arm64
- **Entitlements**: `com.apple.security.hypervisor = true`
- **测试负载**: `fixtures/elfuse/hello` (ELF 64-bit LSB executable, ARM aarch64, version 1 (SYSV), statically linked)

### 2. 复现命令与真实输出
```bash
file sources/elfuse/build/elfuse fixtures/elfuse/hello
sources/elfuse/build/elfuse --timeout 5 fixtures/elfuse/hello
```

**执行回显**:
```text
sources/elfuse/build/elfuse: Mach-O 64-bit executable arm64
fixtures/elfuse/hello:       ELF 64-bit LSB executable, ARM aarch64, version 1 (SYSV), statically linked, not stripped
hello
[Process exit code: 0]
```

**基线结论**: 原生 macOS ARM64 Hypervisor 驱动的 Linux aarch64 ELF 加载与执行基础设施真实有效。

---

## 三、 上游 Proton 包获取阻断复现与语义分析

### 1. 上游资产定义与元数据检查
根据 Valve 官方生态调查与 `artifacts/proton/identity.json` 事实记录：
- **上游源码**: `https://github.com/ValveSoftware/Proton` (tag: `proton-11.0-2e`)。官方 GitHub 仅托管构建源码，未提供任何 GitHub Releases 二进制资产包。
- **预编译发布通道**: Steam 官方内部 Depot。
- **App ID**: `4427310` (Proton Experimental (ARM64), Tool)
- **Depot ID**: `4427311` (Build ID: 25406135)
- **预估解压体积**: ~1.94 GiB (2,083,000,000 字节，符合 < 8 GiB 实验限制)
- **预估下载体积**: ~474.41 MiB (497,455,000 字节)

### 2. 独立隔离沙箱复现命令
为避免干扰已有日志，本任务在完全隔离的环境下启动 SteamCMD 探针：
```bash
export HOME="/Users/mewcapoo/Projects/proton-macos-lab/fixtures/integration/steamcmd_home"
export TMPDIR="/Users/mewcapoo/Projects/proton-macos-lab/fixtures/integration/tmp"
mkdir -p "$HOME/Library/Application Support" "$TMPDIR"

/Users/mewcapoo/Projects/proton-macos-lab/scripts/proton/tools/steamcmd/steamcmd.sh \
  +login anonymous \
  +app_info_print 4427310 \
  +app_license_request 4427310 \
  +app_update 4427310 validate \
  +quit
```

### 3. 原始日志输出与语义特征
日志完整保存于 `logs/integration/steamcmd_anonymous_verify.log`：
```text
Steam Console Client (c) Valve Corporation - version 1791918946
Loading Steam API...OK

Connecting anonymously to Steam Public...OK
Waiting for client config...OK
Waiting for user info...OK
AppID : 4427310, change number : 39839235/39839235
"4427310"
{
	"common"
	{
		"name"		"Proton Experimental (ARM64)"
		"section_type"		"ownersonly"
		"type"		"Tool"
		"ReleaseState"		"released"
	}
}
Not for anonymous users.
ERROR! Failed to install app '4427310' (No subscription)
Unloading Steam API...OK
[process exit: 8]
```

### 4. 语义阻断判定
- `section_type: "ownersonly"`：Valve 将此 AppID 限制为仅限已授权账户访问。
- `Not for anonymous users` & `ERROR! Failed to install app '4427310' (No subscription)`：匿名 Token 无法通过 Steam 分发服务器的许可证校验。
- 退出码 `8`：SteamCMD 内部明确报告下载失败退出。
- 结论：**获取阻断为客观上游鉴权机制所致，在无授权用户交互下无法自动突破。**

---

## 四、 集成检查工具与测试实现

为避免编写泛泛文档，本任务使用 Python 标准库实现了确定性前置检查工具及 TDD 测试套件。

### 1. 工具清单
| 文件路径 | 职责说明 | 依赖 |
| :--- | :--- | :--- |
| `scripts/integration/check_prerequisites.py` | 读取 `identity.json`，验证 `elfuse`，确定 Wine/FEX 状态并生成结构化诊断 | 纯标准库 (`json`, `subprocess`, `pathlib`) |
| `scripts/integration/verify_steamcmd_block.py` | 隔离沙箱探针与 SteamCMD 语义分析器 | 纯标准库 (`re`, `subprocess`, `argparse`) |
| `scripts/integration/test_prerequisites.py` | 前置检查器单元测试（验证阻断、缺少包路径等确定性状态） | `unittest` |
| `scripts/integration/test_steamcmd_verifier.py` | 探针语义解析单元测试（验证 ownersonly、No subscription 等提取） | `unittest` |

### 2. 自动化测试结果
在工作区根目录执行单元测试（含退出码、动态结论与隔离环境覆盖）：
```bash
python3 -m unittest discover -s scripts/integration -p "test_*.py"
```
**回显**:
```text
............
----------------------------------------------------------------------
Ran 12 tests in 0.151s

OK
```

### 3. 前置检查器运行实测与落盘日志
执行检查器（按规范：包获取阻断时退出码为 20，底层 elfuse 失败时退出码为 1，仅前置就绪时退出码为 0）：
```bash
python3 scripts/integration/check_prerequisites.py > logs/integration/integration_check.log 2>&1 || echo "Exit code: $?"
python3 scripts/integration/check_prerequisites.py --json > logs/integration/integration_check.json 2>&1 || true
```

**控制台与日志回显 (`logs/integration/integration_check.log`)**:
```text
==========================================================
Proton Integration Prerequisite Check
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

**结构化 JSON 证据 (`logs/integration/integration_check.json`)**:
```json
{
  "elfuse_status": "VERIFIED",
  "package_status": "BLOCKED",
  "blocker_reason": "Official package missing: Steam depot App 4427310 / Depot 4427311 requires authenticated subscription (ownersonly).",
  "wine_execution_status": "NOT_RUN",
  "fex_execution_status": "NOT_RUN",
  "upstream_app_id": 4427310,
  "upstream_depot_id": 4427311,
  "elfuse_detail": "hello",
  "conclusion": "Conclusion: Execution blocked at official package acquisition (Exit 20).\n            No third-party packages substituted.\n            ELF execution capability verified; Wine / FEX tests NOT RUN."
}
```

---

## 五、 原版身份 Manifest 缺失与测试边界隔离

为保证学术与工程严谨性，本报告明确划定当前阶段的边界：

1. **原版二进制包审计 Manifest**:
   - `artifacts/proton/identity.json` 中 `sha256: null`，`local_package_path: null`。
   - 由于官方二进制文件未落地，无法计算真实 SHA-256 哈希，亦无法静态提取其内部 ELF/PE 符号（如 Wine 的 `ntdll.so`、`wineserver`，或 FEX 的 `libFEXCore.so`）。
2. **严禁混淆概念**:
   - **已验证**: Mach-O ARM64 elfuse 在 macOS HVF 下直接运行静态 Linux ARM64 ELF 程序的系统调用处理能力。
   - **未执行 (NOT_RUN)**: Wine 64-bit 原生 ARM64 进程启动、`wineserver` 进程间通信、FEX 对 Windows x64 PE 的二进制翻译与执行。
   - **结论界定**: 没有任何证据表明 Wine 或 FEX 在技术上与当前 elfuse 存在不兼容，所有未通过项均因前置包缺失被阻断在启动入口前。

---

## 六、 用户提供官方完整包后的续接指南

本实验环境严守无密码、无私有凭据交互原则，绝不要求用户在终端输入 Steam 账号密码，亦不调用交互式登录工具。

若用户希望继续推进官方原版 ARM64 Proton 的执行层验证，请按照以下离线方式导入：

### 步骤 1：用户在外部官方 Steam 客户端导出
1. 在用户具备访问授权的 Steam 客户端中，下载 **Proton Experimental (ARM64)**（App ID `4427310`，Depot ID `4427311`）。
2. 将 Steam 下载的完整 depot 目录打包或复制。

### 步骤 2：置入实验工件目录
将解压后的完整原版包放入以下指定目录：
```bash
/Users/mewcapoo/Projects/proton-macos-lab/artifacts/proton/raw/
```
目录中应包含官方提供的 `files/`、`bin/`（含 `wineserver`、`wine64`）、`lib/` 以及 FEX 运行库组件。

### 步骤 3：离线静态审计
运行官方包审计工具计算 SHA-256 并分析符号拓扑：
```bash
python3 scripts/proton/audit_proton.py artifacts/proton/raw/ --json --out artifacts/proton/audit_results.json
```

### 步骤 4：自动化集成前置复核
运行集成检查工具确认状态变迁为 `READY`：
```bash
python3 scripts/integration/check_prerequisites.py
```

### 步骤 5：启动 Wine/FEX 端到端集成验证
前置通过后，在独立实验前缀（`fixtures/integration/wine_prefix`）中按以下顺序验证：
1. 启动 `elfuse` 挂载或映射 Proton 原生 ARM64 `wineserver`。
2. 运行原版 `wine64` 探测控制台输出。
3. 挂载 FEX-Emu 解释器执行极简 Windows x64 控制台测试用例（如 PE32+ `hello_win64.exe`），验证指令翻译、系统调用转接与退出码。

---

## 七、 交付物文件清单与自检

### 1. 修改与产出文件（严格限制在写入作用域内）
- `scripts/integration/check_prerequisites.py` (前置条件检查器)
- `scripts/integration/verify_steamcmd_block.py` (独立 SteamCMD 语义解析探针)
- `scripts/integration/test_prerequisites.py` (前置条件单元测试)
- `scripts/integration/test_steamcmd_verifier.py` (探针语义解析单元测试)
- `logs/integration/steamcmd_anonymous_verify.log` (独立复验原始日志)
- `logs/integration/integration_check.log` (前置检查文本报告)
- `logs/integration/integration_check.json` (前置检查结构化 JSON)
- `reports/integration.md` (本综合集成验证报告)

### 2. 沙箱临时资源清理
- 独立 SteamCMD 运行产生的文件均在 `fixtures/integration/steamcmd_home` 与 `fixtures/integration/tmp` 内部，无全局系统或宿主 Steam 污染。
- 经进程检查，无任何遗留后台 steamcmd 进程。
