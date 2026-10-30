# 下一门：guest session 与 Wine foreground 接入（仅方案）

## A. 精确二进制 fork/setsid → host PGID 对照
1. 新独立probe目录构建静态Linux ARM64 ELF，父输出guest PID/PGID/SID，fork子经pipe先WAIT。
2. 父子都写携带run随机token的阶段行；child调用guest setsid并写返回值/errno、guest PID/PGID/SID，阻塞等父ACK。父以waitpid回收子。禁止其他daemon行为。
3. 使用本runner分别执行完整SHA 81803322…与3b146bbe…，同ELF/空新sysroot/预算。supervisor对owned host PGID快照；结合elfuse公开观测日志的guest PID→host PID映射（先确认真实可用字段），不靠同名扫描映射。若缺映射，probe加受控两阶段同步，让host枚举同PGID/PPID树并用启动次序与token写端关联，仍明确证据强弱。
4. 在child guest setsid前/后各固定ACK屏障采样host PID/PGID/lstart，确认所有host成员仍为owned PGID；退出/内超时/worker异常三路验证sentinel存活和PID无残留。对任一host逃逸立即停止该候选，交还架构决策，不扩成全系统扫描清理。
5. 独立review通过才开放Wine adapter。此方案本轮未实现/未运行。

## B. 最小 foreground Wine adapter
- 同run内两个elfuse调用（wineserver -f与wine PE）由一个host-owned launcher治理，均不start_new_session；新prefix、HOME、TMPDIR全在run内。先精确核shipped wineserver -f行为和build身份。
- 新prefix按已批准方案复制：仅四个bundle内DLL物化为副本，c:相对副本drive_c，z:只指run/work，其余broken保留并清单。复制前后源内容指纹和新副本链接审计入独立receipt。
- 先启动wineserver -f，真实就绪用新prefix唯一server socket且绑定owned runtime PID，不以固定sleep当就绪。失败不启动PE。设置WINESERVER为run内单用途shim，让自动fallback server仍只以-f启动并继承owned PGID；这部分需先fixture TDD，防未就绪竞争产生隐式daemon。
- 无ELFUSE opt-in，设置WINEESYNC=0/WINEFSYNC=0/PROTON_NO_ESYNC=1/PROTON_NO_FSYNC=1/PROTON_NO_NTSYNC=1；明确guest-env与host-env传递规则并封存。
- elfuse20s / supervisor25s / outer30s，原/C各一轮同PE与同Wine。分别记录wine与server target退出、内部超时标识、stdout/stderr、最后阶段、模块SHA和cleanup。不是单纯把启动总耗时作性能比较。
- 若foreground、shim、guest PID映射需要超出P0最小规格，单独任务批准后实施。当前保持NOT_RUN_ADAPTER_PENDING。
