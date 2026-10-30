# 第一轮结果汇总

## 结论与决策

**整体为 PARTIAL，P1 为 NOT_READY，尚不进入 P2。** P0 的 owned-session fixture 治理门通过，真实 Wine 原/C runtime 同 PE 对照未运行；R1 的诊断证据通过，但正常 COW 可靠性门失败；S1 的离线核查通过，真实客户端行为未测。验收合同与范围见 [第一轮任务书](<TASKBOOK.md>)。

1. **A/C 选择：优先继续 A-copy 的验证，C-decoupled 暂缓，尚无全门胜出的候选。** A 的首版 host-only 结果有正向证据，但完整套件失败；最终 binary 的独立定点复核 10/10 PASS，完整套件与真实 Linux guest producer 未运行。C 的线程和生命周期静态调查已审，C1 功能未运行；`DEFERRED_NOT_SELECTED` 不是技术失败或平台不可行。详见 [C 决策](<../../sources/p1-c-decoupled-v2/DECISION.md>)、[A 定点结果](<../../logs/round1-v2/review/a-111830/results.json>)和[独立审查](<../../logs/round1-v2/review/review-20261028T102002/REVIEW.md>)。
2. **COW 最小可修边界：** 候选为 host 16 KiB 粒度 overlay/backing 生命周期与 guest 4 KiB lane 身份、事务式替换恢复，以及相邻 shared lane 在 fixed/unmap/remap/fork 中的可见性；需覆盖 region metadata 和 HVF remap/quiescence。该 seam 是基于观测和静态源码的候选，不是完整根因证明或已实现修复。详见 [R1 诊断](<../../sources/r1-cow-matrix-v2/DIAGNOSIS.md>)。
3. **Steam 下一行为：** 先对固定版本客户端离线定位兼容工具字串 xref、路径构造与平台 predicate；首个动态门则在可丢弃测试系统上验证实际扫描，继而用仅写 marker 并退出的工具记录一次调用的 argv/cwd 与白名单环境。本轮未执行客户端、登录或安装；详见 [S1 离线报告](<../../sources/s1-steam-offline-v2/task-6/README.md#L136-L145>)。

## 分阶段状态

| 门 | 判定 | 证据范围与剩余事项 |
|---|---|---|
| P0 治理子门 | **PASS** | 新 runner 的 owned PGID fixture 与独立复核通过；不保证主动 setsid 逃逸或父监督器 SIGKILL 情况。见 [交付](<../../logs/session-v2/DELIVERY.md>)、[独立结果](<../../logs/round1-v2/review/review-20261028T102002/p0-final-summary.json>)。 |
| P0 基线门 | **NOT_RUN_ADAPTER_PENDING** | 同 PE/预算原 runtime 与 C 派生 Wine 对照未执行；需先治理 Wine 的 fork/setsid、foreground 与真实进程身份。见 [接入边界](<../../scripts/runtime/session_v2/BASELINE-ADAPTER.md>)和[下一门方案](<../../scripts/runtime/session_v2/NEXT-GATE.md>)。P0 整体 PARTIAL。 |
| P1 A-copy | **FINAL_UNVERIFIED；整体 NOT_READY** | 首版 host-only 1000 变化帧与 30 秒观测有证据；首版 full exit 1，3 项 BrokenPipe harness。最终版独立定点 10/10 PASS；最终 full 未重跑、完整 outer watchdog 缺失、真实 guest producer 未测。见 [A 报告](<../../sources/p1-a-copy-v2/REPORT.md>)及[最终定点结果](<../../logs/round1-v2/review/a-111830/results.json>)；旧性能不绑定新 binary。 |
| P1 C-decoupled | **静态子门 PASS；DEFERRED_NOT_SELECTED** | 独立核对 15 项输入及摘录，C1 新线程、fork/exec/teardown、帧与响应性试验均 NOT_RUN。见 [静态决策](<../../sources/p1-c-decoupled-v2/DECISION.md>)和[审查](<../../logs/round1-v2/review/review-20261028T102002/REVIEW.md#L16-L19>)。 |
| R1 诊断 / 可靠性 | **诊断 PASS / 可靠性 FAIL** | 原 runtime 九项 7 PASS、fixed/remap 2 FAIL；C 派生旧 probe 的 fork-private 原结果证据不足，新 probe 补测该项 PASS。fixed/remap 异常经独立原 runtime 复跑。Windows WRITECOPY 与生产修复未测。见 [诊断](<../../sources/r1-cow-matrix-v2/DIAGNOSIS.md>)。 |
| S1 离线 / 动态 | **离线 PASS / 动态 NOT_RUN** | 固定版本静态字节和一手资料支持分层研究，未证明 macOS 实际扫描、Windows depot 获取或 Steamworks 桥接。见 [S1 报告](<../../sources/s1-steam-offline-v2/task-6/README.md>)和[独立审查](<../../logs/round1-v2/review/review-20261028T102002/REVIEW.md#L37-L41>)。 |

## P0：治理证据与实际边界

[自测收据](<../../logs/session-v2/verification-444e300728fe4377a1dec5d69aae3770/verification.json>)记录 `python3 -I tests/session_v2/test_runner.py` 退出 0，10 项通过；[独立结果](<../../logs/round1-v2/review/review-20261028T102002/p0-final-summary.json>)为 9 项复跑及单独的启动异常 8 条断言。runner 完整 SHA256 `3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b`。记录的 PID 是采样，不代表信号瞬间所有后代；目标退出未观测时显式标记，不以 runner exit 代替 target exit。

真实 Wine 对照尚未运行。Wine 默认 server daemon 路径存在 fork/setsid，静态源码中的 guest session 与 host PGID 关系尚不足以证明实际二进制治理；测试策略见 [下一门方案](<../../scripts/runtime/session_v2/NEXT-GATE.md>)。R1 的 Linux guest probe 不等于该 Wine baseline。

## P1：已有观察与未完成门

A 首版独立复核证据绑定旧版本：[首轮 full 证据核验](<../../logs/round1-v2/review/review-20261028T102002/a-first-full-evidence-check.json>)记录 1000 帧的接收/终态 ACK 和自有 view 捕获配对；30 秒 900 输入为 896 displayed、4 replaced。首版 full 整体 exit 1，overflow、generation、duplicate 三个测试在发送时 BrokenPipe；host ERROR 证据与 harness 失败同时保留。该组测量只说明当时 host-only 版本的行为，不是修订 binary 的新测量，也不是 Wine/GDI、真实 guest 或屏幕合成器结果。

审查发现原 A 治理的 orphan 与身份登记缺口；适配 P0 后，独立 Governance/Wire 5/5 只是受测子集，不能等同完整 P0 合同。最终 [presenter binary](<../../logs/p1-a-copy-v2/run-4e2a63efe2f2/presenter>) SHA256 `b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb`，独立定点 9 项 metadata 及真实 producer 死亡 EOF 合计 10/10 PASS，见 [结果](<../../logs/round1-v2/review/a-111830/results.json>)和[交付补记](<../../sources/p1-a-copy-v2/DELIVERY-ADDENDUM.md>)。新版本未复跑 1000 帧/30 秒，完整 outer watchdog 未实现，旧收据固定 `outer_timeout:false` 不证明监督通过。真实 Linux guest producer 通过实际 stream 传送 payload/ACK 仍 NOT_RUN，P2 不开放。

C 的 SDK 静态证据显示 vCPU create 属当前线程，run/destroy 属 owning thread；源码还涉及 normal 与 fork-child 入口、exec 交接及 teardown。C1 未运行，继续探索的前提是 A 真实传输实证成为瓶颈或 P2 有同进程能力需求，而非仅凭理论零拷贝。旧 C 本身包含 memcpy，不可宣称全链零拷贝。见 [C 决策](<../../sources/p1-c-decoupled-v2/DECISION.md#L11-L35>)。

## R1：观测、根因边界与未测

原 runtime 使用增强 ELF 的九个 guest 4 KiB 案例中，fixed 与 remap 两项 target/runner 均 exit 1，邻 lane 0 而预期 119；两 runtime 呈相同症状。`file=false` 合并全文件与 shared alias 断言，原始数据尚未定位首个不同字节，**不能单独据此声称磁盘污染**。[独立复跑结果](<../../logs/round1-v2/review/review-20261028T102002/r1-independent-guest/results.json>)再次得到原 runtime 两项失败；[原始收据](<../../logs/r1-cow-matrix-v2/review-guest-20261028T105722-8bcfbf/receipt.json>)列预算、退出、SHA 与治理。

fork-private 旧 probe 的子进程写入缺直接证据；增强 probe 增加 child readback，C 派生补测 PASS，旧结果不追认。host 16 KiB 对照的 4 KiB fixed/protect/remap 有对齐 UNSUPPORTED，不能当 guest 结果。Windows section/WRITECOPY、fault enforcement、并发 race、生产修复与无诊断 Wine 回归仍未测。细节与限制见 [R1 诊断](<../../sources/r1-cow-matrix-v2/DIAGNOSIS.md>)。

## S1：三环节证据分层

- **发现/启动：** macOS 样本含兼容工具路径、VDF 字段和启动字符串；实际扫描分支、平台 token、GUI 可见性与 wrapper 调用未测。
- **内容获取：** 官方资料明确 depot 挂载规则，样本含 `download_depot` 字符串；注册、许可、目标 Windows depot 和客户端安装认可未测。
- **登录态/Steamworks：** 文档说明客户端、AppID、同用户与许可等初始化条件；实际 Windows→ELF→macOS 桥接、IPC 与回调未测。AppID 或静态字符串不是登录态证据。

独立 [S1 验证日志](<../../logs/round1-v2/review/review-20261028T102002/s1-verification.log>)复核封存样本；覆盖与样本身份见 [S1 报告](<../../sources/s1-steam-offline-v2/task-6/README.md>)。不存在凭静态结果证明整体可用或整体不可行的依据。

## 完整性与收口边界

[初始冻结](<../../logs/round1-v2/coordination/baseline-freeze.json>)包含 56 项；[独立初次复核](<../../logs/round1-v2/review/review-20261028T102002/baseline-recheck.json>)记录 56/56 SHA 匹配，[Lead 期末复核](<../../logs/round1-v2/coordination/final-baseline-check.json>)和[独立期末复核](<../../logs/round1-v2/review/review-20261028T102002/baseline-final.json>)均为 56 项、零差异。结论限定列项与各自检查时间，不追认历史运行期间无干预。旧证据、旧 runner、runtime/Wine、真实 Steam、系统与全局包均保持原范围；本报告不宣称游戏、GPU、WSI、真实 Steam 或生产驱动已完成。
