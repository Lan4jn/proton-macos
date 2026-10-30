# 第二轮 ABI 实测：通过项与缺项分开

## 可重复命令

```sh
bash scripts/abi/build.sh
python3 -m unittest discover -s scripts/abi -v
```

基于原始 elfuse 固定提交；不把真实失败写成 expectedFailure。`logs/continuation-validation/abi.log` 的当前总结果是 **3 PASS、2 FAIL，退出1**。

| 项目 | 实际结果 | 结论 |
|---|---|---|
| 动态 glibc 程序 | `DYNAMIC_GLIBC_OK`、exit0 | AArch64 ELF 经 ld.so、libc 初始化和 puts 实际运行 |
| clone 后 MAP_SHARED | `SHARED_OK`、exit0 | 子进程写入共享匿名页，父进程在 wait4 后可见 |
| signal handler + return | `SIGNAL_OK`、exit0 | rt_sigaction/kill/rt_sigreturn 的最小链通过 |
| 跨进程 futex WAIT/WAKE | `FUTEX_TIMEOUT_DESPITE_SHARED_WRITE`、exit5 | 共享值已更新但 parent waiter 没被另一个进程 wake 唤醒 |
| posix_spawn 不存在文件 | `SPAWN_RETURN=0 CHILD_EXIT=127`、exit9 | Linux glibc 期望同步 ENOENT，当前出现异步 child127 |

源码：`fixtures/abi/{start.S,dynamic_hello.c,shared.c,futex.c,signal.c,spawn_missing.c,syscalls.h}`。动态程序采用自定义 `_start` 调用 `__libc_start_main`，不是只运行 ld.so --help。每次实际执行都有 `logs/abi/run-*` 的独立目录。最小信号测试不证明完整多线程信号语义；共享内存可见不证明跨进程同步完整。

## 与 Wine 的关系

Wine compiled server 搜索优先尝试 `files/bin/wineserver`。原包只有 `files/bin-arm64`，同时 posix_spawn 错误传播缺项导致它在 spawn 返回成功后只看到 child127，未按预期转到环境指定路径。独立派生包的 `bin -> bin-arm64` 让 wineserver 实际启动；这是布局规避，不是 ABI 缺项修复。

跨进程 futex 缺项与 Wine 初始化卡住存在机制关联的可能，但尚未建立因果证明。不能因为同时出现，就把所有 Wine 超时都归因于 futex。

## 后续修复边界

`task-13` 在派生 elfuse 源码范围开展同步语义修复与自检；原始源码仍保留。任何修复必须同时验证超时、信号、零等待者与准确返回值，而不只是让单一 testcase 变绿。修复成功和新回归结果应另外报告，不覆盖本轮原始失败证据。

## 派生补丁最终实测（原始失败仍保留）

`task-13` 已在独立 `sources/elfuse-derived` 交付有限共享 WAIT/WAKE 修复；最终仅修改 `src/core/shim.S` 与 `src/runtime/futex.c`，早期host地址hint已移除。原始二进制futex仍exit5；派生最小futex已转为exit0，Lead独立执行边界套件通过：`logs/lead-round3/futex-suite-final.log`。旧基线7项保持通过，spawn errno传播仍exit9。

独立审查 `reports/abi-independent-review.md` 确认 PRIVATE隔离、两waiter逐个唤醒、超时/EAGAIN和共享WAITV guard。限定支持实验所验证的非负 wake计数、普通共享 WAIT/WAKE；partial bitset、shared WAITV/PI/requeue等显式ENOSYS。负wake计数尚有Linux规范偏差，报告为已知限制；clear_child_tid独立唤醒未与SIGCHLD打断完全隔离，不能仅凭EINTR探针宣称验证完成。性能未测，非PRIVATE调用新增HVC可能有开销。没有将该补丁默认替换原始elfuse或称为完整Linux同步支持。

原版与派生binary的x64PE对照均在FEX模块加载后超时，不足以证明“futex修好即游戏能跑”。后续精确映射分支调查另见task-17。

