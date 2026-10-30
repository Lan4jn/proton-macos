# I/O等待guest现场与进程归属纠正（round24/task66）

独立sources/elfuse-io-context-derived从19040d51复制，仅io.c helper追加同线程current_thread的guest_tid/in_syscall、ELR_EL1、LR及两HV返回状态。读取只在2s阈值发生时；不写寄存器、不读guest payload、不改变I/O返回。ELR是SVC返回位置而非完整上层guest调用栈，LR也不是完整回溯；无module映射不能擅自符号化。binary SHA0112982773e4b65f9495be980e1afd07763e0c2da82e95bf99741099d938ae9b。

控制logs/io-wait-context/control.json/run-wm4bn6vy：2.528291s/0/noTimeout/cleanup[]，PIPE_WAIT_CONTROL_OK；syscall63(read)、gfd3/want1、ELR0x2007f1c6c/LR0x2007e5074，两HV状态0。

一次真实独立prefix/noGDB/null驱动/shared别名gate开启Vulkan：vulkan/receipt.json/run为该收据result.run_dir，55.113767s/124/targetnull/timeout/cleanup[]、0mismatch；34条总等待。启动wrapper记录native根PID30942，根仅一条记录：gtid1/syscall63、gfd8/hfd54、POLLIN/want16/FIFO，ELR0x2000c5094、LR0x2000c50b8，两HV返回0。

## 重要反证：根PID不是已绑定的目标PE进程

逐行核对显示root observation在stderr第20行，而trace:vulkan:vkCreateInstance在第263行，期间还有services等子进程启动。也就是说该已绑定根的等待早于目标Vulkan调用；其它PID/TID观测不能直接归入根。

**必须收窄round22及23解释**：round22核对的是exec保留PID的启动根进程，sample得到其io_xfer→poll是事实；没有证明它就是执行Windows PE/Vulkan的Wine子进程。因此它不构成vkCreateInstance调用线程处在pipe wait的证据。root read16可以是启动器等待子进程/其它协议，尚不能确定是哪个Wine wait结构。round23其它后台16B等待也未建立PE归属。

这轮进展是消除进程身份误归，而不是完成Vulkan根因定位。前序报告中“目标”应按本纠正理解为owned启动根。

## 下一步
建立本次supervisor组内有限父子进程映射，读取精确后代command/path及已知guest process identity/loader标记，先绑定vk_enum_arm64.exe对应host PID；不全系统枚举、不读其它进程。对绑定后的目标只采一次native sample，或在io等待日志中加入可信的当前guest执行映像身份，不凭pid顺序/同地址/16字节推断。该归属前停止进一步改I/O或Vulkan参数。

本次增加+loaddll使日志44975B，是额外观测变量，不把时延当性能比较。两诊断版本及原accepted版均保留，不默认接后端，PRIVATE→SHARED仍是有缺陷的因果实验而非修复。

steam-macos-research当前团队恢复task ready失败未claim/产出，Lead就有限上下文观测兜底；独立验收仍缺，无新会话/临时subagent/真实Steam/global/commit/push。总目标active。
