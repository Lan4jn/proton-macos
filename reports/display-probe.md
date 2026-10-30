# Task140：显示驱动选择与类注册耗时归因

## 确定的显示路径
实际task139 prefix user.reg行831-833：HKCU Software\Wine\Drivers，Graphics="null"。
不是因为没有x11日志推断没有driver，而是显式选择内置null_user_driver。

- explorer/desktop.c:1007-1018读取Graphics覆盖default_driver；1027-1033遇null将guid清零、设置null_driver，跳出，不LoadLibrary真实显示drv。
- win32u/driver.c:936-1002 load_desktop_driver从desktop的GraphicsDriver读取null；978-993直接__wine_set_user_driver(&null_user_driver,WINE_GDI_DRIVER_VERSION)。
- 同文件775-778 nulldrv_CreateWindow直接TRUE；886-889 CreateWindowSurface直接FALSE；896-899 WindowPosChanged空函数。无需存在独立nulldrv模块，内置函数表即可令窗口对象调用成功但无宿主surface。
- 原raw baseline/probe.stderr.log第52/53、76/77行明确using null driver及driver L"null"；不是缺日志证据。
- 新raw logs/display-probe/driver_trace/probe.stderr.log行450、474：explorer选null，目标进程load_desktop_driver尝试null。loaddll显示实际win32u/gdi32/FEX模块，本轮没有真实显示drv加载记录；“未加载真实drv”的结论基于显式null分支，不仅是grep空。

## 20.7秒是桌面初始化，不是类表计算
基线RegisterClassEx BEGIN357ms→OK21035ms，实测20678ms；CreateWindowEx只3ms。
源码链：user32/class.c:343→NtUserRegisterClassExWOW；win32u/class.c:526-527对非内置类先get_desktop_window；winstation.c:812-910启动explorer、NtCreateUserProcess、NtResumeThread、NtUserWaitForInputIdle(process,10000,FALSE)。
ntdll/unix/process.c:888-894先spawn_process，然后NtWaitForSingleObject(process_info,FALSE,NULL)同步等新进程信息。msg:NtUserWaitForInputIdle自身又等待进程/idle event，并处理sent messages；这不是忙算类表。

为细分调用，使用不变d6625afe PE、新prefix、新安装目标，仅加+pid,+win,+msg,+process,+loaddll trace；exit0，cleanup_errors=[]，无模块补丁。

| 新trace事件 | 时间戳s | 原raw行 |
|---|---:|---:|
| 目标get_desktop_window准备explorer | 35110.576 | 404 |
| NtCreateUserProcess进入 | 35110.576 | 405 |
| NtCreateUserProcess返回pid/handle | 35134.371 | 408 |
| started explorer / WaitForInputIdle开始 | 35134.371 | 409-410 |
| explorer选择null | 35134.676 | 450 |
| explorer自身递归准备desktop | 35134.677 | 456 |
| 第二个explorer创建返回 | 35138.224 | 460 |
| 目标WaitForInputIdle finished | 35138.224 | 471 |
| 目标load_desktop_driver null | 35138.225 | 474 |

新trace注册总27923ms：约23795ms在NtCreateUserProcess进入到返回区间，3853ms在目标InputIdle同步等待，其余约275ms。该轮PE总28.057s、wrapper87.210s、adapter87.055s，无timeout。

归因强度：**桌面/Explorer进程启动及同步初始化是主要延迟来源**。原20.678s基线没有+process/+msg，不能把新轮23.795/3.853s直接移植为旧轮精确分解。NtCreateUserProcess期间有同步等待源码，但未抓取其每一内部函数的CPU/阻塞占比，不声称23.795s全是同一个wait或固定10秒timeout。新trace明确finished而非timeout；两轮不同耗时不是固定20秒睡眠。

## 最小呈现路线对比
### A：Wine侧实现/移植macOS显示驱动
Wine已有winemac.drv，Makefile链接AppKit/Carbon/CoreVideo/Foundation/IOKit/Metal/OpenGL/QuartzCore等。当前运行的Unix模块却是Linux ELF，不能直接dlopen Mach-O/AppKit；仅把mac改成注册表driver名称不解决ABI/进程模型。
最小需Linux端Wine user_driver_funcs适配层、宿主Mach-O AppKit服务、窗口surface提交协议/事件回传；否则需要广泛改Wine Unix运行环境。窗口生命周期、surface/dirtyrect、消息唤醒、坐标/DPI/焦点等必须设计。工作量高，完整winemac移植远超一张图呈现。
可逆模型：新drv模块及配置可由既有plan安装回滚，但必须另行批准，不替换59a76b05等已验收模块。无需完整Linux VM，前提是明确跨ABI桥而非假定Linux可直接调用AppKit。

### B：elfuse侧显示通道+宿主AppKit服务
Linux guest通过socket/shm或专用hypercall发窗口/像素事务；elfuse/宿主处理surface与输入队列。软件像素版本不需GPU，更不需要完整Linux VM。
最小接口：create/destroy/resize、pixel format/pitch/dirty rect/commit/fence、event fd或队列、input/focus/DPI/cursor。只加elfuse写屏通道仍不等于Wine驱动，Wine端还需surface与事件接线。
可逆模型：独立派生runtime及helper、外置配置记录SHA，安装包仍保留runtime外部依赖；改动和回滚都须独立批准。比整体移植winemac更易分段验证，但维护runtime协议、共享内存生命周期和线程同步的成本仍高。

## 最小实验设计（交由task141，不在本卡实现）
先用已验收64x64 RGBA framebuffer SHA2f69987b，经文件交接让独立系统clang+AppKit host helper显示NSImageView；截取窗口内容区、逐像素核对及计时。该实验仅证明宿主像素输出腿，不证明Wine窗口管理、输入或真实driver。
文件watcher能检验“像素能显示”，不能证明驱动路线正确；若成功再比较socket/shm持久通道与elfuse协议，不直接跳到游戏支持。

## 分层
Win32窗口对象PASS；WM_PAINT/GDI调用PASS；宿主Wine窗口可见FAIL（null backend明确无对应surface输出）；host呈现新通道尚未实现UNKNOWN；输入事件UNKNOWN；硬件GPU/可运行游戏UNKNOWN。既有离屏CPU渲染和gate1成果不变。

## 证据及复现
python3 scripts/runtime/display_probe/run_trace.py driver_trace
该label已存在，重复需新label以保护raw；新目录与独立prefix受task140范围限制。
- logs/display-probe/driver_trace/{receipt.json,timeline.json,probe.stdout.log,probe.stderr.log}
- runtime-logs/run-rzof_im9及wrapper原始输出
- 安装manifest、前后指纹及rollback.json
- scripts/runtime/display_probe/run_trace.py：仅读现有adapter与x64 PE

超时口径：adapter115s、外层125s；实际elfuse argv仍90s，本轮87.210s内完成，未出现timeout。后续更慢实验必须显式修正底层预算，不能把外层预算写成整体生效。
不改原Wine/runtime/backend/fixtures，不写Steam，无commit/push。没有分析闭源二进制，不需要加载逆向工具；以源码和实际模块加载trace为依据。
