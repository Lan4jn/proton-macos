# 有界I/O等待身份观测（round23/task65）

## 实现
独立sources/elfuse-io-observe-derived从60诊断版clone，仅io.c增加ELFUSE_IO_WAIT_OBSERVE gate、>=2000ms阈值和每process image最多32条记录。io_xfer在唯一wait调用前设置TLS gfd/want，返回后清空；无context直接wait记录gfd=-1/want0。记录hostPID/TID、events、字节数、fstat类型/dev/inode/F_GETFL；socket支持时尝试LOCAL_PEERPID。没有通信payload/路径，未改poll或I/O返回值。helper保errno，clock/getenv在wait入口及循环有扰动，fork继承计数、exec重置，非全树32行；额外write到stderr也有观测副作用。

build.log只编io.c、link/sign成功；运行时SHA19040d51a315838d669ba4890b6c253a2115168a88ec3a16e27e0e60a9db8108，patch在logs/io-wait-identity/observer.patch。该版本继承故意PRIVATE→SHARED诊断gate，仍非正确COW实现，不接后端。

## 控制
control.json/run-3df3p4p5：2.508981s/0/target0/noTimeout/cleanup[]，PIPE_WAIT_CONTROL_OK。guest Python线程延迟2.3s后写一个字节，read正常返回；日志2011ms、gfd3/POLLIN/want1/FIFO，验证阈值和context字段，不证明全I/O ABI正确。

## 一次真实Vulkan
独立新prefix，null graphics、shared别名gate开、无GDB/全量verbose；vulkan/receipt.json/run-l7pogh62：55.121101s/124/targetnull/timeout/cleanup[]，0 session mismatch，仍Step3未返回，stderr24981B。

34条观测均events0x1(POLLIN)、mode0x1000(FIFO/pipe)、hostflags0x4(host nonblocking)；33条want16，一条直接调用context未知(gfd-1/want0)。来自多PID/TID，不能把每条后台等待都算目标主线程故障；同pipe的重复记录也不是持续同一个wait的证明。pipe没有socket LOCAL_PEERPID，本次peerpid=-1不等于无对端。

官方日期候选Wine dc26e618的dlls/ntdll/unix/server.c原文保存wine-ntdll-server.c.txt：363-367以struct wake_up_reply在wait_fd[0]上read(sizeof reply)，259另有reply_fd读。其机制是候选解释，实际fd尚未绑定到该Wine字段或guest调用PC，不能仅凭16字节当确定请求。

## 下一步
先从精确pipe创建/SCM_RIGHTS传递与线程wait字段建立对端关系，或在guest调试停机不依赖host I/O合作的观测点保留PC/调用返回地址。重点区分正常服务线程wait与主Vulkan进程等待；不能从34条pipe wait推出pipe传输丢失或WineServer死锁，不修改I/O语义、不再盲加Vulkan参数。

当前团队proton-integration-worker恢复task ready失败未claim，Lead只此单文件诊断兜底，无新会话/临时subagent/Steam/global/commit/push。独立复验未完成，总目标active。
