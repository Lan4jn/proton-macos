# 第二轮阶段结果汇总

> **整体状态**：**PARTIAL / 进行中**。目标未全量达成，绝不虚标完成，绝不进入 P2。看板 `task-9`、`task-11`、`task-12` 严格维持 `in_progress`；`task-10`（A-copy 主线）与 `task-14`（事实审计）已完成（`completed`）。

---

## 1. 总体决策与状态矩阵

依据第二轮独立终审报告 [REVIEW-FINAL.md](../../logs/round2-v2/review/REVIEW-FINAL.md)（SHA256: `8338c1b3c75f403197fd741d7058d29ee0f460f120e2ef6d55fe56ec2b853f3f`）及各执行交付收据，第二轮客观状态裁决如下：

| 门控子项 | 最终独立裁决 | 客观证据与支持凭据 | 严格限制与未测边界 |
|---|---|---|---|
| **P1 A-copy (全场景回归与跨层Smoke)** | **FINAL ACCEPTED / PASS** | 7 大 Host 场景（1000 帧正确性、30s 吞吐、latest 3/97、resize-02、busy-01、busy-close-01、disconnect-01）全通；**真实 Linux Guest aarch64 静态 ELF 单帧 smoke (`r2-g1-01`) 真实走通**（耗时 1.34s，Exit 0，CRC32 `355804070` displayed）。主报告 [REPORT.md](../../sources/p1-a-copy-round2/REPORT.md) 正式接受。 | **严格限定为单帧 smoke，`capture: false`，不外推像素核验或屏幕可见性**；真实 Guest 1000/30s 持续长测为 **NOT_RUN**；非真实 Wine/GDI，绝不进入 P2；独占锁已归还。 |
| **P0 A段 (elfuse guest normal)** | **PASS** | `cow-worker` 专项复核确证：原版 (`81803322...`) 与派生 (`3b146bbe...`) 4 阶段屏障全部走通，两采样点瞬间进程严格处于同一 owned PGID，退出码 0，cleanup 完整。见 [GUEST-HARNESS-REVIEW.md](../../logs/round2-v2/review-p0/GUEST-HARNESS-REVIEW.md)。 | 仅证明两采样点瞬间同组无逃逸，不证明全生命周期；定性为 `elfuse guest` 进程模型，非 Linux 内核命名空间；未核验控制终端 (tty)。 |
| **P0 A段 (elfuse guest faults)** | **PASS** | 4 组真实故障实测（原版/派生 timeout 与 crash）全绿：双要素终态比对零残留 (`leaked: 0`)，Sentinel 独立存活并在 finally 块安全回收。见 [independent_real_faults.json](../../logs/round2-v2/review-p0/independent_real_faults.json)。 | 故障由控制器受控发起，不保证宿主内核崩溃下的进程治理。 |
| **P0 B段 (Wine Adapter & 实测)** | **NOT_READY (真实对照 NOT_RUN)** | 完成前台 `wineserver -f` 治理与 APFS clonefile 物理隔离防写穿；**真实执行三轮物理实测**，第 3 轮物化 `l_intl.nls` 后 Wineserver 达成阶段 1 真实就绪突破，阶段 2 拉起 Wine 进程后遭遇退出码 29 退出。见 [REPORT.md](../../sources/p0-session-round2/REPORT.md)。 | **目标 PE 入口点是否真正执行为 UNKNOWN（无专属 marker），同 PE 原版/派生对照 NOT_RUN**；Wine 门判定为 **NOT_READY**；遵守纪律坚决止步，不无限链式追加资源。 |
| **P1 C-decoupled** | **DEFERRED_NOT_SELECTED** | 静态决策与否决条件已封存，C1 生命周期与实现 NOT_RUN。见 [DECISION.md](../../sources/p1-c-decoupled-v2/DECISION.md)。 | 仅在 A 实测证实为瓶颈或 P2 有同进程硬性需求时由 Lead 决定重开。 |
| **R1 COW 矩阵 / S1 Steam / P2** | **FROZEN / NOT_RUN** | 第二轮严格禁止展开，维持第一轮冻结结论。 | 正常 COW 可靠性仍为 FAIL；Steam 真实客户端未测；P2 驱动闭环严格关闭。 |

---

## 2. P1 A-copy 主线验证事实与最终里程碑 (FINAL ACCEPTED)

在 P0 单一进程组继承与独立 outer watchdog 治理加固下，固定 AppKit presenter 二进制（SHA256: `b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb`）达成全线突破并正式结题（`task-10` completed）：

### 2.1 7 大 Host 呈现场景全量通过
1. **1000 帧变化帧正确性 (`r2-correctness-01`)**：耗时 9.18s，逐帧比对一致（`capture_match: 1`，JSON 模式实际为整数 1），1000 terminal 均为 `displayed`，退出码 0，收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-correctness-01/receipt.json)；
2. **30s 720p30 吞吐长测 (`r2-throughput-01`)**：持续 30.004s，900 帧全显示，载荷达 110.575 MB/s；RTT p50 13.03ms / p95 17.20ms，帧龄 p50 5.14ms / p95 8.55ms，收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-throughput-01/receipt.json)；
3. **高频推帧 Latest (`r2-latest-01`)**：100 帧输入，**真实客观数值核实确为 `displayed: 3, replaced: 97`**（两者相加严格等于 100），收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-latest-01/receipt.json)；
   - *历史数据纠偏*：初期口头通报中出现的 9/91 数值冲突已在 [CORRECTIONS.md](../../sources/p1-a-copy-round2/CORRECTIONS.md) 中正式纠偏澄清：原始磁盘收据客观记录为 3/97；因早期临时状态未单独留痕，历史生成过程定性为未知（UNKNOWN），基于当前冻结字节开展验收并解除暂扣；
4. **动态 Resize (`r2-resize-02`)**：seq 1/2 正常显示，seq 3（旧 gen 1）在 header-only 阶段被 Host 拒绝返回 `ERROR: frame_shape_identity` 且绝无 ACK 产生，收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-resize-02/receipt.json)；首轮 BrokenPipe 退出 1 保留为历史负测记录；
5. **3s 纯算预排 UI 事件 (`r2-busy-01`)**：纯算持续 3000.05ms，在同一单调时钟约束下确认主线程调度 `ui_event` 并收到 `HANDLED` ACK，收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-busy-01/receipt.json)；
6. **3s 纯算关闭响应 (`r2-busy-close-01`)**：纯算持续 3000.29ms，主线程调度 `close_event` 并触发安全退出，收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-busy-close-01/receipt.json)；
7. **正常断连 (`r2-disconnect-01`)**：主动断连后 Host 捕获 EOF 有界退出 (exit 0)，进程组完全清理，收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-disconnect-01/receipt.json)。

### 2.2 真实 Linux Guest C Producer 单帧实测 (`r2-g1-01`) 真实走通
在 Lead 批准与串行锁放行下，由专用启动器（[`guest_launcher.py`](../../scripts/p1_a_copy_round2/guest_launcher.py)）驱动 Linux guest 内部的真实纯静态 C 二进制（`guest_producer_arm64`，SHA256: `f699318aff3bffb55cf03dddaa69f82c68ace2cee643e64aff8f3a989847e12e`）与宿主 AppKit presenter 联调：
- **运行实据**：Runner exit 0，Target exit 0，整组耗时 1.34s，四个子阶段 exit 0，P0 治理完整 (`cleanup_complete: true`)，收据见 [receipt.json](../../logs/p1-a-copy-round2/r2-g1-01/receipt.json)；
- **帧与载荷核验**：成功传输 1 帧 720p（1280x720，RGBA8，共 3,686,400 字节，CRC32: 355804070）；
- **协议闭环**：依次收到 `CONFIGURED`、`RECEIVED`、`displayed` CONSUMED 及最终 `CLOSED` ACK；
- **严格边界**：测试设置 `capture: false`，**严格限定为跨架构 IPC 连通与生命周期消费验证，不外推为像素比对或屏幕可见性**；当前阶段无需进行 guest 多帧测试，绝不进入 P2。

---

## 3. P0 Session 治理：9 组真实 Guest 专项与 Wine 差距分析

### 3.1 6 组真实 Guest 屏障与故障实测 (全量 PASS)
在 Lead 授权下严格持有 guest 串行锁，分别针对原版 (`81803322...`) 与派生版 (`3b146bbe...`) 运行 6 组真实 guest 专项：
1. **Normal 屏障基线实测 (2 组)**：
   - 原版：[receipt.json](../../logs/session-v2-round2/p0-r2-orig-normal-run2/receipt.json)，Runner exit 0，Target exit 0，清理完整；
   - 派生版：[receipt.json](../../logs/session-v2-round2/p0-r2-derived-normal/receipt.json)，Runner exit 0，Target exit 0，清理完整；
   - 采样证实：在 PRE 与 POST 两个屏障点瞬间，四个 PPID 级联进程全部位于同一 owned PGID，退出码为 0。
2. **真实 Fault 故障实测 (4 组)**：
   - 超时故障：`p0-r2-orig-timeout` 与 `p0-r2-derived-timeout`，Runner exit 124 且 `inner_timed_out: true`；
   - 崩溃故障：`p0-r2-orig-crash` 与 `p0-r2-derived-crash`，Runner exit 70，Worker 异常后 P0 独立完成收据落盘与进程清理；
   - 终态比对证实零残留泄漏 (`leaked: 0`)，Sentinel 进程均存活并在 finally 块安全回收（见 [independent_real_faults.json](../../logs/round2-v2/review-p0/independent_real_faults.json)）。
3. **证据边界**：仅证明两采样点瞬间同组无逃逸，不证明全生命周期；定性为 `elfuse guest` 进程模型，非 Linux 内核命名空间；探针未核验控制终端 (tty)。

### 3.2 真实 Wine 三轮实测推进与底层差距事实
在 APFS clonefile 物理隔离防写穿与 `wine_launcher.py` 严格治理下，对真实 Wine 进行了三轮独立物理探测：
1. **首轮实测 (`p0-r2-wine-orig`)**：wineserver 在 5.0s 内未就绪，raw stderr 记录 `wineserver: /prefix is not owned by you`，确认为客体 UID 1000 与宿主 UID 501 属主不符，PE 未启动（`wine_exit: null`），收据见 [receipt.json](../../logs/session-v2-round2/p0-r2-wine-orig/receipt.json)；
2. **第二轮实测 (`p0-r2-wine-orig-u`)**：引入原生 `--user 501:20` 参数，属主错误彻底消除；进而捕获到深层依赖缺失：`wineserver: failed to load l_intl.nls`，PE 未启动（`wine_exit: null`），收据见 [receipt.json](../../logs/session-v2-round2/p0-r2-wine-orig-u/receipt.json)；
3. **第三轮新假说实测 (`p0-r2-wine-orig-nls`)**：
   - **阶段 1 真实突破**：物理物化单个 5.4KB `l_intl.nls`（SHA256 `ad190cb8...`）后，wineserver 成功加载并建立套接字监听，非阻塞探针在 guest 内握手成功输出 `status: "READY", uid: 501`，判定 `server_ready: true`！
   - **阶段 2 真实启动与深层退出**：解除阻断后，启动器真正派生拉起 Wine 进程以执行目标 PE，最终以退出码 29 退出（`wine_exit: 29`，`wineserver_exit: -15`，P0 清理完成），收据见 [receipt.json](../../logs/session-v2-round2/p0-r2-wine-orig-nls/receipt.json)；
   - **底层事实清单 (stderr 物理证据)**：
     - `WARN src/syscall/syscall.c:3505: unimplemented syscall 374 (x0=0x80801, ...)`：仅记录为系统调用行号与编号事实，不强行作具体名称推断，不假设单一致命因果；
     - `err:environ:read_nls_file failed to load .../c_20127.nls` 与 `locale.nls`；
     - `wine: failed to start L"C:\\windows\\system32\\wineboot.exe": c0000135` (STATUS_DLL_NOT_FOUND)；
     - `0028:err:module:load_apiset_dll failed to load apiset: c000000f`；
     - `0028:err:seh:NtRaiseException Unhandled exception code c000001d flags 0 addr 0xdfffbc6610`；
   - **定性校准**：**由于缺乏专属 marker，目标 PE 的 WinMain 或主入口点是否真正被执行判定为 UNKNOWN**（日志反映失败发生在 Wine 加载器与 Windows 子系统初始化阶段）；
   - **止步纪律**：坚决遵守同假设最多两轮原则，不无限链式追加资源，不运行派生运行时对照，B 段到此闭环止步。

---

## 4. 下一门规划 (NEXT-GATE)

1. **未实现系统调用支持评估**：
   专项评估 `syscall 374` 在 elfuse 运行时中的调用背景与处理边界，分析其对 Wine 初始化流程的影响；
2. **Wine 加载器基础运行依赖完善**：
   - 补齐 NLS 扩展编码表：`c_20127.nls` 与 `locale.nls`；
   - 补齐基础 Windows 用户态组件：`wineboot.exe`（DLL/可执行文件补齐）与 `apiset` 映射模块；
3. **同 PE 原 / 派生两 Runtime 对照**：
   在加载器环境与系统调用支持确立后，再严格按同配置（`--user`、prefix、无 opt-in）放行 `original` 与 `derived` 的首轮同 PE 完整执行比对。

---

## 5. 初始 69 项基线与具体 5 项受测源文件防篡改审计

1. **初始冻结资产复核 (100% MATCH)**：
   [initial-freeze.json](../../logs/round2-v2/review/initial-freeze.json) 中 69 唯一路径本次比对零差异；额外 [initial-freeze-a-inputs.json](../../logs/round2-v2/review/initial-freeze-a-inputs.json) (4 项) 与 [initial-freeze-zig.json](../../logs/round2-v2/review/initial-freeze-zig.json) (1 项) 为独立清单、不可混算，经全量校验全部物理路径哈希**100% 逐字节匹配，零篡改**；
2. **具体受测 5 项核心文件路径与哈希精确审计（100% MATCH，绝不放大声称全目录）**：
   - `sources/proton-v3-deploy/original/files/bin-arm64/wine`: `0eb603be3624255de6d13740b73c4c5bbb9ee5c1f5f9120abdb3ebc408dab91b` (PASS)
   - `sources/proton-v3-deploy/original/files/bin-arm64/wineserver`: `dc6b16a7428df4beca04620839fc13e231a529270bd40b43c3ae3dd2d990995c` (PASS)
   - `fixtures/runtime/pe-worker/pfx/drive_c/minimal-x64.exe`: `87406032e5b7c6546afe5fa0f03847a5e398cb4981c969604417a828ab266bc8` (PASS)
   - `sources/elfuse-once-panorama2-derived/build/elfuse`: `8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda` (PASS)
   - `sources/elfuse-inproc-present-derived/build/elfuse`: `3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926` (PASS)
   APFS clone 物理隔离生效，未发生写穿篡改。
3. **纪律遵守**：未修改任何旧报告、第一轮冻结产物或 `PROJECT-STATUS.md`；未修改系统、Steam 或全局包；无 git commit 或 push。
