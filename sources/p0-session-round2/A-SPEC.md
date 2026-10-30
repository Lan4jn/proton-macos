# task-9 A 段：guest fork/setsid 与 host PGID（待 Lead 审核）

## 目标与方案
仅新 round2 四个目录，不改第一轮模块/证据/sysroot；同一个静态 Linux ARM64 ELF，以固定 SHA 的原 runtime 81803322 与 C 派生 3b146bbe 串行对照。推荐两阶段 token + pipe/FIFO 握手和受控父子树快照：guest child 调 setsid 前后停在屏障；host 同时记录已登记 owned leader 的 PID/PGID/lstart 及后代 PID/PPID/PGID/lstart。不按进程名清理或关联。备选仅静态读源码缺二进制运行证据；系统全局名称扫描没有可靠归属且扩大范围，均不采用。

## 隔离与控制
每 case UUID 唯一目录、新空 sysroot 与可写 /tmp；sysroot 仅复制此 ELF、控制文件，不挂旧 prefix，不继承 opt-in。只读复用第一轮 runner：先核固定 SHA，父进程以 P0 handshake 注册 session leader；所有运行归入该组。P0 固定 log 根的问题先审查可否通过 import-only LOGS 覆写至 round2；不改第一轮源码。一次只启动一组；实际 guest 执行须先向 Lead 获取独占锁。构建和 host fixture 可先做。

## probe 与证据
1. probe 父 fork 一个子；父/子各记录随机 run token、guest PID/PPID/PGID/SID、阶段和 syscall 结果。子进 PRE 屏障等待 host ACK；setsid 返回和 errno 后进入 POST 屏障，再由 host ACK；父 waitpid 并记录子退出。所有等待均设有限时；非成功或 EOF 明确失败。
2. host 在 PRE/POST 各采样完整 owned session leader 与递归 PPID 树（/bin/ps，原始快照保留），包含 PID/PPID/PGID、启动身份 lstart 和状态。仅在对照屏障期间，从已登记 leader 出发，经 PPID 连续边/启动身份及唯一阶段 token 关联候选。若运行时提供确切 guest→host 映射可额外记录；若只有树+token，标记 correlation=bounded_inference，不称 PID 逐一精确映射。
3. 若任一已关联的 host 子进程 PGID 不同于 owned PGID、身份丢失或树关联不唯一：停止该候选并报告 UNKNOWN/FAIL，禁止对未知 PID/组发送信号；仅 P0 已登记且身份匹配组可清理。token 只证明阶段发生，不独立证明对应某个 host PID。观测是屏障时刻快照，不证明整个生命周期不逃逸。
4. 每组 normal、受控内 timeout、受控 worker 异常各一轮；异常由外层 fixture 对已登记、再次核验 identity 的 worker 发一次信号并审计，guest 不主动杀 worker。故障前保存已验证 PPID 树及 PID/lstart，故障后按已知身份只读复核，避免 reparent 遗失关联；清理仍严格限已登记 owned PGID。专用 sentinel 为独立会话，逐次检查存活并由创建者回收。P0 内/外 timeout、target/runner exit、原始阶段日志及SHA、静态 ELF/runtime/P0 SHA、完整命令、环境、sysroot 清单、所有 observed PID、信号与清理结果均写新唯一日志目录。guest watchdog、P0 inner、P0 outer三层区分；失败场景不得误报 target exit。

## TDD 与阶段门
- 先 host-only 负测：屏障缺失/超时、token 不符、未观测 child、ambiguous mapping、模拟 host 逃逸、PID 身份变化、sentinel 活着、重复 run ID 拒绝覆盖；明确不能将空快照算 PASS。先红后实现，fixture 先过。
- 独立 reviewer 审查并复核 fixture 清理后，申请 guest 锁，固定两版本同 ELF/相同预算；各场景受控最多两轮同假设，不追加无新证据探索。锁解除后通知 Lead 和 reviewer。
- reviewer 核原始屏障、树与清理结果并明确通过 A 段后，才提出 Wine foreground adapter 的独立规格；adapter 再独立review与Lead批准后才同 PE 对照。未达门即保留 NOT_RUN/UNKNOWN，不越级。

## 安全与边界
已知 P0 只保证所登记且 identity 匹配的 PGID 清理；host 自行 setsid 逃逸、父监督器 SIGKILL/机器崩溃均不保证治理，禁止自动 kill 未知对象。若逃逸发生，保留身份证据通知 Lead，由其判断处理。无真实 Steam/系统/全局包改动、无 killall、无 commit/push。
