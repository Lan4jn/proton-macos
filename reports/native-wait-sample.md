# 精确owned Vulkan进程的宿主等待栈（round22/task64）

**Round24归属纠正：本报告采样PID是owned启动根，尚未绑定Windows PE/Vulkan所在Wine子进程。后续实测根read16记录早于vkCreateInstance，故不能用该宿主栈认定Vulkan调用线程也在poll。栈本身真实，具体Vulkan因果未证，见io-wait-context.md。**


## 范围与身份
新COWprefix fixtures/runtime/native-wait-sample/pfx，原60f87660诊断binary（共享别名gate开，仍非正确COW），Graphics=null；无GDB、无全量verbose。一次run，条件Step3和explorer using null driver均满足后只sample1秒、10ms间隔，sampler自身最大5秒。

runner logs/native-wait-sample/run_once.py使用一个native shell wrapper记录自身PID后立即exec原elfuse，PID保持；没有改变生产backend代码。sample前后用proc_pidpath和针对单PID的ps核对path/PPID/start，父command精确含本次supervisor脚本；只查询两个相关PID，没有全系统进程枚举。PID27769、PPID27768、start Sat Oct17 13:01:47 2026、path项目独立诊断elfuse，sample前后身份完全相同。没有调整权限、签名或全局配置。

## 真实结果
logs/native-wait-sample/receipt.json/run-_m5eujaw：sample exit0、73420B、身份不变。原件native-sample.txt SHA b75ac3b14fcb0283071b05142522558c98029db0f5c2e2141f3bd0cabbad2368。

一秒窗口主线程87样本均为：

```
main → elfuse_launch → vcpu_run_loop_with_hooks
  → syscall_dispatch → io_xfer
  → io_wait_fd_timed_or_interrupted → poll
```

其它线程是preempt_thread_main/sigwait、Hypervisor virtual clock/cond wait、async_watcher/kevent。没有把这些普通后台等待写成死锁。

目标在外层55.106s预算结束，overall124、target_exit=null、timed_out=true、cleanup_errors=[]；stdout仍只有vkCreateInstance调用前标记，session mismatch=0。55秒是本次采样预算而非与旧70秒run完全等价的性能比较。

## 源码核对与边界
io.c与冻结accepted06源码逐字节相同；样本所用runtime摘要仍60f87660...，详stack-summary.json。io.c267-368显示poll按200ms片段检查teardown、guest信号及wakeup pipe；io_xfer可服务读写方向，所以仅栈无法判定read还是write、哪一个fd/peer。该窗口也不能证明一直是同一个fd或整个55秒都在同一调用中。

这一证据将采样窗口从“可能guest忙循环/驱动内计算”缩到宿主I/O就绪等待，**尚不证明poll实现有bug或定位了WineServer具体请求**。GDB stop_requested与I/O loop的信号/stop检查机制可能不同，能解释为何debug hook未及时返回停止响应，但这里只作代码候选，不作已经复现的GDB修复结论。

下一步在独立派生io.c做有上限、等待超过阈值才触发的metadata观测：hostPID/guestfd/hostfd、events方向、fd类型/设备inode、想读写字节数、对端身份；不记录管道载荷，不改变poll/读写返回值。先纯控制，后一次真实等待，与server/explorer对端关联后再谈修复；不继续改Vulkan参数或延长超时。

团队elfuse-baseline-worker恢复无closing失败，未claim，Lead仅此有限原生采样兜底；独立复验欠缺。原Proton/accepted binary/Steam未改，无global/commit/push。
