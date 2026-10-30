# 探针进程身份观测覆盖检查（round25–26 / task67）

## 实现与控制
独立sources/elfuse-pe-identity-derived从01129827复制。io.c仅在env ELFUSE_FIXTURE_IDENTITY存在、guest fd1、单次<=4096B写缓冲中精确匹配固定fixture Step3标记，输出PID/PPID/gtid/phase=write_request，不记录其它载荷。

初版440d1af2...控制退出0、stdout存在标记但metadata缺失。源码定位syscall.c2640起有read/write快速路径绕过sys_write。保留control-fastpath-negative.json及原run，不把阴性写成功。两个前置shell序列化SyntaxError均发生在guest前，无目标副作用。

修正仅在env开且SYS_write fd1时跳现有slow_path；此时源码差异扩展为io.c+syscall.c，不再声称单文件或无路径扰动。build-gated.log构建成功，binary ef7cd2a8e9ef2f716a0336191f3000163c450042baa5e1041b14a75555ff49dc。

修正后control.json/run-r_n04bc9：0.186487s、overall0/target0、noTimeout/cleanup[]，恰一条FIXTURE_STEP3_IDENTITY pid28700/gtid1，控制基本覆盖通过。

## 实际Wine：覆盖仍未闭合
vulkan/receipt.json/run-uci2g2xs：唯一新prefix/null driver/shared别名gate开、无GDB；55.103969s、overall124/targetnull/timeout/cleanup[]、0 session mismatch。stdout确有完整Step3，但未出现fixture metadata，故runner没有选PID、没有执行sample，也没有pe-native-sample.txt可供解释。

不能从控制通过推出Wine写入路径也被覆盖。当前实现限fd1和sys_write，Wine可能使用其它fd、writev或拆分写入等路径；实际是哪一种尚未证。不要宣称目标PID已绑定或获得真实PE栈。

## 后续明确门槛
先用小控制覆盖writev、dup stdout及分片边界，或在共同I/O出口按精确fixture字节流做有界识别；只有metadata与实际目标Step3同时成立且PID身份/owned父子链核对通过后，才进行下一次重Wine采样。停止当前相同observer的超时重跑。不扩大日志为全量verbose，也不假设根PID就是PE进程。

本轮团队工具目录已从teammate切换为仅subagent工具，先前当前队员恢复失败；按用户要求没有另开团队执行会话或临时子代理。task67在原共享板尚待补结算，工具恢复后按真实阴性结果完成诊断任务而非标产品完成。报告及收据是当前交接依据。

原Proton/accepted运行时/真实Steam未修改，无global/commit/push。所有实验二进制保留为诊断，PRIVATE→SHARED仍非正确COW实现，总目标保持active。
