# Vulkan下一等待路径与null driver单变量验证

## 官方日期候选源码（不是包精确commit认证）
Valve Wine dc26e61847081a1b5cb0733dc30feba6ee575482，API取得原文在logs/vulkan-driver-source/。

- win32u/vulkan.c4093-4169 vulkan_init_once：dlopen libvulkan、解析函数、枚举宿主扩展并打印列表，随后4159调用driver_funcs->p_map_instance_extensions。
- driver_funcs起初为lazydrv，4073-4076会调用vulkan_driver_load→pthread_once(vulkan_driver_init)，再调用user_driver->pVulkanInit。
- win32u/driver.c936-1025 load_desktop_driver：先send_message(desktop,WM_NULL)等待驱动就绪，再读GraphicsDriver；load_display_driver失败可用null_user_driver。源中显式等待不证明实际目标正停在此PC。
- 为核对可支持的配置，额外查看programs/explorer/desktop.c996-1069：HKCU Software\Wine\Drivers Graphics可设null，1027-1033特殊处理，无需加载不存在的winenull.drv；1062-1064写volatile驱动状态。源检查从原定3函数扩展到此直接相关配置函数，未遍历全依赖。

## 新实验：只在独立prefix指定null
冻结60f87660诊断二进制（PRIVATE→SHARED候选干预仍开，非正确COW），原ARM64 Vulkan PE未改。从原arm64-vulkan-probe/pfx再COWclone到fixtures/runtime/vulkan-null-driver/pfx，只在其user.reg新增[Software\\Wine\\Drivers] Graphics=null。原registry备份及前后SHA在logs/vulkan-null-driver/user.reg.before与configuration.json；真实Steam或系统registry均未触碰。

唯一目标运行logs/vulkan-null-driver/result.json/run-iec88328：70.127160s，overall124、target_exit=null、timed_out=true、cleanup_errors=[]。函数解析和LoadLibrary成功，目标仍在Step3 vkCreateInstance未返回。

**实际确认配置生效**：两次explorer trace明确display using null driver/driver L"null"；session mismatch=0、6条共享别名干预标记。stderr18693B，无全量verbose。故不是仅写配置但未加载的阴性结果。

## 可推导边界
显式null驱动仍未解除停滞，因此“只缺DISPLAY或选错默认x11/wayland”不是足以解释/消除该70s停滞的单因素。不能排除desktop同步、消息队列/信号、pthread_once重入或其它锁等待。此实验没有捕获当前PC/线程等待栈；源码链仅缩小调试窗口，不把候选当root cause。

下一次不继续延长timeout/重复null运行。现elfuse已有loopback GDB RSP（--gdb PORT，Ctrl+C、thread list、register read、断开恢复），应在Step3后抓一次guest线程PC/SP/X29/X30，区分宿主调用阻塞与guest轮询；不需系统attach或改全局调试权限。先验证stub对fork/exec与运行中interrupt的限制，失败保留unknown。

当前既有团队成员恢复仍无工件失败，task62只读分析由Lead有限兜底，null配置运行属于独立单变量诊断；缺独立复验。用户本次继续指令已把原20轮耗尽目标扩到40并恢复active，未把整项标完成。
