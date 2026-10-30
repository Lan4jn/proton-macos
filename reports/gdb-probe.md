# 有界GDB RSP控制与Vulkan采样结果（round21 / task63）

## 新代码及纯测试
scripts/runtime/gdb_probe/rsp.py：仅允许thread list、Hg线程选择、p寄存器、D detach以及原始Ctrl+C；无memory/register写、kill/continue/shell命令。4096字节payload上限、128字节前缀上限、checksum/EOF/deadline检查；不支持escape/RLE则明确报错，不错误解码。单recv至多2s，整个capture有独立deadline；不代表网络/所有RSP实现通用客户端。

test_rsp.py七个纯socketpair测试实跑7 PASS，日志logs/gdb-probe/unit-tests.log。测试包含分帧、错误校验、EOF、前缀/长度界限、不允许写命令与deadline；没有声称完整协议测试。

## 真实guest控制
任务最初描述sleep控制；实际改为3秒monotonic busy loop，因为host nanosleep阻塞会混淆vCPU interrupt能力。冻结06runtime原GDB stub、仅loopback临时端口，不用系统attach或全局调试权限。

logs/gdb-probe/control/receipt.json/run-63j2q5fu：3.199993s/overall0/target0/noTimeout/cleanup[]。运行中CtrlC返回T05，thread1，pc0x2007e5094/sp0x7fff0e0/fp0x7fff0e0/lr0x2001a981c；detach OK后出现GDB_CONTROL_DONE并正常退出。该控制验证target可运行时的基本stub及客户端配合，不等Wine复杂状态可暂停。

## 真实Vulkan单次采样
60f87660诊断binary，shared别名gate开、null graphics driver、新COWprefix，原PE与ICD未改；--gdb端口仅本次loopback。

条件是目标stdout Step3 vkCreateInstance已出现且explorer using null driver已出现，满足后一次连接/中断，不重试。日志确认GDB client connected（stderr100行），两秒后断开（137行）；客户端receive发生socket timeout，没有T/S停止回复，故没有PC/线程寄存器。raw receipt：logs/gdb-probe/vulkan/receipt.json/run-txvn2_86。

最终outer70.123198s/overall124/targetnull/timed_out=true/cleanup[]、0 session mismatch，仍没有实例返回。断开后stub是否有未消费的stop_requested属于观测副作用边界；本次结果不用于证明超时是调试前后完全等价，也不把无PC说成已捕获等待栈。

## 下一诊断
GDB失败可能来自host syscall/锁阻塞、stub停机协作限制或其它时序；没有足够证据选一个。停止同样的GDB重试，下一步对精确本次supervisor的直接target进程（核对PID/path/parent/start identity）做有限原生sample线程栈，观察host syscall与gdb监听线程。只采项目owned进程，不全系统枚举、不附加不相关进程；权限失败保留错误，不改全局权限。

当前团队steam-probe-worker恢复无closing失败，未claim或产出，Lead就有限调试客户端/控制兜底；缺独立审查。原Proton/Wine/accepted runtime未修改，无真实Steam/global/commit/push。
