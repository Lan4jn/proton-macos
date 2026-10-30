# P0 第二轮受控故障注入方案（待 Lead / cow-worker 审核）

## 背景与目标
在两款 runtime（original 与 derived）正常模式（normal）均已成功通过并确证 Linux guest 内部 `setsid()` 生效及 PRE/POST 采样时刻宿主四节点链严格归属 owned PGID 的基础上，按第一轮 NEXT-GATE 规格，补齐两组受控故障场景：
1. **inner timeout**（内部超时受控触发与清理）
2. **worker crash**（宿主 worker 会话组长异常崩溃与治理）

---

## 核心机制与时序控制

### 1. 预算与时序区分（严防探针自退冒充超时）
- **问题定义**：静态 Linux probe 内部 `wait_ack()` 设置了 5 秒超时自退（退出码 72）。若 P0 inner timeout 设置大于或等于 5 秒，probe 将因等不到 ACK 自行退出，导致 P0 worker 误将正常退出判定为 target exit，冒充真正的超时。
- **精确预算配置**：
  - **P0 inner timeout**：设置为 **2.0 秒**（明确小于 probe 的 5s 自退时限与 runtime 的 12s 预算）。
  - **P0 outer watchdog**：设置为 **6.0 秒**（带 `--fixture-short-outer`），高于 inner timeout 4 秒，确保外层监督器兜底。
  - **时序流程**：
    1. Probe 启动，输出 parent，fork 子进程输出 pre；
    2. Observer 捕获 pre 事件，核实 token 并完成 PRE 阶段宿主四节点链采样记录，写入 `guest-pre.json`；
    3. Observer **故意扣留 `post.ack`**，使 guest probe 子进程阻塞在 setsid 后的 POST 屏障等待中；
    4. 达到 2.0 秒后，P0 worker 内部 `p.wait(timeout=2.0)` 抛出 `subprocess.TimeoutExpired`，记录 `inner_timed_out: true`，`target_exit: null`；
    5. P0 parent 捕获结果，输出 `runner_exit: 124`，并对 owned PGID 发送 SIGTERM / SIGKILL 完成清理；
    6. 终态采样断言：probe 未有机会触发 5s 自退或正常 exit，确由 P0 超时机制终止。

### 2. Worker 崩溃控制（严格限定已核验身份单次发信）
- **控制器角色与权限**：
  - 故障注入控制器由外层测试 harness 派生或作为非被测组的独立进程。
  - 禁止盲向未知 PID/PGID 发送信号；控制器必须读取 P0 的 `owned.json`，并通过 `/bin/ps` 实时核对 worker 的 PID、PGID 与 `lstart` 启动时间戳（身份严格一致）。
- **注入时序**：
  - 在 PRE 阶段确认宿主四节点链（worker -> observer -> elfuse -> child）完整落盘后，控制器执行单次 `os.kill(worker_pid, signal.SIGKILL)`。
  - P0 parent 作为唯一 reaper，在轮询中通过 PID 状态检查发现 worker 进程变为僵尸（`state.startswith('Z')`）或消失，捕获到 worker 提前异常退出（`runner_exit: 70`）。
  - P0 parent 立即执行组清理，对属于该 owned PGID 的全部残余进程发送 SIGTERM/SIGKILL。
  - 故障发生前由 observer 预先记录落盘的四节点链 PID 集合，在终态 ps 中被逐一核查，确认无一残留。

### 3. 独立 Sentinel 保护
- 每次测试前，测试框架派生一个独立会话组的 sentinel 进程（`python3 -I -c 'import time; time.sleep(60)'`, `start_new_session=True`）。
- 测试过程中 sentinel 与被测 P0 组完全隔离。
- 在测试无论是正常、超时还是崩溃退出后，通过 `finally` 块核验 sentinel 依然存活，且由创建者显式 terminate 与 wait 回收，断言无误杀、无泄漏。

---

## 阶段门与交付边界

1. **先在 Host Fixture 模拟**：
   - 不修改已冻结的 normal 文件。
   - 新增专用故障 harness：`scripts/runtime/session_v2_round2/guest_fault_harness.py`（包含 `--fault-timeout` 与 `--fault-crash` 模式）。
   - 编写 `tests/session_v2_round2/test_guest_faults.py`，先跑 host fake runtime 模拟红绿测试。
2. **审查与真机放行**：
   - 独立审查员核验方案与 host 测试通过。
   - 申请独占 guest 锁，针对 `original` 与 `derived` 两款 runtime 分别执行 1 轮 inner timeout 与 1 轮 worker crash（共 4 个 run-id：`p0-r2-orig-timeout`, `p0-r2-orig-crash`, `p0-r2-derived-timeout`, `p0-r2-derived-crash`）。
3. **完成标准**：
   - 超时场景：`inner_timed_out: true`, `target_exit: null`, `runner_exit: 124`, PRE 四节点链落盘且归属 owned PGID，sentinel 存活。
   - 崩溃场景：`runner_exit: 70`, 故障前四链预留 PID 终态确认全部清理完毕，sentinel 存活。
