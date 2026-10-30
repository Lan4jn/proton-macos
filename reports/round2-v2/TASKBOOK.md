# 第二轮任务书：P0 与 A-copy 门控

**目标：** 在独立审查和受控 guest 串行前提下，补齐 P0 会话治理与 A-copy 监督缺口；按实际证据决定下一步，暂不进入 P2。本文是协调任务书，不是任何门的通过收据。

## 基线与范围

[第一轮结果](../round1-v2/RESULTS.md)：整体 PARTIAL、P1 NOT_READY；P0 仅 fixture 治理子门通过，Wine 同 PE 对照未运行；A 的最终版本仅定点复核，完整 outer watchdog、最终 binary 全套及真实 guest producer 未验证。C 为 DEFERRED_NOT_SELECTED、C1 NOT_RUN；R1 可靠性 FAIL；S1 动态 NOT_RUN。这些状态不会因本任务书改变。

第一轮只读，不覆盖旧报告、源码、binary、日志或冻结证据。独立 reviewer 的 [初始冻结](../../logs/round2-v2/review/initial-freeze.json)记录 69 个唯一路径、69 匹配，SHA256 `c4a2508ce6cee2ab71c0bdef7edd14ba5a5bf99ef64d269718aef9366101319e`；[A 声明输入](../../logs/round2-v2/review/initial-freeze-a-inputs.json)另四项匹配，SHA256 `4813bf69ab367856042f23b2a19a324d35e44a9b5c15347810d07ba4f406e4ac`。两清单合计 73 个独立路径，结论仅限清单与检查时点；[Zig 补录](../../logs/round2-v2/review/initial-freeze-zig.json) SHA256 `3891fde889d447bda30540d731e5843370b7f61e5d0e7ad4628091557f71371a`，仅核版本 0.16.0 与可执行文件，标准库、sysroot 和 SDK 依赖未冻结；后续发现的新输入须补录，当前不称全部派生输入已冻结。旧 probe 只作参考，不作为第二轮执行入口。期末由 reviewer 对列项及新增声明输入重新核验，差异须显式报告。

第二轮写范围：P0 为 `scripts/runtime/session_v2_round2/`、`tests/session_v2_round2/`、`sources/p0-session-round2/`、`logs/session-v2-round2/`；A 为 `sources/p1-a-copy-round2/`、`scripts/p1_a_copy_round2/`、`tests/p1_a_copy_round2/`、`logs/p1-a-copy-round2/`；review 为 `logs/round2-v2/review/`；协调为 `reports/round2-v2/`、`logs/round2-v2/coordination/`。仅新建唯一 run 目录；禁止裸 killall、未知 PID 清理、修改真实 Steam/系统/全局包、commit/push。R1/C 实现、S1 真实操作与 P2 不展开。

## 依赖与放行

**所有 guest 实跑串行：Lead 管理唯一 guest 锁。** 执行者先向 Lead 请求并取得具体场景许可；完成清理及归还锁后才能放行下一个 guest。fixture 或 host-only 是否占锁由 Lead 按实际涉及资源决定；不得把 guest 锁当其他安全门的替代。

### P0 链（task-9）

1. **guest setsid 治理规格 → Lead 批准 → 受控实验 → 独立 review。** 在新目录使用静态 Linux ARM64 fork/setsid 双屏障 probe，分别对完整 SHA 身份的原 runtime 与 C 派生 runtime，记录 guest PID/PGID/SID 与 host owned PID/PGID 映射及其证据强度；验证退出、timeout、异常三路，记录清理对象与结果、无关 sentinel 存活。host 成员逃逸、映射不足或清理不确定即停止本门，不对未知进程发信号。
2. **Wine foreground adapter 规格 → Lead 批准 → 实施及独立 review。** 仅在第 1 门独立 review 通过且 Lead 放行后；验证 owned launcher、foreground server 真实就绪、fallback 不产生未经治理 daemon、新 prefix/环境/链接审计，以及异常和清理。细节以 [下一门设计](../../scripts/runtime/session_v2/NEXT-GATE.md) 和获批第二轮规格为准；fixture 成功不是 Wine 实跑成功。
3. **同 PE 对照。** 仅在第 2 门独立 review 通过、Lead 放行并取得 guest 锁后，原 runtime 与 C 派生 runtime 使用同一个 PE、Wine、预算和无 opt-in 条件，各记录完整模块 SHA、配置、target 与 runner exit、内外 timeout、原始输出、受治理清理。结果单独判读，不把启动总时长当性能结论。

### A 链（task-10）

1. **独立 outer watchdog 治理规格 → Lead 批准 → 实施及独立 review。** 新派生目录，先测独立 outer watchdog、有界 send/read、半包、永不 ACK、producer/host 异常、无关 sentinel 和 owned 清理；分别记录 target、runner、outer 结果和超时，不以固定字段或局部子集替代完整治理。
2. **最终 binary 新 SHA 完整 host 回归 → 独立 review。** 第 1 门 review 通过且 Lead 放行后，用同一个最终 binary 完整 SHA 绑定 1000 变化帧 CRC/view/唯一 terminal、30 秒 720p30、latest/resize、三秒 busy 期间预安排 UI/关闭事件、断连和清理；记录分布、队列与 replacements。旧 binary 的性能与结果不可移植到新 SHA。自有 view 捕获不代表桌面合成器或无遮挡显示。
3. **真实 guest producer。** 仅在第 2 门 review 通过后提交独立规格、成本及范围，获得 Lead 明确批准并取得 guest 锁才运行；真实 payload/ACK 与 host-only 分层记账，不自动开放 P2。

P0 与 A 的非 guest 工作可并行；上列每条链内 review 和 Lead 放行不可跳级。每个相同假设最多两轮，若无新增证据停止扩 probe 并上报。

## 验收与后续汇总

各 worker 输出独立 run-id、精确命令与预算、证据路径与 SHA、实际退出/超时、负测、失败和清理记录；reviewer 先核规格后核质量与必要独立负测。任何门未运行记 NOT_RUN，未通过记实际状态；禁止以静态设计、部分测试或旧 binary 结果写全门 PASS。Lead 决定接受与放行。

本任务后续依据实际验收和最终冻结复核撰写 `reports/round2-v2/RESULTS.md`；当前不创建预设通过的结果。task-12 保持 in_progress，待各门和最终汇总有证据后收口。
