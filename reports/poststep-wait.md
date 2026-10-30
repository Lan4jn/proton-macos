# Step3之后同guest线程的等待窗口（round29）

## 红绿控制及范围
原4c6273c7阈值observer对Step3之后0.3s pipe read控制正常exit0但无POSTSTEP_WAIT_ENTRY，预期断言失败，logs/poststep-wait-red/receipt.json保留。说明阈值-only遗漏短等待，不直接认定原wait实现错误。

独立sources/elfuse-poststep-derived仅io.c增加TLS fixture_step3_seen和最多16个等待入口metadata；仅固定marker命中本线程后启用，不扩展到其它线程。相同control绿色，管道read1 metadata已出现、目标0。新binary SHA1676a04c6a6db0b71514c4d79f17218cc594e4fc52d52a1a2430ac3e29265ad5；开启时额外HV读/fstat/write有调度扰动。metadata是wait入口，不是读写完成或返回计数。

## 实际同线程窗口
logs/poststep-wait/vulkan.json：固定标记pid42288/gtid1/gfd10。紧接目标进入vkCreateInstance，整个本次标记后最多16条POSTSTEP_WAIT_ENTRY均同pid/gtid。

- 14条syscall63(read)，gfd6/hfd52、POLLIN、want64、FIFO/type0x1000，inode14188339967350296774。
- 第9号syscall212(recvmsg)、hostfd50、POLLIN、socket/type0xc000，inode59717；这一路无io_xfer TLS context，因此gfd=-1/want0代表未知，绝不是guest fd-1。
- 第15号syscall211(sendmsg)、相同host socket、POLLOUT。
- HV读取ELR0x2000c5094/LR0x2000c50b8状态0；重复相同地址不能擅自符号化为read上层函数或完整guest PC栈。

不同syscall间交错，支持有多次I/O wait入口，不等同单次read63持续阻塞；read64也不能倒套启动read16/wake_up_reply路径。Wine client reply_fd read是静态候选，需要返回配对/上层调用点证明。

实际外层55.123689s/overall124/targetnull/timeout/cleanup[]，0session mismatch，目标仍Step3未返回。16条cap已耗尽，因此本窗口不是整个后续55秒完整轨迹，也不提供每次等待时长或返回码。不能从短窗口推断所有消息循环或无穷重试。

## 下一步
为固定线程的前有限N个read63/sendmsg211/recvmsg212添加事务编号与入口/返回metadata，记录native elapsed/returned byte count及错误，不采集通信载荷。配对要覆盖scalar fast dispatch路径与slow handler，避免同一调用重复计数，并限制输出量。先小控制包括短读、EOF、EAGAIN与socket收发，再唯一Wine。确认请求在推进还是返回错误重试以后才设计ABI修复。

工具仍无当前team派发接口，未用临时subagent/新会话绕过。原Proton/accepted runtime/真实Steam/global未动，无commit/push。版本继承PRIVATE→SHARED诊断干预，不是COW实现或产品运行时；独立复核和整个目标仍未完成。
