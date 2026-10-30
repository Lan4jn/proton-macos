# Proton macOS Lab 后端架构与进程生命周期修复报告

**报告日期**：2026-10-15  
**执行角色**：`steam-probe-worker`（后端返工与生命周期实现员）  
**关联任务**：`task-11`、`task-16`  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**测试日志归档**：`logs/backend-repair/red.log`、`logs/backend-repair/green.log`  

---

## 一、 缺陷根因深度分析与平台能力实测

### 1. 原 `scripts/backend/process.py` 竞态缺陷
- **缺陷表现**：原实现中 `proc.wait(timeout)` 返回并收割（reap）子进程后，在 `finally` 块中无条件调用 `os.killpg(proc.pid, signal.SIGKILL)`。
- **机制危害**：
  1. `waitpid` 成功返回后，主进程 PID 已被内核释放回操作系统的可用 PID 池；
  2. 若操作系统在微秒级时间内将该 PID 重新分配给其他系统用户的进程，`killpg` 将抛出 `PermissionError: [Errno 1] Operation not permitted`（在 Wine 超时日志中已真实观测到 `cleanup_errors: ["[Errno 1] Operation not permitted"]`）；
  3. 若操作系统将该 PID 重新分配给当前用户（`mewcapoo`）自己的其他正在运行的无辜进程，盲目 `killpg` 将直接误杀同用户的其他任务；
  4. 原实现简单在第 55 行将 `PermissionError` 追加到 `cleanup_errors` 并掩盖，未从架构上消除 PID 复用危害；
  5. 若简单删除 `finally` 中的 `killpg`，则当主进程正常退出但留下长活孤儿进程（如后台守护进程或未退出的子线程）时，后代进程将彻底泄漏。

### 2. 平台能力实测与技术选型
针对 Lead 建议的 `waitid WNOWAIT` 与 `受控 supervisor` 方案，在 macOS Darwin (macOS 27.0.1, Python 3.9.6) 上进行了实测：
- `hasattr(os, 'waitid')` 为 `False`（macOS Python 3.9 未导出 waitid 系统调用包装）；
- `os.waitpid(pid, os.WNOWAIT)` 直接报错 `[Errno 22] Invalid argument`（Darwin 内核 waitpid 不支持 WNOWAIT 标志位）；
- 尝试通过 ctypes 调用 Darwin libc 的 `waitid` 时，由于 Darwin `siginfo_t` 结构体 union 内存布局与对齐特性易触发段错误，且 macOS 内核在 session leader 成为僵尸时对 `killpg` 报错 `ESRCH`。
- **最终选型**：**受控管程（Controlled Supervisor）进程组保持模式**。
  - 新建独立脚本 `scripts/backend/supervisor.py`；
  - 由 `process.py` 启动 supervisor 作为新 session leader（`start_new_session=True`）；
  - 目标真实进程在 supervisor 的同一 process group 内启动，恢复默认信号处理（`restore_signals=True`）；
  - 目标进程结束后，由 supervisor 将真实退出码写入 `supervisor-status.json` 并通过管道发送 `DONE\n`；
  - supervisor 在清理阶段显式设置 `signal.signal(signal.SIGTERM, signal.SIG_IGN)` 并通过管道阻塞等待 runner 控制，**持续持有 PGID 进程组身份，防止 PID 被内核复用**；
  - runner 收到状态后向 `supervisor.pid` 所在组发送 SIGTERM 及必要时的 SIGKILL，由内核一次性杀死组内所有残留后代，最后才调用 `proc.wait()` 回收 supervisor；
  - **绝不在 supervisor 回收后向已释放的 PID 发送任何信号**。

---

## 二、 修复方案实现要点

### 1. `scripts/backend/supervisor.py`（受控管程）
- **会话与进程组 Leader 身份维持**：
  supervisor 安装捕获型 `SIGTERM` 处理器（`def sigterm_handler(...)`），贯穿整个生命周期。依据 POSIX 规范，当在子进程中调用 `exec()` 时，父进程所有捕获型信号处理器均被操作系统内核自动重置为默认处理（`SIG_DFL`），既保证了目标子进程具备标准的信号响应能力，又确保 supervisor 收到组 `SIGTERM` 时不会提前自毁，能稳定维持 PGID 归属直至 `SIGKILL` 清理完毕。
- **管道控制协议与自动断连退出**：
  废除任意硬编码的固定等待（如 60s），supervisor 在 `ctl_fd` 管道上读取控制信号。当 runner 正常回收或异常退出时，内核向 `ctl_fd` 传递 EOF，supervisor 即刻退出，无孤儿遗留。
- **状态确证与真实回传**：
  真实目标 exit code 经原子状态文件 `supervisor-status.json` 与 `status_fd` 管道回传。目标启动失败（如 `FileNotFoundError`）捕获为 127 状态与详细错误字符串，绝不丢失现场。

### 2. `scripts/backend/process.py`（安全执行器）
- 区分 `exit`（总体退出码）、`target_exit`（目标进程真实退出码）与 `supervisor_exit`（管程退出码）；
- 超时标准退出码：发生超时时返回 POSIX 标准退出码 `124`，且真实 `target_exit` 记录为 `None`（严禁伪造猜想的 `-15`）；
- 清理失败防掩盖：若清理过程中发生异常（`cleanup_errors` 非空），总体退出码不能为 0（置为 125），杜绝清理故障被当成干净成功；
- 边界声明：保证清理属于该 session process group 的所有后代进程。若目标进程显式调用 `setsid()` 逃逸出组，则属于进程隔离支持边界之外，绝不使用全系统扫描杀进程避免误伤。

### 3. `scripts/backend/bundle.py`（wrapper `--` 边界防护）
- 在生成的 `probe-wrapper.sh` 头部增加：
  ```sh
  if [ "$1" = "--" ]; then
    shift
  fi
  exec command -- "$@"
  ```
- 若调用者未显式传递 `--`，wrapper 自动补充传递 `--`，彻底防止游戏的 `--log-dir` 被误吞；
- 若调用者（如 Steam toolmanifest）已显式传递 `--`，wrapper 自动 shift 剥除，防止命令行中出现重复 `--`。

---

## 三、 TDD 测试证据与全量验证矩阵

### 1. RED 阶段失败证据（`logs/backend-repair/red.log`）
- 验证 wrapper 未传 `--` 时引发错误：
  `AssertionError: 1 != 0 : Error: Log directory does not exist: game-only`
- 验证缺少 `supervisor_exit` 字段：
  `AssertionError: 'supervisor_exit' not found in result`

### 2. GREEN 阶段通过证据（`logs/backend-repair/green.log`）
执行全量 `tests/backend` 测试套件（27 项全部通过）：
```bash
python3 -m unittest discover -s tests/backend -v
```

控制台实测回显：
```text
test_changed_digest_rejected (test_bundle.BundleTests) ... ok
test_full_proton_needs_linux_python (test_bundle.BundleTests) ... ok
test_missing_manifest_blocks (test_bundle.BundleTests) ... ok
test_prefix_escape (test_bundle.BundleTests) ... ok
test_prepare_does_not_install (test_bundle.BundleTests) ... ok
test_real_bundle_checksums (test_bundle.BundleTests) ... ok
test_wine_plan_no_execution (test_bundle.BundleTests) ... ok
test_wrapper_preserves_verb_and_arguments (test_prepare_integration.PrepareIntegration) ... ok
test_wrapper_without_double_dash (test_prepare_integration.PrepareIntegration) ... ok
test_accurate_nonzero_exit_code (test_process.ProcessTests)
Verify command exiting with specific code returns exact code. ... ok
test_child_ignoring_term_cleaned_up_on_normal_root_exit (test_process.ProcessTests)
Root exits 0, but descendant explicitly ignores SIGTERM. ... ok
test_child_restores_default_sigterm_handler (test_process.ProcessTests)
Verify that target child process starts with SIG_DFL for SIGTERM and never inherits SIG_IGN. ... ok
test_child_survives_root_exit_cleaned_up (test_process.ProcessTests)
Root exits cleanly with exit code 0, but leaves background descendant. ... ok
test_cleanup_wait_timeout_persisted (test_process.ProcessTests)
Mock TimeoutExpired during supervisor cleanup wait. ... ok
test_environment_isolation (test_process.ProcessTests) ... ok
test_exit_and_output (test_process.ProcessTests) ... ok
test_no_signal_to_reaped_pid (test_process.ProcessTests)
Directly observe and assert the timing of killpg vs process reaping: ... ok
test_outside_lab_denied (test_process.ProcessTests) ... ok
test_supervisor_launch_oserror_persisted (test_process.ProcessTests)
Mock failure on supervisor Popen launch. ... ok
test_supervisor_spawn_error_recorded (test_process.ProcessTests)
Verify that an invalid/nonexistent executable is caught and recorded in cleanup_errors and result.json. ... ok
test_target_ignoring_term_on_timeout (test_process.ProcessTests)
Target ignores SIGTERM, writes ready marker with its PID, and sleeps. ... ok
test_timeout (test_process.ProcessTests) ... ok
test_unique_logs (test_process.ProcessTests) ... ok
test_unrelated_control_process_survives (test_process.ProcessTests)
Verify an unrelated control process belonging to current user is NOT killed. ... ok
test_cleanup_error_preserves_result (test_regressions.Regressions) ... ok
test_no_environment_path_escape (test_regressions.Regressions) ... ok
test_real_elf_vernaux_layout (test_regressions.Regressions) ... ok

----------------------------------------------------------------------
Ran 27 tests in 8.644s

OK
```
**退出码**：`0`。

### 3. 全局回归零破坏验证
- `tests/steam` 套件：20 项全部通过（Ran 20 tests, OK）。
- `scripts/proton` 套件：12 项（11 PASS, 1 SKIP）。
- `scripts/abi/test_abi.py`：保持真实基线（3 PASS, 2 FAIL 未被篡改）。
- CLI 默认计划：`python3 -m scripts.backend.cli`（Exit 20, BLOCKED，不伪造运行）。
- CLI Wine 计划：`python3 -m scripts.backend.cli --engine wine`（Exit 0, PLAN_READY）。

---

## 四、 交付文件清单

| 文件路径 | 说明 |
| :--- | :--- |
| `scripts/backend/supervisor.py` | 新增受控 session supervisor 脚本（保持 PGID 身份、管道握手、TERM 保护、EOF 自动退出） |
| `scripts/backend/process.py` | 修复后的隔离 runner（时序安全、分立 target/overall exit、timeout=124、cleanup_errors 持久化） |
| `scripts/backend/bundle.py` | 修复后的 `prepare_tool`（wrapper 兼容传与不传 `--`，不吞游戏 `--log-dir`） |
| `tests/backend/test_process.py` | 新增时序观测、root exit 0 后代忽略 TERM、timeout 忽略 TERM、spawn 错误、准确退出码用例 |
| `tests/backend/test_prepare_integration.py` | 新增 wrapper 不传 `--` 时的完整集成测试用例 |
| `tests/backend/test_regressions.py` | 调整 cleanup failure 断言确保非零退出 |
| `logs/backend-repair/red.log` | RED 阶段失败原始记录 |
| `logs/backend-repair/green.log` | GREEN 阶段 27 项测试全量通过原始记录 |
| `reports/backend.md` | 本交付报告 |

---

## 五、 状态更新

- 任务 `task-16` 已完成，全部测试与验证通过，可提请审查员进行最终独立复审。
