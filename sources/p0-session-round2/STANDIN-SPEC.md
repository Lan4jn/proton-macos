# P0 全链路 host stand-in 修正规格（待 reviewer 审核）

## 背景
先前将真正的 guest probe 在 host 本机执行，`setsid()` 改变 host PGID，因此 POST 实际逃离登记组；本次是错误的 stand-in 模型。原 [P0 receipt](<../../logs/session-v2-round2/full-dc724d303de84fc4b09f7117af1edb72/receipt.json>) 与 [observer](<../../logs/session-v2-round2/full-dc724d303de84fc4b09f7117af1edb72/work/observer.json>) 保留，已登记外 PID 58691 经只读 ps 证实不存在；该轮无 sentinel，不能推断 sentinel 保护。

## 修正设计
- 新建 host-only 模拟器：一个普通进程 fork 一个普通 child；明确禁止调用 setsid、setpgid、daemon、exec 和创建新会话；生成受控合成 guest 数字身份，而不调用真实 syscall。child 的 pre/post 显示假 guest SID/PGID 变化，宿主 PID 树仍用实时 `/bin/ps` 采样。PRE/POST ACK 仍使用随机 token 与分阶段有限截止；退出由父 waitpid 回收。
- 正常 case 仅判定 host 链路/屏障和监督行为；模拟 guest setsid 的结果只标 SIMULATED，不据此断言真实 guest setsid 已发生。worker→observer→stand-in parent→stand-in child 精确4链由 PPID 关联；多出或缺失候选、身份变化、guest token 不符为 UNKNOWN；host 组改变记录 UNKNOWN 并中止，不向未知组发信号。
- 复用已冻结 P0 的完整 parent，通过 bootstrap 显式重定向 round2 日志，普通 Popen 启动 observer 和模拟器。fixture 特例 `--fixture-short-outer` 只用于外层强制卡死，inner20/outer3；P0超时后负责组清理。正常链 inner20/outer30。
- 两组均由测试控制一个独立 sentinel，不与被测组共组；父测试先启动 sentinel，检查运行后存活并由创建者 wait 回收，即使异常亦执行 finally。残留复核限定原快照各 PID/lstart 和 P0 登记的组身份，不扫描名字或给未知对象发信号。
- 固定负测使用纯数据篡改：将 POST 快照的模拟 child PGID 改为不同值，评估器必须返回 UNKNOWN；不得在 host 真执行 setsid 制造负测。模拟器源码在运行前静态核无任何 setsid/setpgid 调用，并可由 reviewer独立核验。

## 门
先请 reviewer 审查以上设计，再写或运行修正 stand-in；完成后须测试/证据和独立复核，才能申请真实 guest 6 场景锁。真实 guest probe 的 setsid 本身仅在持锁之后通过 ELF runtime 运行；如果 host 逃逸，留身份证据并停止，不扩大清理或宣称覆盖。
