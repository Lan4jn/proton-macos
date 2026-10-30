# Step3后I/O进入返回配对（round30）

独立sources/elfuse-transaction-derived从1676a04c复制，io.c暴露TLS标记布尔，syscall.c在共同dispatch边界记录选定read63/sendmsg211/recvmsg212的entry和fast_done返回，覆盖fast/slow路径。最多128事务/线程，额外<=256行；不采payload、不改result/寄存器。getenv/clock/write有调度扰动，phase不是无侵入性能剖析。

首build因-Wmissing-prototypes失败，补显式函数原型后build-fixed.log通过。binary SHA69dff2bf9c931978185a243434ccd48f92f561ceefa46f4eb5a7ebcceb8b670f。

## 控制
control.py真实guest验证read短读1、EOF0、EAGAIN-11，sendmsg1、recvmsg1，五对entry/return完整；0.192624s/0/noTimeout/cleanup[]。这是一个有限控制脚本5行为，不声称完整ABI回归。原始control.json。

## 一次实际Wine
vulkan/receipt.json对应run结果：55.119645s/overall124/targetnull/timeout/cleanup[]、0 session mismatch、仍vkCreateInstance无返回。

同固定标记线程共95个selected transactions，低于128cap，全部entry/return配对。read返回均正数（64共41次，832共28次，另有14/16/30/96/220/618/629/834等），recvmsg返回4一次，sendmsg返回8一次；没有selected负返回或EOF。最大耗时1590419us。

由此推翻“当前采样window中某次read/sendmsg/recvmsg持续不返回”的充分解释。反复read64并非仅entry虚假进度，本次有实际返回字节数。但95次之后仍可能进入其它syscall、guest循环、signal epilogue或另一未覆盖函数；不能由open_pairs=[]得出目标无任何阻塞/全部IPC正确。

## 下一步
记录固定fixture线程所有syscall的最后进入/返回状态，不只三类；有界环形缓冲或只保存当前inflight及累计计数，以在截止前取得最后一个没有返回的call/guest状态，禁止全量verbose。之前GDB运行中stop合作失败，只能在自有诊断实现加观测，先证明覆盖尾部再猜根因。

仍是故意PRIVATE→SHARED干预的诊断构建，不是COW实现、不可接默认后端。真实Steam/global未改，无commit/push。当前工具无teammate接口，不另建会话或临时subagent；独立复核未完成，总目标active。
