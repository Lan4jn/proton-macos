# Proton macOS Lab 第二阶段独立复审报告：后端、ABI 与执行层证据

**报告日期**：2026-10-15  
**审查角色**：`lab-reviewer`（独立代码审查员）  
**关联任务**：`task-12`（独立复审本轮后端与真实执行证据）  
**关联返工**：`task-16`（修复后端进程身份清理与 wrapper 边界）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**独立测试归档目录**：`logs/continuation-review/`  

---

## 一、 执行摘要与总体验收裁定

### 1. 核心技术进展与事实确认
1. **公开原版 Proton 资产获取与置信度解耦**：
   - 通过公开再分发仓库（`The412Banner/winlator-contents`）成功获取包含 App 4427310 / Depot 4427311 / Build 25502785 的原版 Proton 压缩包（`proton-experimental-arm64-25502785.tar.zst`，398,113,534 字节，SHA-256：`d6c480a90d981801be0906a3f3418eb9bd9461c30e411140951cb0daf9d2a189`）。
   - **置信度诚实声明**：本包已经发布者元数据摘要与关键二进制 SHA-256 核验，但**未经 Valve 官方独立签名校验**（`independent_valve_signature_verified: false`）。代码与元数据中真实保留该说明，不冒充官方直签。
2. **底层执行突破与真实分层**：
   - **Wine 11 组件版本查询真实成功**：在 Debian glibc 2.41 环境下通过 `elfuse` 实测执行原包 `files/bin-arm64/wine --version`，标准输出输出 `wine-11.0`，退出码为 `0`（见 `logs/runtime/glibc241-wine.log`）。
   - **FEX 动态模块装载真实成功**：原包中的原生 `libarm64ecfex.so` 经 Linux Python 3.14.7 调用 `ctypes.CDLL(..., mode=2)` 在 HVF 下动态加载成功，输出 `FEX_NATIVE_MODULE_LOADED`，退出码为 `0`（见 `logs/runtime/run-njak1o36/result.json`）。**严格厘定：此结果仅证明动态库装载（`mmap`/`dlopen`）通过，绝不等于 FEX 已执行 x64 代码翻译**。
   - **完整 Linux 用户态隔离解压成功**：公开下载完整 `linuxfs-r9`（SHA-256：`d3240c1531531615b0dd06b6ad56e92db9015a8641eb18c3a613835ae45992e7`），解压至 lab 内专属 case-sensitive APFS 镜像 `fixtures/runtime/arch-case`，`tar` 退出码 0，错误日志为空。
3. **关键缺项与真实阻断状态（严禁虚报通过）**：
   - **Windows x64 PE 执行尚未成功**：实测调用 `wine C:\hello-x64.exe`（内部配置了 elfuse `--timeout 60` vCPU watchdog 周期，但现有日志未证明内部 watchdog 实际触发；确证的是外层 runner 70 秒 wall timeout 设定在运行 70.589 秒后实际触发），被外层 runner 发送 SIGTERM 终止，返回退出码 `-15`（信号 15 对应 SIGTERM，非 SIGKILL；见 `logs/runtime/run-1jxuv_2m/result.json`）。**当前阶段绝对不得声称 Windows 游戏或 x64 PE 程序能够运行**。
   - **ABI 兼容性真实保留 2 项失败**：原始 elfuse 上 5 项 ABI 测试呈现 **3 PASS, 2 FAIL**（跨进程 futex 唤醒失败，posix_spawn 错误未同步传递）。报告与测试真实保留失败，未被伪造为预期通过。

### 2. 审查裁定：【批准通过 (APPROVED)】
- **裁定理由**：针对此前暴露的超时目标忽略 SIGTERM 导致 Supervisor 提前死亡、进而丢失 SIGKILL 导致顽固进程逃逸泄漏的深层缺陷，执行员在 `task-16` 终审修复中精准落地了**基于 POSIX 规范的 Caught No-op Handler 模式**：
  1. Supervisor 在子进程全生命周期内注册捕获型 no-op SIGTERM handler，自身免于死在子进程之前，始终维持组 Leader 身份；
  2. POSIX 保证 `execve` 在子进程启动时自动将捕获型 handler 重置为 `SIG_DFL`，确保普通目标依然能正常响应优雅退出信号；
  3. 当超时触发时，Runner 发送的 `SIGKILL` 借由存活的 Leader 成功送达整个进程组，彻底杜绝孤儿进程泄漏；
  4. 审查员独立复验 Lead 同款黑盒场景（`logs/continuation-review/lead_blackbox_recheck_reviewer.log`），确证目标进程 PID 彻底消亡（`target_survives_cleanup: False`）；
  5. 后端自动化测试扩充至 27 项全量 PASS，Steam 测试 20 项全量 PASS，Proton 测试 11 项全量 PASS，ABI 失败项真实保留。全项符合严密工程标准。

---

## 二、 关键缺陷深度复查与返工闭环验证（task-16 终审核验）

### 1. 超时进程泄漏的闭环机制（Caught Handler 与进程生命周期）
- **涉及文件**：`scripts/backend/supervisor.py`、`scripts/backend/process.py`
- **机制与实现细节**：
  1. **Supervisor 捕获型 SIGTERM 处理**（`supervisor.py:45-49`）：
     ```python
     def sigterm_handler(signum, frame):
         nonlocal term_received
         term_received = True
     signal.signal(signal.SIGTERM, sigterm_handler)
     ```
     在启动子进程之前注册捕获型信号处理函数。
  2. **避免 SIG_IGN 跨 `execve` 继承陷阱**：
     POSIX 标准明确规定：被设为 `SIG_IGN` 的信号会被 `execve` 继承，导致子进程无法被正常信号终止；而捕获型 handler 在 `execve` 时**由操作系统内核自动重置为 `SIG_DFL`**。因此，目标子进程不会错误继承忽略行为，保证正常程序能正常响应 `SIGTERM`。
     - 自动化单测 `test_child_restores_default_sigterm_handler` 实测断言子进程启动时的 handler 精确为 `SIG_DFL`。
  3. **存活 Supervisor 保证组 SIGKILL 可达**：
     在超时或清理阶段，Supervisor 即使接收到组 `SIGTERM` 也不会提前死亡，而是安全进入等待并维持 PGID Leader。当 Runner 在 `process.py:158` 发送 `os.killpg(proc.pid, signal.SIGKILL)` 时，由于组 Leader 依然存活，`SIGKILL` 能顺利广播到所有忽略 SIGTERM 的顽固目标子进程，将其彻底消灭。随后 Runner 再通过 `proc.wait(timeout=1.0)` 将 Supervisor 干净收割。
  4. **独立黑盒双向实测证据**：
     - **顽固子进程测试**（`logs/continuation-review/lead_blackbox_recheck_reviewer.log`）：
       运行显式 `signal.signal(SIGTERM, SIG_IGN)` 且 sleep 25s 的目标进程。
       Runner 发生超时（`timeout=0.6`），返回 `exit: 124`, `target_exit: null`, `supervisor_exit: -9`（被 SIGKILL 终止）。
       实测检查目标 PID `80432`：`os.kill(target_pid, 0)` 抛出 `ProcessLookupError`，**确证目标进程已被 SIGKILL 彻底消灭，零进程泄漏（`alive == False`）**！
     - **普通子进程测试**（`logs/continuation-review/normal_target_term_reviewer.log`）：
       运行未忽略信号的普通 sleep 目标进程，实测验证其在超时阶段同样被干净清理，未发生信号失效或进程残留。

---

### 2. 状态传递、异常持久化与退出码严格解耦
- **真实退出码解耦**：
  - 超时状态下，Runner 返回标准的 POSIX 超时退出码 `exit: 124`；
  - `target_exit` 严格记录为 `null`（真实反映目标进程在被强制终止前未产生确定的自然退出码，严禁伪造猜测的 `-15`）；
  - `supervisor_exit` 真实记录 Supervisor 自身的终止状态（`-9` 代表由 Runner 的 SIGKILL 最终回收）。
- **清理失败防假绿保障**：
  - 在 `process.py:204-206` 中：若子任务正常返回 0 但在清理后代或回收过程中产生了 `cleanup_errors`，最终整体退出码被强制置为 `125`，从机制上杜绝“清理崩溃却报整体成功”的欺瞒。
  - 自动化单测 `test_cleanup_wait_timeout_persisted` 与 `test_supervisor_spawn_error_recorded` 验证了错误在 `result.json` 中的完整持久化。

---

### 3. Wrapper 双向调用边界闭环
- **涉及文件**：`scripts/backend/bundle.py:68-71`
- **重构机制**：
  ```bash
  #!/bin/sh
  if [ "$1" = "--" ]; then
    shift
  fi
  exec <command> -- "$@"
  ```
- **双向边界验证**：
  - **Steam Toolmanifest 路径（带 `--`）**：Steam 传入 `probe-wrapper.sh -- %verb% <game> ...`，wrapper 自动 `shift` 掉首个 `--`，再由 `exec command -- "$@"` 注入唯一的 `--`，防止多重 `--` 干扰游戏参数；
  - **用户/脚本直调路径（无 `--`）**：用户直接运行 `probe-wrapper.sh waitforexitandrun 游戏.exe --log-dir /game/logs`，wrapper 自动在探针命令与游戏参数之间插入 `--`，百分之百避免游戏自有的 `--log-dir` 被探针误吞导致崩溃。
  - 自动化测试 `test_wrapper_preserves_verb_and_arguments` 与 `test_wrapper_without_double_dash` 均 100% 通过。

---

## 三、 第一阶段：规格合规审查（Specification Review）

| 审查维度 | 规范约束 | 实测代码与证据溯源 | 判定 |
| :--- | :--- | :--- | :---: |
| **包来源真实性** | 明确包来源置信度；禁止冒充 Valve 官方独立签名。 | `artifacts/public-proton/bundle.json:8-9` 明确注明 `PUBLIC_REDISTRIBUTOR_CHECKSUM_VERIFIED_VALVE_ORIGIN_CLAIMED` 且 `independent_valve_signature_verified: false`。SHA-256 吻合。 | **PASS** |
| **计划与执行严格解耦** | 默认仅生成命令计划；禁止将计划伪称为执行成功。 | `scripts/backend/cli.py:28` 默认输出计划 JSON 并不执行；`scripts/backend/bundle.py:59` 显式标明 `'execution_performed': False` 并携带警告。 | **PASS** |
| **环境与路径强隔离** | 严禁读取宿主凭据；WINEPREFIX 与日志限定在 lab 内；拦截外部路径注入。 | `scripts/backend/process.py:42-51` 严格拦截 `DYLD_*` 与 `LD_*` 变量；限制 `HOME`, `TMPDIR`, `WINEPREFIX`, `XDG_*` 必须在 lab 内，违者抛出 `ValueError`。 | **PASS** |
| **真实执行状态诚实度** | 实际 Wine 版本及模块加载只认真实日志；x64 PE 未成功必须明示。 | 真实记录 Wine 版本（`wine-11.0`）及 `libarm64ecfex.so` 装载；实测记录 `wine C:\hello-x64.exe` 超时失败（Exit -15），明确声明游戏与 x64 尚未运行。 | **PASS** |
| **Steam 离线候选边界** | 仅生成候选与记录目标，严禁改动真实 Steam。 | `bundle.py:prepare_tool` 仅在 lab 内部生成 `artifacts/steam-prepared/continuation-probe`，标明 `'applied': false`；宿主 Steam 未作任何修改。 | **PASS** |
| **生命周期清理可靠性** | 必须消除 PID 复用误杀，且超时/异常时后代孤儿进程绝不泄漏。 | Caught Handler 模式确保 Supervisor 存活至 SIGKILL 送达，实测断言顽固子进程彻底消亡，无进程泄漏。 | **PASS** |
| **ABI 兼容性真实报告** | 真实保留失败项，不得掩盖为预期成功。 | `scripts/abi/test_abi.py` 明确输出 3 PASS, 2 FAIL，真实记录 futex 超时与 spawn 错误。 | **PASS** |

---

## 四、 第二阶段：独立测试执行与证据矩阵（Test Matrix）

审查员在隔离沙箱环境中（`HOME` 与 `TMPDIR` 均重定向至 `logs/continuation-review/` 内部目录）独立执行了全量测试套件与黑盒复验：

| 模块 / 测试套件 | 执行命令 | 用例数 / 范围 | 预期状态 | 实测状态 | 耗时 | 归档日志路径 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Backend 单元测试** | `python3 -m unittest discover -s tests/backend -v` | 27 项 (含 11 项安全与边界测试) | Exit 0 | **27/27 PASS** | 9.142s | `logs/continuation-review/backend_test_final_caught.log` |
| **顽固进程黑盒复核** | `python3 -c "import ... SIG_IGN ..."` | 1 项 (独立复验 Lead 超时泄漏场景) | Exit 124, 目标消亡 | **PASS (目标实测死亡)** | 0.718s | `logs/continuation-review/lead_blackbox_recheck_reviewer.log` |
| **普通目标信号复核** | `python3 -c "import ... SIG_DFL ..."` | 1 项 (验证普通目标响应默认 TERM) | Exit 124, 目标消亡 | **PASS (目标实测死亡)** | 0.723s | `logs/continuation-review/normal_target_term_reviewer.log` |
| **ABI 底层实测** | `python3 -m unittest scripts/abi/test_abi.py -v` | 5 项 | Exit 1 (含真实失败) | **3 PASS, 2 FAIL** | 1.769s | `logs/continuation-review/abi_test_final.log` |
| **Steam 离线适配器** | `python3 -m unittest discover -s tests/steam -v` | 20 项 | Exit 0 | **20/20 PASS** | 3.075s | `logs/continuation-review/steam_test_final.log` |
| **Proton 获取与审计** | `python3 -m unittest discover -s scripts/proton -p 'test_*.py' -v` | 12 项 | Exit 0 (1 skip) | **11 PASS, 1 SKIP** | 1.092s | `logs/continuation-review/proton_test_final.log` |
| **CLI Proton 默认计划** | `python3 -m scripts.backend.cli` | 1 项 | Exit 20 (BLOCKED) | **PASS (阻断且无执行)** | 0.04s | `logs/continuation-review/cli_default_plan.log` |
| **CLI Wine 默认计划** | `python3 -m scripts.backend.cli --engine wine` | 1 项 | Exit 0 (PLAN_READY) | **PASS (生成纯计划)** | 0.04s | `logs/continuation-review/cli_wine_plan.log` |

### 1. 关键 ABI 实测回显（真实保留失败证据）：
- `test_dynamic` (ELF aarch64 动态链接 ld.so + glibc)：**PASS** (`DYNAMIC_GLIBC_OK`, Exit 0)
- `test_shared` (clone 后 MAP_SHARED 内存共享与 wait4 回收)：**PASS** (`SHARED_OK`, Exit 0)
- `test_signal` (rt_sigaction + kill + rt_sigreturn 信号链)：**PASS** (`SIGNAL_OK`, Exit 0)
- `test_futex` (跨进程 futex WAIT/WAKE)：**FAIL**（`FUTEX_TIMEOUT_DESPITE_SHARED_WRITE`, Exit 5）
- `test_spawn` (posix_spawn 不存在文件)：**FAIL**（`SPAWN_RETURN=0 CHILD_EXIT=127`, Exit 9）

### 2. 真实 Wine 与 Proton 运行记录：
- `logs/runtime/glibc241-wine.log`：`wine-11.0`（Exit 0）。
- `logs/runtime/run-njak1o36/result.json`：`FEX_NATIVE_MODULE_LOADED`（Exit 0，仅动态装载）。
- `logs/runtime/run-1jxuv_2m/result.json`：`wine C:\hello-x64.exe`（Exit -15，内部配置 watchdog 60s，外层 runner 70s wall timeout 触发后被 SIGTERM 终止）。

---

## 五、 审查结论与交付签字

1. **测试统计汇总**：
   - 后端自动化测试套件：**27 / 27 PASS**
   - Steam 测试套件：**20 / 20 PASS**
   - Proton 获取/审计测试套件：**11 PASS, 1 SKIP**
   - 独立黑盒超时清理复核用例：**2 / 2 PASS**（确证目标进程真实死亡）
   - ABI 底层实测：**3 PASS, 2 FAIL**（真实保留兼容性失败，无假绿掩盖）
   - 累计独立执行用例数：**66 项**
2. **闭环状态**：
   - 初审与复审指出的进程清理超时泄漏缺陷已通过 POSIX Caught Handler 模式彻底修复并闭环；
   - Wrapper 脚本双边界参数防护已通过端到端测试闭环；
   - 真实执行层边界与包来源置信度表述已精确校准。
3. **最终审查判定**：**批准通过 (APPROVED)**
   - `task-12` 独立复审终审完成签字。
