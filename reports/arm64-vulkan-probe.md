# 原生 ARM64 Windows Vulkan API 探针（task57）

- 团队成员本次仍在工件生成前失败；Lead仅对此卡作任务级兜底，新增实现未取得独立成员复核。
- 新测试PE来自冻结x64探针C源码，仅架构目标和显示标签调整，编译为原生ARM64；原Proton、原Wine DLL、x64样本均未修改。运行件SHA及全部argv/env见`logs/arm64-vulkan-probe/execution.json`。
- 生产分类器7个纯单元测试通过；退出码/target_exit/timeout/cleanup与实例创建、CPU guard、最终marker独立判定。
- 唯一真实运行`logs/arm64-vulkan-probe/run-5ssg96r5`：outer70.140150s达到70s预算，overall124、target_exit=null、timed_out=true、cleanup_errors=[]，分类TIMEOUT。
- stdout明确DLL加载已返回（0xfc440000）、函数指针解析成功，目标进入`vkCreateInstance`；未见返回/设备枚举/CPU guard成功，因此未通过Windows ARM64 Vulkan。
- 新时间戳记录：0024在714490.835进入vkCreateInstance，714496.460报告get_desktop_window失败；更早多个进程报告`Failed to get shared session object for window class`，后续反复desktop失败。
- 此次无DISPLAY/Xvfb/observer，原生ARM64也出现desktop/shared-session缺项；不把所有图形失败归因FEX，不推断无Xvfb是唯一原因，也不把先前Linux软件Vulkan成功归入Windows层。
- 官方原包静态win32u ELF包含`map_shared_session_block.nameW`；外部rr问题3972讨论Wine只读MAP_PRIVATE追踪共享session文件更新的Linux特定假设。该外部案例只是候选线索，不证明当前同根因。
- 当前elfuse `src/syscall/mem.c:3505-3533`对文件映射仅在MAP_SHARED且fd可写及页对齐时作host overlay，否则走pread快照。这给出独立最小ABI测试方向：只读MAP_PRIVATE是否可见另一个共享映射更新。
- 不修改Wine/Proton规避原逻辑；下一步先做该最小ABI观察测试，区分通用映射缺项与特定桌面问题，再考虑派生runtime补丁。

参考： https://github.com/rr-debugger/rr/issues/3972 （外部2025案例，非本包运行证据）。WineHQ60114抓取仅返回bot验证页，未将其当已读源码。
