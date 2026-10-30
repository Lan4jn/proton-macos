# Proton macOS Lab 最终独立验收与审查报告

**报告日期**：2026-10-15  
**验收角色**：`final-lab-reviewer`（独立验收审查员）  
**关联任务**：`task-7`（独立验收执行层证据与 Steam 探测器）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**独立测试证据归档目录**：`logs/review/final/run_20261015_101011/`  

---

## 一、 执行摘要与总体验收结论

1. **核心技术目标状态**：**尚未达成（OBJECTIVE NOT ACHIEVED: BLOCKED / NOT_RUN）**。
   - **真实原版包未取得**：Valve 官方原版 ARM64 Proton（Steam App `4427310` / Depot `4427311`）为 `ownersonly` 资产。在严格遵守实验室安全红线（禁止读取宿主 Steam 凭据、禁止网络交互凭据泄露）的前提下，匿名 SteamCMD 请求返回明确阻断：`Not for anonymous users. ERROR! Failed to install app '4427310' (No subscription)`。
   - **阻断属性明确**：此阻断纯属**上游分发通道鉴权阻断**，**绝非底层 ABI 或 Linux-on-Darwin 兼容性失败**。
   - **执行层状态诚实**：由于官方二进制文件未落地，`wineserver`、`wine64` 及 FEX 模拟执行状态严格标记为 **`NOT_RUN`**，绝不以空跑或第三方构建冒充成功。
   - **真实依赖审计未执行**：`scripts/proton/audit_proton.py` 目前仅通过了合成假 ELF/PE 的单元测试，未对实际 Valve 原版二进制执行真实审计。
   - **前置检查器定位澄清**：`scripts/integration/check_prerequisites.py` 是**只读诊断工具**，而非完整实现的包导入器或自动化运行时；用户仅复制未经验证的 raw 目录**绝不等于**自动变更为 `READY`。
2. **底层基础设施状态**：**已验证（VERIFIED）**。
   - `elfuse`（基于 Hypervisor.framework 的 Mach-O arm64）上游源码干净（HEAD `8612033dab8dc60728f604a4ea0441895fc16d39`），局部 `tools/elfuse/bin/objcopy` 经字节级校验一致。
   - 7 项底层 ELF 基线测试（包含纯汇编、独立 C ELF、mmap+JIT、clone/fork、glibc 动态链接器自执行以及负例错误文件拦截）100% 通过。
3. **Steam 离线适配器状态**：**已验证（VERIFIED）**。
   - `scripts/steam/probe.py` 纯离线无副作用，不执行目标游戏，不改动宿主 Steam 配置；严格脱敏敏感参数、实施 19 项安全环境变量白名单、0600 独占防覆盖写日志。
   - 包含候选 VDF 生成器在内的 20 项单元测试全量通过，前期审查员 9 项深度边界测试全量通过。
4. **验收裁定**：**批准通过验收（APPROVED）**。全流程符合规范，边界清晰，未发生假绿欺瞒与环境越界。

---

## 二、 第一阶段：规格合规审查（Specification Review）

| 审查维度 | 规范约束与红线 | 审查发现与证据溯源 | 判定 |
| :--- | :--- | :--- | :---: |
| **环境严格隔离** | 严禁读取宿主 Steam 配置与私有凭据；所有执行 HOME/TMPDIR 重定向在实验目录内；禁止全局安装与 Git commit/push。 | 所有脚本与测试执行严格限制在 lab 内部（如 `fixtures/integration/steamcmd_home`, `logs/review/final/run_20261015_101011/fake_home` 等）。宿主 `~/Library/Application Support/Steam` 与 `~/.steam` 零读写；`fetch_proton.sh --username` 显式以退出码 2 拒绝。工作区无未授权 commit/push。 | **PASS** |
| **原版包身份与获取阻断** | 固定 Valve 官方原版身份；先走公开匿名途径；获取受阻必须真实报告，禁止拿第三方包替代。 | `artifacts/proton/identity.json` 固定 App `4427310` / Depot `4427311`，`local_package_path` 与 `sha256` 真实置为 `null`。SteamCMD 匿名实测日志（`logs/proton/steamcmd_anonymous_verify.log` 与 `logs/integration/steamcmd_anonymous_verify.log`）均记录 `No subscription`（Exit 20）。无 GE/CachyOS 冒充。 | **PASS** |
| **Wine / FEX 执行层边界** | 前置缺失时，Wine 与 FEX 必须明确标记为阻断/未运行，禁止将前置通过等同于执行层成功。 | `scripts/integration/check_prerequisites.py` 严格将 `wine_execution_status` 与 `fex_execution_status` 输出为 `NOT_RUN`。结论明确注明 `Execution blocked at official package acquisition`。 | **PASS** |
| **Steam 客户端边界** | 仅离线研究，严禁安装、调用或改动真实 Steam 客户端；不得将适配器调用等同于游戏运行或 Steamworks DRM 通过。 | 适配器 `scripts/steam/probe.py` 仅解析参数并记录脱敏 JSON，无 `subprocess.Popen` / `exec` 行为；候选 VDF 模版 `scripts/steam/candidate/` 严格遵循 `-- %verb%` 契约，仅作为离线交付物，未拷贝至真实 Steam 目录。 | **PASS** |
| **失败不假绿** | 异常情况必须返回明确非零退出码；断言必须校验真实退出码与模式输出，避免假成功。 | `check_prerequisites.py` 在包缺失或未校验时均严格退出码 20；elfuse 测试套件 `run_all_baseline.sh` 校验逐项实际退出码与输出正则；`test_fake_binary_rejection.sh` 注入模拟伪二进制确认 runner 能准确失败（Exit 1）。 | **PASS** |
| **诊断工具定位** | 诊断工具不得伪装为完整导入器；空目录或未校验目录不得报告为 READY。 | `check_prerequisites.py:45-50` 明确：若指定目录存在但无官方 SHA-256 或校验凭据，判定为 `LOCAL_PATH_PRESENT_UNVERIFIED` 并以退出码 20 阻断，不承诺自动变更为 `READY`。 | **PASS** |

---

## 三、 第二阶段：代码质量与工程审查（Code Quality Review）

1. **退出状态码标准**：
   - `scripts/integration/check_prerequisites.py`：`0`（前置就绪）、`1`（elfuse 执行失败）、`2`（CLI 参数/元数据缺失）、`20`（官方包获取受阻或未校验）。实测退出码均为预期值。
   - `scripts/proton/fetch_proton.sh`：`0`（容量评估通过）、`2`（参数非法/禁用凭据输入）、`10`（网络错误/超时）、`20`（官方包鉴权阻断）。
   - `scripts/steam/probe.py`：参数缺失或路径不存在时返回 `1`，正常记录返回 `0`。
2. **超时机制与资源保护**：
   - `scripts/proton/tools/run_timeout.py` 为 SteamCMD 操作设定 35 秒上限，超时自动清理子进程并返回 `124`。
   - `scripts/elfuse/run_all_baseline.sh` 每项 fixture 设定 `--timeout 5`。
   - `scripts/integration/check_prerequisites.py` 设定 `timeout=10`。
3. **日志防覆盖与隔离**：
   - `scripts/elfuse/run_all_baseline.sh` 每次执行通过 `mktemp -d logs/elfuse/run.XXXXXX` 创建唯一目录，完整未截断的 fixture 输出（`test_N.stdout`）全部保留不删，`--log` 目标存在时拒绝覆盖。
   - `scripts/proton/fetch_proton.sh` 每次检查生成唯一的 `logs/proton/check.XXXXXX/`，分别独立存储 `stage1_app_info.log` 与 `stage2_app_update.log`，彻底移除 `rm -f`。
   - `scripts/steam/probe.py` 文件名包含高精度时间戳、PID 与 UUID8，使用 `os.O_CREAT | os.O_EXCL` 原子创建，文件权限严格限制为 `0600`。
4. **敏感字段与环境过滤**：
   - `probe.py` 具备 URL userinfo（`user:pass@`）、Query/Fragment 凭据特征字典、`-H` / `Authorization` Header 及 `--auth` 连字符敏感值脱敏能力；仅捕获白名单内 19 项安全 Steam 环境变量，其余全部丢弃。

---

## 四、 独立实测证据矩阵（Test Execution Matrix）

审查员在隔离环境中（`HOME` 与 `TMPDIR` 重定向至专属沙箱目录）独立执行全部 4 大测试套件，原始终端回显与退出码完整归档于 `logs/review/final/run_20261015_101011/`：

| 测试套件 | 执行命令 | 用例数 / 范围 | 预期状态 | 实测状态 | 耗时 | 归档日志文件 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Suite 1: Steam 适配器** | `python3 -m unittest discover -s tests/steam -v` | 20 项 (probe 15 + candidate 5) | Exit 0 | **PASS (20/20)** | 1.372s | `logs/review/final/run_20261015_101011/1_steam_unittest.log` |
| **Suite 2: elfuse 基线套件** | `bash scripts/elfuse/run_all_baseline.sh` | 7 项 (正向 5 + 负向 2) | Exit 0 | **PASS (7/7)** | 0.218s | `logs/review/final/run_20261015_101011/2_elfuse_baseline.log` |
| **Suite 2 补充: 伪程序注入** | `bash scripts/elfuse/test_fake_binary_rejection.sh` | 1 项 (注入 fake binary 验证捕获) | Exit 0 (Runner 1) | **PASS (捕获成功)** | 0.052s | `logs/review/final/run_20261015_101011/2_elfuse_fake_rejection.log` |
| **Suite 3: Proton 单元测试** | `python3 -m unittest discover -s scripts/proton -p 'test_*.py' -v` | 12 项 (audit 2 + fetch mock 10) | Exit 0 (1 skip) | **PASS (11 通过, 1 跳过)** | 0.330s | `logs/review/final/run_20261015_101011/3_proton_unittest.log` |
| **Suite 4: Integration 单元测试** | `python3 -m unittest discover -s scripts/integration -p 'test_*.py' -v` | 12 项 (prerequisites 9 + verifier 3) | Exit 0 | **PASS (12/12)** | 0.097s | `logs/review/final/run_20261015_101011/4_integration_unittest.log` |
| **Suite 4: 前置检查器 CLI (文本)** | `python3 scripts/integration/check_prerequisites.py` | 1 项 (真实前置条件文本诊断) | Exit 20 | **PASS (明确报告 BLOCKED)** | 0.041s | `logs/review/final/run_20261015_101011/4_check_prerequisites_text.log` |
| **Suite 4: 前置检查器 CLI (JSON)** | `python3 scripts/integration/check_prerequisites.py --json` | 1 项 (真实前置条件结构化 JSON) | Exit 20 | **PASS (结构化 JSON 吻合)** | 0.040s | `logs/review/final/run_20261015_101011/4_check_prerequisites_json.log` |

**统计汇总**：
- 独立执行自动化单测及基线用例累计 **52 项**（51 项成功通过，1 项按设计跳过外部实时 Steam 网络测试 `RUN_LIVE_STEAM_TEST`）。
- 独立执行诊断 CLI 命令 2 次，均准确输出并返回退出码 **20**。
- 所有测试用例失败数 0，错误数 0，假绿数 0。

---

## 五、 后续交接与用户操作指引

由于实验室严格禁止私有凭据交互，若用户需在后续阶段推进官方原版 ARM64 Proton 的实际动态执行，需按以下合规步骤离线提供数据：

1. **外部官方导出**：
   - 用户在自身具备 App `4427310` 授权的真实 Steam 客户端下载安装 `Proton Experimental (ARM64)`；
   - 将官方安装目录拷贝导出。
2. **置入实验目录**：
   - 放入 `/Users/mewcapoo/Projects/proton-macos-lab/artifacts/proton/raw/`；
3. **真实二进制静态审计**：
   - 运行 `python3 scripts/proton/audit_proton.py artifacts/proton/raw/ --json --out artifacts/proton/audit_results.json`，提取真实 SHA-256 及 ELF/PE 动态符号依赖拓扑；
4. **集成前置诊断复核**：
   - 运行 `python3 scripts/integration/check_prerequisites.py`，确认其前置状态变更为 `READY`（Exit 0）；
5. **执行层实测推进**：
   - 在独立前缀下依序启动 `elfuse` + `wineserver` + `wine64` 及 FEX x64 测试。

---

## 六、 最终签字

- **审查员**：`final-lab-reviewer`
- **审查结论**：**通过最终验收（APPROVED）**
- **当前技术目标**：**诚实记录未达成（上游获取鉴权阻断，Wine/FEX 状态确认为 NOT_RUN）**
- **关联任务状态**：`task-7` 满足完成条件。
