# 有界流式身份观测与实际PE采样（round28）

## 红绿验证
check_stream_identity_live.py对冻结ef7cd2a8运行7个预期用例：dup/writev/split三项明确失败，其余plain/unrelated/other_object/split_other符合预期，记录logs/pe-identity-stream-red/matrix.json及stream-red.log。

新独立sources/elfuse-stream-identity-derived仅相对ef7版io.c、syscall.c不同。共享scanner给scalar与vector入口；比较已pin hostfd与native stdout的dev/inode/type，覆盖dup；TLS跨iov/跨调用保留进度，非同输出对象调用重置；每host thread/process image最多扫描65536B，process image只emit一次固定metadata。开启envgate后所有SYS_write走现有slow_path，因此有可测路径/时序扰动，不声称完全被动；stdout fd复用、跨线程交错及host inode复用未全面验收。

七项真实guest控制全部通过（均目标0、noTimeout/cleanup[]），logs/pe-identity-stream-green/matrix.json；1个脚本7case，不包装成完整协议测试。诊断binary SHA4c6273c7c38676e97e34cdaa71cbbd1a314f4f6c89ff907208c54b31bdb802cd。原accepted06摘要重新核对不变；变化范围和patch在logs/pe-identity-stream/integrity.json、{io.c,syscall.c}.patch。

## 实际绑定成功
唯一新prefix/null驱动/shared别名gate开、无GDB的run，receipt logs/pe-identity-stream/vulkan/receipt.json；精确run路径以收据result.run_dir为准。

实际stderr84行：FIXTURE_STEP3_IDENTITY pid34442 ppid34441 gtid1 gfd10 nvec1 phase=write_request。
85行：Wine trace:vulkan:vkCreateInstance进入。
stdout有完整同一固定探针标记。由此固定fixture进程与hostPID直接绑定；不是靠pid顺序或root猜测。gfd10解释前版fd1限定为何对Wine漏检（不再把writev/分片候选说成已证的实际原因）。

本run绑定PID恰等于wrapper root34442，先前round24“尚未绑定”保持为当时正确未知；不能从早期启动read16及root相同就倒推启动时与调用时等待相同。

## 有效采样
对标记PID验证proc_pidpath为当前诊断runtime、与本run进程组一致、有限ancestry可达root、start身份前后不变。sample1秒/10ms exit0，88主线程样本全为syscall_dispatch→io_xfer→io_wait_fd_timed_or_interrupted→host poll。无guest PC栈，不把host poll直接符号化为Wine某函数。原件pe-native-sample.txt。

当前可支持：在Step3、实际null驱动出现后，已绑定Vulkan探针进程的主宿主执行线程处于I/O等待。该层现在不再存在未绑定PE的身份缺口。具体本次等哪个fd/读写方向仍未知：本run只有标记前的root IO_WAIT_OBS，marker后没有新阈值记录；不能复制前次read16字段当作当前等待。

目标最终55.122168s/overall124/targetnull/timeout/cleanup[]、0session mismatch，仍无vkCreateInstance返回。root与PE同PID不等之前采样已完成归属证明，证据需按时序保留。

## 下一步
在固定fixture命中后显式激活per-thread I/O wait诊断，且共享明确单调时钟；对后续的wait每2s有限重报状态和ELR/LR，区分同一wait延续与新wait。捕获pipe endpoint关系或guest模块位置后再修，不继续猜Vulkan参数。

此scanner仅诊断，不接默认backend；继承故意PRIVATE→SHARED干预，COW仍未正确实现。工具目录当前缺teammate接口，不另建执行会话/临时子代理，独立复核仍待完成；真实Steam/global未改、无commit/push，总目标active。
