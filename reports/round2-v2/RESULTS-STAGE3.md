# 第二轮阶段结果汇总（Stage 3 终审增补版）

> **整体状态**：**本次第二轮工程核验任务交付完成，但 Wine 运行时业务功能目标未达成 (NOT_READY)**。绝不因为工程任务闭环而模糊业务判定，绝不进入 P2。看板 `task-9`、`task-10`、`task-11`、`task-14`、`task-15` 达成目标记录为 `completed`；`task-12` 本阶段汇总核验完成后亦结项置为 `completed`。先前报告（[RESULTS.md](RESULTS.md)，SHA256: `62682b3aad33c48bd54eb96a73bf71e26a303c9654698472a58d5fde893eb50b`）保持物理只读，本文件仅作为 Stage 3 事实与验收的独立增补。

---

## 1. 总体决策与状态矩阵

依据第二轮独立终审最终验收报告 [FINAL-ACCEPTANCE.md](../../logs/round2-v2/stage3-review/FINAL-ACCEPTANCE.md)（SHA256: `45fa67a1362f02c19d8c53672599ab75276aab159758055d39d8a609f445c7d8`）、归一化对照收据 [comparison-validated.json](../../logs/session-v2-round2/stage3/comparison-validated.json) 及 [DELIVERY-STAGE3.md](../../sources/p0-session-round2/stage3/DELIVERY-STAGE3.md)，客观状态矩阵如下：

| 门控子项 | 最终独立裁决 | 客观证据与支持凭据 | 严格限制与未测边界 |
|---|---|---|---|
| **P1 A-copy (全场景回归与跨层Smoke)** | **FINAL ACCEPTED / PASS** | 7 大 Host 场景全通；真实 Linux Guest aarch64 静态 ELF 单帧 smoke (`r2-g1-01`) 真实走通（耗时 1.34s，Exit 0，CRC32 `355804070` displayed）。主报告 [REPORT.md](../../sources/p1-a-copy-round2/REPORT.md) 正式接受。 | **严格限定为单帧 smoke，`capture: false`，不外推像素核验或屏幕可见性**；真实 Guest 1000/30s 持续长测为 **NOT_RUN**；非真实 Wine/GDI，绝不进入 P2；独占锁已归还。 |
| **P0 A段 (elfuse guest 治理)** | **PASS** | 真实 elfuse guest 6 场景（2 normal + 4 faults）全绿：两采样点瞬间进程严格处于同一 owned PGID；双要素终态比对零残留 (`leaked: 0`)，Sentinel 独立存活并在 finally 块安全回收。见 [GUEST-HARNESS-REVIEW.md](../../logs/round2-v2/review-p0/GUEST-HARNESS-REVIEW.md) 与 [independent_real_faults.json](../../logs/round2-v2/review-p0/independent_real_faults.json)。 | 仅证明两采样点瞬间同组无逃逸，不外推全生命周期；定性为 `elfuse guest` 进程模型，非 Linux 内核命名空间；未核验控制终端 (tty)。 |
| **P0 B段 (Wine 同 PE 两运行时对照)** | **对照已执行比对 (PASS); Wine 运行功能定性 NOT_READY** | 在 22.76MB 物理闭包与无 opt-in 归一化条件下，**原版 (`81803322...`) 与派生 (`3b146bbe...`) 使用相同的受测 PE (`minimal-x64.exe`) 真实完成了对照执行**。两者 server 均握手就绪（`server_ready: true`），两者 Wine PE 均拉起并在加载器阶段以相同退出码 29 退出（见 [comparison-validated.json](../../logs/session-v2-round2/stage3/comparison-validated.json)）。 | **两组失败表现一致仅限有限错误/exit 29 观测，绝不外推为全部运行时等价**；目标 PE 入口执行状态判定为 **UNKNOWN**（无专有 marker 43，失败发生在加载器初始化，是否触及 mainCRTStartup 入口判定为 UNKNOWN）；Wine 运行功能维持 **NOT_READY**；遵守纪律坚决止步，不无限追加闭包资源。 |
| **P1 C-decoupled** | **DEFERRED_NOT_SELECTED** | 静态决策与否决条件已封存，C1 生命周期与实现 NOT_RUN。见 [DECISION.md](../../sources/p1-c-decoupled-v2/DECISION.md)。 | 仅在 A 实测证实为瓶颈或 P2 有同进程硬性需求时由 Lead 决定重开。 |
| **R1 COW 矩阵 / S1 Steam / P2** | **FROZEN / NOT_RUN** | 第二轮严格禁止展开，维持第一轮冻结结论。 | 正常 COW 可靠性仍为 FAIL；Steam 真实客户端未测；P2 驱动闭环严格关闭。 |

---

## 2. P1 A-copy 主线验证事实与最终里程碑 (FINAL ACCEPTED)

P1 A-copy 路线全量完成第二轮目标并被正式接受，成果已固化在先前报告中，无需后续 guest 多帧测试：
1. **Host 7 大场景全量回归通过**：
   - 1000 帧正确性长测 (`r2-correctness-01`): 1000 帧逐像素核验一致（`capture_match: 1`），1000 终端全为 `displayed`，收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-correctness-01/receipt.json)；
   - 30 秒 720p30 吞吐长测 (`r2-throughput-01`): 900 帧全部显示，载荷达 110.575 MB/s；RTT p50 13.03ms / p95 17.20ms，帧龄 p50 5.14ms / p95 8.55ms，收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-throughput-01/receipt.json)；
   - 增量场景：`latest` (客观实测数值 `displayed: 3, replaced: 97`，早期 9/91 口头冲突已在 [CORRECTIONS.md](../../sources/p1-a-copy-round2/CORRECTIONS.md) 中纠偏澄清并按当前冻结字节验收)、`resize-02` (旧代 header 拒签返回 ERROR 且无违规 ACK)、`busy-01` 与 `busy-close-01` (3s 纯算窗口内观察到主线程 `HANDLED` 事件 ACK)、`disconnect-01` (安全退出清理)。
2. **跨层真实 Linux Guest 通信 (单帧 Smoke 真实走通)**：
   - 纯静态 Linux aarch64 ELF (`guest_producer_arm64`，SHA256: `f699318aff3bffb55cf03dddaa69f82c68ace2cee643e64aff8f3a989847e12e`) 在真实 `elfuse` 环境下拉起并通过 AF_UNIX 套接字与 Host 联调（`r2-g1-01`，耗时 1.34s，Exit 0，收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-g1-01/receipt.json)）；
   - 真实发送 1 帧 720p RGBA8 (3.68MB)，CRC32 `355804070`，Host 完整广播 `CONFIGURED`、`RECEIVED`、`displayed` CONSUMED 及最终 `CLOSED` 双 ACK 闭环；
   - **严格界限**：参数为 `capture: false`，**不充当像素核验或屏幕可见证据**；未执行多帧长测，绝不进 P2，独占锁已彻底交还。

---

## 3. P0 Session 治理：真实 Guest 实跑与两运行时真实比对

### 3.1 真实 elfuse guest 屏障与受控故障实测 (全量 PASS)
在 Lead 授权下严格持有 guest 串行锁，分别针对原版 (`81803322...`) 与派生版 (`3b146bbe...`) 运行真实 guest 专项：
1. **Normal 屏障基线实测**：
   - 原版：[receipt.json](../../logs/session-v2-round2/p0-r2-orig-normal-run2/receipt.json)，Runner exit 0，Target exit 0，清理完整；
   - 派生版：[receipt.json](../../logs/session-v2-round2/p0-r2-derived-normal/receipt.json)，Runner exit 0，Target exit 0，清理完整；
   - 采样证实：在 PRE 与 POST 两个屏障点瞬间，四个 PPID 级联进程全部位于同一 owned PGID，退出码为 0。
2. **受控故障实测 (Faults)**：
   - 超时故障：`p0-r2-orig-timeout` 与 `p0-r2-derived-timeout`，Runner exit 124 且 `inner_timed_out: true`；
   - 崩溃故障：`p0-r2-orig-crash` 与 `p0-r2-derived-crash`，Runner exit 70，Worker 异常后 P0 独立完成收据落盘与进程清理；
   - 终态比对证实零残留泄漏 (`leaked: 0`)，Sentinel 进程均存活并在 finally 块安全回收（见 [independent_real_faults.json](../../logs/round2-v2/review-p0/independent_real_faults.json)）。
3. **证据边界**：仅证明两采样点瞬间同组无逃逸，不外推为全生命周期或“全局零孤儿”；定性为 `elfuse guest` 进程模型，非 Linux 内核命名空间；探针未核验控制终端 (tty)。

### 3.2 Stage 3 两运行时同 PE 无 Opt-in 真实比对 (失败基线已测，不再 NOT_RUN)
在 Stage 3 建立的 22.76MB 物理闭包（17 项文件，含 1 PE + 1 wineboot + 12 DLLs + 3 NLS 表，完全受控于 30MB 选定闭包预算内，见 [CLOSURE_MANIFEST_V2.json](../../sources/p0-session-round2/stage3/CLOSURE_MANIFEST_V2.json)）与单 PGID 启动器加固下，两款 runtime 真实完成了同 PE 对照比对（数据源自 [comparison-validated.json](../../logs/session-v2-round2/stage3/comparison-validated.json)）：

| 对照维度 | 原版运行时 (`original`) | 派生运行时 (`derived`) | 归一化判定与等价性边界 |
|---|---|---|---|
| **执行 Run-ID** | [p0-r2-wine-orig-s3v2](../../logs/session-v2-round2/p0-r2-wine-orig-s3v2/receipt.json) | [p0-r2-wine-derived-s3v2](../../logs/session-v2-round2/p0-r2-wine-derived-s3v2/receipt.json) | 物理环境、超时预算 (60/75/85)、WINEPREFIX 隔离完全一致 |
| **运行时 SHA256** | `8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda` | `3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926` | 严格绑定真实物理二进制 |
| **受测 PE 目标** | `minimal-x64.exe` (`87406032...`) | `minimal-x64.exe` (`87406032...`) | 目标 PE 输入完全相同 |
| **物理运行耗时** | 18.11 秒 | 18.91 秒 | 运行轨迹与耗时量级完全一致 |
| **Runner / Target 退出** | 1 / 1 | 1 / 1 | 测得退出码完全匹配 |
| **Wineserver 状态** | `READY` (握手通过) / 回收码 `-15` | `READY` (握手通过) / 回收码 `-15` | 阶段 1 前台 server 真实就绪完全一致 |
| **Wine PE 退出码** | **29** | **29** | 阶段 2 退出码完全匹配 |
| **stderr 物理日志现象** | 并列记录 `wineboot c0000005`、未实现 `syscall 374`、`c000001d` 异常 | 并列记录 `wineboot c0000005`、未实现 `syscall 374`、`c000001d` 异常 | 物理错误类别完全一致 |
| **宿主治理清理** | `complete: true` (ps 采样无活跃孤儿) | `complete: true` (ps 采样无活跃孤儿) | P0 治理均安全闭环 |

- **失败基线等价性与非外推声明 (Hard Boundaries)**：
  1. **比对任务已完成，基线定性 NOT_READY**：真实同 PE 原版/派生对照已经实际执行比对，**对照状态不再是 NOT_RUN**；但由于两者均以退出码 29 受阻，Wine 运行功能基线状态严格定性为 **NOT_READY**；
  2. **有限错误等价，绝非全量 Runtime 等价**：比对确证两款 runtime 在此特定 22.76MB 闭包与环境配置下呈现相同的退出码与错误类别，**绝不外推为原版与派生运行时全功能等价，亦不宣称两者具备完全相同的内部深层根因**；
  3. **PE 入口执行状态严格判定为 UNKNOWN**：因均未捕获到专有的退出码 43 Marker，目标 PE 的入口点（`mainCRTStartup`）是否真正被执行判定为 **UNKNOWN**（日志反映失败发生在 Wine 加载器初始化阶段）；
  4. **止步纪律**：遵守同假设最多两轮原则，第二轮实测就此闭环止步，不无限链式追加闭包资源。

---

## 4. 下一门规划 (NEXT-GATE)

1. **未实现系统调用专项评估**：
   专项评估运行时未实现的 `syscall 374`（源码 `src/syscall/syscall.c`）在 elfuse 中的调用背景与处理边界，分析其与 Wine 加载器崩溃之间是否存在因果联系；
2. **加载器内部异常诊断与断点分析**：
   - 重点诊断 `wineboot.exe` 初始化系统 DLL 失败（`status c0000005`）与最后未捕获异常（`Unhandled exception code c000001d`）之间的具体关系；
   - 验证是否真正阻断在 Windows 核心子系统初始化（如注册表、会话初始化），而非简单文件缺失；
3. **同 PE 业务运行功能突破 (PE 43)**：
   在加载器环境与系统调用支持确立后，以捕获目标 PE 专有退出码 43 Marker 为验收标准，再行验证真实 PE 主代码（`mainCRTStartup`）执行。

---

## 5. 资产防篡改审计与偏差记录 (Audit & Freeze Deviation)

1. **初始基线资产核验 (100% MATCH)**：
   [initial-freeze.json](../../logs/round2-v2/review/initial-freeze.json) 中 69 项唯一物理资产本次比对零差异；额外 [initial-freeze-a-inputs.json](../../logs/round2-v2/review/initial-freeze-a-inputs.json) (4 项) 与 [initial-freeze-zig.json](../../logs/round2-v2/review/initial-freeze-zig.json) (1 项) 为独立清单、不可混算，经全量校验全部物理路径哈希**100% 逐字节匹配，零篡改**；第一轮冻结基线未受第二轮任何执行影响；
2. **第二轮阶段文档偏差记录 (Freeze Deviation)**：
   依据 [freeze-deviation.json](../../logs/round2-v2/stage3-review/freeze-deviation.json)，严肃记录 Reviewer 在 stage3 跟踪期间误改旧稿 `REVIEW-FINAL.md`（由定稿 `8338c1b3` 变为 `4a81d213`），随后恢复失败（当前为 `b45f8548`）；偏差已归档至 [freeze-deviation.json](../../logs/round2-v2/stage3-review/freeze-deviation.json) 并永久冻结修改，最终终审验收均严格受限于 [FINAL-ACCEPTANCE.md](../../logs/round2-v2/stage3-review/FINAL-ACCEPTANCE.md)，不称所有第二轮中间草稿绝对零变；
3. **Stage 3 v2 闭包 17 项物理源文件防篡改审计 (100% MATCH)**：
   包含目标 PE (`minimal-x64.exe`)、`wineboot.exe`、12 个核心系统 DLL（含 `cryptbase.dll` 与 `cryptsp.dll` 导出转发依赖）以及 3 个 NLS 编码表文件，全部 17 项物理源文件哈希零偏差吻合，物理总大小实测为 22.76 MB（< 30 MB 预算），APFS 物理隔离生效，未发生写穿篡改；
4. **纪律遵守**：
   - 未修改已冻结的前轮成果：第一轮 8 项交付报告、第一轮 56 项基线产物、[RESULTS.md](RESULTS.md)（SHA256: `62682b3aad33c48bd54eb96a73bf71e26a303c9654698472a58d5fde893eb50b`）、A 路线最终报告 [REPORT.md](../../sources/p1-a-copy-round2/REPORT.md) 以及 `PROJECT-STATUS.md` 均保持物理只读；
   - 未修改系统、Steam 或全局包；无 git commit 或 push。
