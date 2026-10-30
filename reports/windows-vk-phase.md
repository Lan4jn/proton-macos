# Windows Vulkan 阶段观测受控实测报告 (Task-54 审定修订版)
- 运行路径: `sources/elfuse-socket-derived/build/elfuse` (`06a2fceb...`) | 前缀: `fixtures/runtime/windows-vk-phase/pfx` (6核心DLL+f77 PE验过)
- 诊断库: `fixtures/runtime/badalloc-phase/libbadalloc_phase.so` (`105aaa5a...`) | 中继基址: `lab/.s` (mode 0700)
- 退出码与计时: 外层控制器 exit 0 (耗时 94.48s) | 内部 Wine exit -15/SIGTERM (耗时 90.34s, 达 90s 内部限制自然超时终止)
- 整体观测状态: `OBSERVATION_TIMEOUT` / `NO_TRACE` (严禁以外层 0 判定成功, 目标 PE 未成功执行完毕)
- PE 进程输出: PID 0024 输出 `Step 1: Calling LoadLibraryA("vulkan-1.dll")...`，stderr 止于 `loaddll vulkan-1` 未见返回
- 阶段观测标记: 捕获 63 条 `[PHASE_TRACE]`，含 9 次 `INIT_DONE` (无 PID 归属，不能证明主测试进程调用无阻断)
- 异常捕获判定: 未见 `THROW_ENTER` 或 `HELPER_ENTER` (只未见 THROW marker，映射及异常是否发生未知)
- 隔离审计实证: `lab/.s` 验证本实验局部路由且退出无残留，宿主 tmp 增量 `[]` 仅为局部会话观察非全域写零证明
- 缺项与下步: 前置 00ac 报 shared session 失败，无 timestamp 难估 wineboot 耗时；下步需静态 loader/session 边界而非重复 90s
