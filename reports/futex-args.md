# 末端 futex 参数与真实控制（round33 / task-68）

## 任务级兜底
首派elfuse-baseline-worker、第一次重派proton-integration-worker、第二次重派proton-darwin-research均claim前失败（后两无closing，首派task ready）。核查task-68 revision1/pending且预期路径全不存在后，仅此任务Lead兜底。task-69三位审查员也执行前失败，独立审查仍未通过，以下是Lead自检证据而非独立review。

## 变更与控制
从cc083604独立复制sources/elfuse-futex-args-derived。仅syscall.c在现有bounded dispatch observer内对SYS_futex补原始x0..x5、guest_read_small uaddr uint32及ELR/LR，保留读寄存器各状态，不改futex语义/返回。最多受4096事务cap控制，非全进程waker追踪。patch logs/futex-args/syscall.patch。

binary ccdc6732c9d2d1b7b528ae26d2d987fdfd28938abc37fa64646e76579e205535。控制scripts/runtime/futex_args/control.py通过libc.syscall98明确断言EAGAIN、20ms timeout ETIMEDOUT、跨线程WAIT/WAKE（waker返回1、waiter0）；控制0.252175s/target0/noTimeout/cleanup[]，输出FUTEX_CONTROLS_OK。见control.json/run-jnca7bt4。这是一项脚本三行为控制，不是完整futex回归。

注意：第一个EAGAIN调用未出现在FUTEX_ARGS；部分早期dispatcher快捷返回仍可能位于诊断点之前。因此语义控制通过，不等所有futex请求均被观测；waker不同线程且无fixture命中，亦未记录其参数。不能声称已经覆盖waker或跨线程完整关系。

## 实际唯一 Wine
logs/futex-args/vulkan/receipt.json：pid55012/gtid1/id855，uaddr0x20102d440、op0x80、val1、timeout0、当前word1（读取status0），ELR0x2000ce084/LR0x2000ce048（status0）。其它原始x4=uaddr、x5=8605900192只是原始寄存器，在WAIT中无额外语义，不当作地址或证明损坏。sys_futex适配会把val3转uint32。

已核对src/runtime/futex.c61 FUTEX_WAIT0、77 FUTEX_PRIVATE_FLAG0x80：末端为FUTEX_WAIT_PRIVATE且无timeout。expected==snapshot word1支持进入等待的参数合理，但该快照不是atomic compare/enqueue同一瞬间。

前一read64返回64、sigprocmask返回0，随后该futex进入无return直到外层55.119770s/overall124/targetnull/timedout/cleanup[]。0session mismatch，Vulkan仍Step3未返回。无timeout WAIT不应单凭55s无return判handler错误；应找谁负责把word从1改掉并wake，或对应pthread_once/锁对象。

## 下一步
绑定uaddr到guest ELF映射/符号或ELR/LR调用点；观测同进程所有线程对该精确private地址的WAIT/WAKE及线程状态，不扩大为任意payload或全量verbose。先识别该地址所在模块/data锁，而非继续换Vulkan参数。当前尚无lost-wake、锁拥有者、递归初始化证据。

accepted06a2摘要已重新核对不变。原始Proton/真实Steam/global未改，无commit/push。继承故意PRIVATE→SHARED诊断gate，仍不是正确COW或产品后端；目标active。
