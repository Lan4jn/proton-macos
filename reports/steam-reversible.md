# Steam 接入适配器可逆性与路径封闭性测试强化报告（Task-80）

**执行员**：evidence-reviewer-r36  
**任务要求**：
- 严格保持真实 Steam、宿主系统路径与全局包不受任何修改；
- 新增独立测试文件位于 `scripts/backend/tests/`，不篡改既有测试；
- 运行产物落盘至 `logs/steam-reversible/`，总结产物落盘至 `reports/steam-reversible.md`；
- 覆盖：(1) 字节级可逆性；(2) 路径封闭性；(3) 幂等重复执行；(4) 干跑与执行门禁；(5) 未覆盖能力边界。

---

## 一、 测试设计与制品清单 (Test Suite & Artifacts)

| 制品文件路径 | SHA256 / 状态 | 说明 |
| :--- | :--- | :--- |
| `scripts/backend/tests/test_steam_reversible_closure.py` | `c2ee89c3b349ab2aaad26440cd739dd7db183b412a7c611e6da3d4d9726ae35f` | 新增的 Steam 适配器可逆性与封闭性单元测试套件 |
| `logs/steam-reversible/test_output.log` | `69926f63f35ee3db776dbda3bdfb3cb86754b2d354c4146a7ce32f8641ea5d7f` | 新测试套件 4 项用例全量控制台输出（4/4 OK） |
| `logs/steam-reversible/regression_output.log` | `46ca826e792c3a502a5cf38b1bc678a6ff3e7be7d4766ecad6da3e58941cfbdf` | 既有后端回归测试全量输出（63/63 OK，0 回归） |
| `logs/steam-reversible/receipt.json` | `e5a593368ea5b9a781b0a8274f8c47f7d9834ea576ee3b7e4ef47e62a4d3539f` | 结构化审计收据与环境快照 |

---

## 二、 五大核心安全保证实测结论 (Verification Results)

### 1. 严格可逆性 (Byte-Identical Reversibility)
- **用例**：`test_reversibility_byte_identical_rollback`
- **验证机制**：
  1. 在模拟的目标目录 `compatibilitytools.d` 中注入既有工具文件、配置 `.vdf` 及二进制测试夹具；
  2. 提取基准目录递归指纹（包含所有相对路径集合、文件 SHA256 校验和、POSIX 权限位八进制值、文件字节长度）；
  3. 执行适配器候选准备并在目标目录下模拟受控部署；
  4. 触发回滚操作（严格仅清理已安装的工具目录，不触碰基准文件）；
  5. 再次提取回滚后目录递归指纹，与基准指纹逐字段比对。
- **实测结果**：`initial_fingerprint == post_rollback_fingerprint`，**实现 100% 字节级严格回滚恢复**。

### 2. 绝对路径封闭性 (Strict Path Enclosure)
- **用例**：`test_path_enclosure_rejects_real_steam_and_system_paths`
- **验证机制**：
  构造全部典型的真实 Steam、宿主系统及用户目录输入：
  - `~/Library/Application Support/Steam`
  - `~/Library/Application Support/Steam/compatibilitytools.d`
  - `/Applications/Steam.app`
  - `/Applications`
  - `/usr/local/bin`
  - `/etc`
  - `/tmp`
  - 用户主目录 `~/`
- **入口覆盖**：
  - `bundle.local(path)`：基础路径封闭解析器；
  - `bundle.prepare_tool(out, target)`：探测器准备入口；
  - `steam_handoff.prepare_runtime_tool(out, target, sysroot, prefix, elfuse, logs)`：完整运行时候选准备入口；
  - `bundle.validate_absock_base(base)`：Unix 域套接字基目录校验器；
  - `process.run_isolated(argv, log_root)`：子进程隔离执行器。
- **实测结果**：**全部 5 个入口对上述所有非 lab 路径 100% 拒绝并抛出 `ValueError`**。真实系统路径只读探测前后存在性与目录状态完全未变，未发生任何非 lab 文件写入或泄漏。

### 3. 幂等与重复执行安全 (Idempotency & Repeatability)
- **用例**：`test_idempotent_preparation`
- **验证机制**：
  在同一目标输出路径下连续进行 3 次重复准备（初次生成、二次覆盖、三次覆盖），比对生成的全部配置文件（`config.json`）、启动包装脚本（`proton-wrapper.sh`）、VDF 清单（`toolmanifest.vdf`、`compatibilitytool.vdf`）与安装计划（`install-plan.json`）。
- **实测结果**：3 次运行产物指纹完全一致（`fp1 == fp2 == fp3`），**证明重复调用无状态累积或副作用污染**。

### 4. 干跑能力与执行门禁 (Dry-Run & Execution Gating)
- **用例**：`test_dry_run_capabilities_and_execution_gating`
- **验证机制**：
  - 默认参数生成候选时，`execute_runtime` 强制为 `False`；
  - 执行生成的 `proton-wrapper.sh run C:\game.exe`：
    - 返回码为 `0`（正常退出）；
    - 标准输出输出标准 JSON 格式的执行计划（`PLAN_READY`）；
    - 明确包含标志位 `"execution_performed": false`；
    - 未触发任何 Linux Python 或 elfuse/Wine 子进程执行（纯干跑 / 计划校验）。
  - 传入非法/未知的 Steam verb（如 `invalid_verb`）：
    - 包装脚本直接拦截，标准错误输出 `Error: Unknown or unsupported Steam verb`，退出码非零，杜绝任意参数穿透。

### 5. 全量回归测试状态 (Regression Status)
- 在加入新测试后，执行现有 `tests/backend` 下全部 63 项测试：
  - **运行结果**：`Ran 63 tests in 11.184s - OK`；
  - **回归指标**：0 失败，0 错误，证明新测试套件与既有适配器逻辑完全兼容。

---

## 三、 当前环境不可覆盖能力与限制说明 (Uncovered Capabilities & Gaps)

根据当前 macOS 实验舱与用户硬性边界限制，以下能力在当前离线纯本地环境下**明确不具备可测条件，如实记录为未覆盖缺口**：

1. **真实 Steam 客户端 UI 动态装载与用户点击启动**：
   - *原因*：用户全局规范禁止启动、安装或修改真实 Steam 客户端；macOS 上 Steam 客户端对兼容工具的探测需要将其注册进 `compatibilitytools.d` 并在真实客户端内登录特定拥有 Windows 版游戏许可证的商业账号，该链路在离线纯只读环境下不可覆盖。
2. **Steamworks 在线通信与官方 Ticket 校验**：
   - *原因*：当前运行使用独立模拟环境与无 Steam 标志（`STEAM_COMPAT_CLIENT_INSTALL_PATH` 指向存根），没有宿主 Steam 守护进程提供 IPC 命名管道服务，无法验证 `SteamAPI_Init()` 票据下发。
3. **真实 GPU 物理交换链呈现**：
   - *原因*：目前图形测试仅到软件 Vulkan（Lavapipe），尚未接入宿主 Metal/MoltenVK 硬件图形呈现。
