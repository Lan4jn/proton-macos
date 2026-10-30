# 第一轮执行任务书

用户本轮批准执行 P0、P1 架构验证、R1 矩阵与 S1 离线核查；原路线图保持冻结，不回写“待确认”标题。

## 冻结与隔离

基线为 [PROJECT-STATUS](../PROJECT-STATUS.md) 和 [开发计划 v2](../DEVELOPMENT-PLAN-v2.md)。初始冻结见 [baseline-freeze.json](../../logs/round1-v2/coordination/baseline-freeze.json)：历史清单 53 项加状态、计划、清单自身共 56 项，初核零缺失、零既有 SHA 不匹配。只读引用并前后校验 SHA，不 chmod 或改写原产物、prefix、旧证据。

工作目录没有 Git 元数据（只读检测 exit 128），按任务新目录隔离，不创建 Git 仓库或提交。初始花名册只有 Lead，无可复用执行员，已建立六名可持续复用成员。

## 任务及写范围

| 看板 | 队员 | 目标/边界 | 独立写范围 |
|---|---|---|---|
| task-1 | lead | 任务书、冻结、门判定 | `reports/round1-v2/`、`logs/round1-v2/coordination/` |
| task-2 | session-worker | P0 新入口，不改旧 runner | `scripts/runtime/session_v2/`、`tests/session_v2/`、`logs/session-v2/` |
| task-3 | present-a-worker | A-copy AppKit + stream payload 架构验证 | `sources/p1-a-copy-v2/`、`scripts/p1_a_copy_v2/`、`tests/p1_a_copy_v2/`、`logs/p1-a-copy-v2/` |
| task-4 | present-c-worker | C-decoupled HVF 线程约束及有界验证 | `sources/p1-c-decoupled-v2/`、`scripts/p1_c_decoupled_v2/`、`tests/p1_c_decoupled_v2/`、`logs/p1-c-decoupled-v2/` |
| task-5 | cow-worker | 正常 COW 最小矩阵，不开生产修复 | `sources/r1-cow-matrix-v2/`、`scripts/r1_cow_matrix_v2/`、`tests/r1_cow_matrix_v2/`、`logs/r1-cow-matrix-v2/` |
| task-6 | steam-worker | 三环节资料与离线样本 | `sources/s1-steam-offline-v2/`、`scripts/s1_steam_offline_v2/`、`logs/s1-steam-offline-v2/` |
| task-7 | reviewer | 独立规格、质量与关键复跑，不代改执行代码 | `logs/round1-v2/review/` |

## 规格与门依赖

各任务先 get→claim，最小规格经 Lead 确认后实施，先失败测试后实现。实现者 completed 不等于阶段通过；必须独立规格审查，再质量/关键复跑，最后 Lead 接受。

1. **P0 治理子门**：唯一 run-id、已有目录拒绝；owned PID/PGID；sentinel 存活；正常/内外 timeout/异常仅清理本 session；target/runner exit 分列。reviewer 通过才放行 guest runtime 实跑。P1 host-only 在独立自有治理自测后可运行；静态分析、构建及 host POSIX 对照可并行。
2. **P0 基线门**：同 PE/负载/预算，原 runtime 与 C 派生无 opt-in 对照；模块 SHA、prefix、配置、cleanup 记录于新收据。
3. **P1 决策门**：1000 变化帧 CRC/sequence/唯一 terminal ACK；真实 RGBA8 payload 与 view 像素检验；至少 30 秒 720p30，首帧与稳态分位分报；latest-frame-wins 替换序号；producer 三秒纯算期间预排 AppKit 事件/关闭真正响应；断连、单端退出有界。选择达标且改动较小的后端。CPU producer 仅证明传输架构，不等于 Wine/GDI 完成。
4. **R1 门**：九组 backing/shared/private/邻页/MAP_FIXED/mprotect/thread/fork/unmap-remap，host 16K 对照与 guest 4K 分列；file/sibling/邻 lane 分别断言。MAP_PRIVATE 仅为 Windows WRITECOPY 机制代理；unsupported/FAIL/NOT_RUN 分列，真实正常 COW 未全部通过前不开放可靠性验收。
5. **S1 门**：客户端发现/启动、Windows 内容获取、登录态/Steamworks/参数分别给出一手证据、版本、样本 SHA；证实/推断/待动态分列。下一动态实验只设计，不执行客户端、不登录、不读取个人 Steam 配置。

## P1 共用 frame/ACK v1

A worker 落盘协议，C 沿用语义。`u32be total_length + u32be json_length + UTF8 JSON + payload`，先检查上限再分配。版本 1；surface/generation/sequence、RGBA8/尺寸/pitch/长度/CRC；host-owned slots。RECEIVED 只确认接收与所有权；每帧唯一 CONSUMED terminal，disposition 为 displayed/replaced/invalidated，只有 displayed 计显示。READING 不覆写，generation 使旧帧失效；控制 ACK 与帧 terminal 区分。跨 clock 一程延迟不推算。

## 首轮规格审查补充

- C-decoupled 本轮批准只封存 SDK/源码线程约束与成本分析，不实现 C1。结论限定 `DEFERRED_NOT_SELECTED`；真实新线程/fork/exec/teardown 可行性 `NOT_RUN`，不等于平台不可行。
- A-copy host-only 通过仅为 AppKit/协议子门。整体 P1 transport 必须另有真实 Linux guest producer 经实际 SOCK_STREAM 发送 RGBA8/ACK 的证据；P0 放行前不执行。成本过大则保留 `NOT_READY`，不将 host producer 结果外推 P2。

## 停止线

不修改真实 Steam、系统或全局包，不 commit/push；不重放旧 killall 入口，不覆盖已有 run，不迁移 HVF vCPU 线程。每同假设最多两轮。P2/P3/P4/G1/G2 不在本轮实施范围；门未通过则保留 FAIL/NOT_RUN、归因与成本，不自动推进。
