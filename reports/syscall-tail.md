# 固定探针线程的syscall尾部定位（round31）

独立sources/elfuse-syscall-tail-derived从69dff2bf只放宽dispatcher诊断选择到全部syscall，per-thread上限4096，仍只固定Step3命中的线程，无全量verbose。保留IO_TX标签只是日志格式沿用；现在fd字段实际上是通用x0，非所有syscall都表示fd，arg2是原始x2（在sendmsg/recvmsg是flags）。不能按字段名误读futex地址。

控制新增clock_nanosleep115进入/返回，目标0/0.252139s/noTimeout/cleanup[]，证明原三类之外可覆盖。binary SHAcc08360450a6d2a3bd9f5730e54738224fe52ed328782aa8fe7ffa18d7a6d276，logs/syscall-tail/control.json。

## 实际唯一运行
vulkan/receipt.json：pid52883/gtid1，id0..855共856entry；4096cap未耗尽，stderr165582B。前855个调用返回，唯一未配对entry为id855 nr98 x0=8606897216 x2=1，HV参数读取均状态0。

已查runtime src/syscall/abi.h95：SYS_futex=98；syscall.c462适配x0=uaddr、x1=op、x2=val、x3=timeout/val2、x4=uaddr2、x5=val3。**当前日志没有记录x1/x3，不能声称已知WAIT/PRIVATE或超时模式。** x0十进制地址不是fd，保持其原始值以便下一轮核对。

尾部id852 writev66返回148、id853 read63(fd6,count64)返回64、id854 rt_sigprocmask135返回0，随后进入futex98直到截止无return。足以把本次末端未返回边界定位到futex，而非先前pipe read。

外层55.107340s/overall124/targetnull/timed_out=true/cleanup[]，0session mismatch、vkCreateInstance仍未返回。截止由runner触发，不是futex内生超时判定。没有entry单调时间字段，不能精确量化该futex实际等了几秒。

## 下一步
对固定thread的futex98 metadata补x1完整op/x3timeout指针及受限timespec/x4地址/x5、uaddr当前uint32和ELR/LR、已知映射对象身份；同guest进程各线程/关联进程上记录仅匹配地址或共享对象的WAKE请求，区分private共享键、expected值与lost-wake。先真实futex WAIT/WAKE控制与超时/EAGAIN，再唯一Wine。不能仅凭未返回就判elfuse futex bug，也可能是Wine内部pthread_once/锁或对端没有发wake。

诊断版本仍继承PRIVATE→SHARED试验，不是正确COW，不接默认backend。原Proton/accepted runtime/真实Steam/global未改、无commit/push；工具无团队接口，不用临时subagent绕过，独立复核仍缺。总目标active。
