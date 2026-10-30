# Task143：显示驱动最小可行方案（设计，不实现）

## 决策摘要与证据等级
**候选推荐：先裁剪 Wine frontend，把传输实测设为实现驱动前的硬门；并列保留A（独立宿主服务）、B（elfuse专用传输+服务）、C（runtime进程内呈现）。优先用M2验证A的现成原语；若外部映射导出成为硬阻塞，在B与C之间先比较最小闭环及调度/崩溃代价，不预设必须增加hypercall。**不建议将整套winemac直接拿来Linux guest加载。这不是证明整套移植在理论上永远不可能，而是其当前同进程Darwin API/对象/线程假设与Linux ABI不兼容，不是改一个Graphics注册表就能工作。

本卡只设计、只读盘点和完整性核验，**没有实现驱动，也没有实现/测量新socket、shm或hypercall通道**。三条路线、字段和门槛都是待批准执行的规格，不是已实现能力。

- 已证：Win32 HWND及消息循环/GDI成功；当前注册表Graphics=null，win32u内置null_user_driver无host surface；真实guest framebuffer可由独立host helper自有view呈现且4096/4096像素一致。
- 已证边界：host helper窗口不是原Wine HWND，view缓存截图不是人眼见屏或整桌面合成证明。task141文件watcher观察20–42ms不是socket RTT，也不是持续吞吐测量。
- 已证性能边界：task142轻载固定成本明显；重叠覆盖下CPU成本增大，填充增量三档1.22e8/3.36e8/5.32e8覆盖像素每秒，不能压成一个通用常数，更不能等同游戏性能。
- UNKNOWN：live-shared跨guest/host映射、消息往返、持续传输、Wine frontend接线、输入/DPI/多窗口/WSI、正常private COW。

## 1. winemac 可复用性：源码事实而不是移植百分比
源码根简称W：sources/wine-pin-adea/pristine/wine-adea6cbac9d00bb22910145354d00c463fcf3afc/dlls/winemac.drv。
本轮研究直接使用本地固定版本一手源码；没有在线资料或闭源模块反编译，不对最新版Wine作断言。独立脚本sources/display-driver-design/inventory.py保存每文件SHA和计数于logs/display-driver-design/source-inventory.json。

### 1.1 规模及接口数量级
- 14个.c共13,303行，9个.m共10,208行：**23个实现TU、23,511行**；9个.h共1,483行，总24,994行。包括注释/空行；不是需要重写的行数，不提供无依据人月。
- W/Makefile.in:1–15：winemac.drv + winemac.so，导入user32/gdi32/win32u等，链接**9类framework**：AppKit、Carbon、CoreVideo、Foundation、IOKit、Metal、OpenGL、QuartzCore、Security。CoreGraphics/CoreFoundation直接API另存在于源文件，不简单按Makefile数量推断所有依赖。
- 词法盘点去重名称：CG*函数样式112、CF*67、CV*8、IO*17、dispatch_*12、NS*类型/常量名称229；只为API接触面量级，不是完整reachable调用图、真正系统导出数或ObjC selector数。
- W/macdrv_cocoa.h：**85个extern macdrv_*函数声明**。这条现有C边界可作为切分参考，但不是直接可序列化的85条IPC协议。

### 1.2 哪些可借鉴，哪些必须改边界
| 子系统 | 直接证据 | 本环境复用判断 |
|---|---|---|
| Win32窗口/样式与几何 | W/window.c:1543+ WindowPosChanging、1586+ WindowPosChanged；整个文件2164行 | guest侧保留Wine HWND/owner/style语义，参考现有转换；回调绑定仍须针对当前win32u ABI重新核验，不能整文件不改编译 |
| GDI surface | W/surface.c:80–98直接CGColorSpaceCreateWithName、CGImageCreate，再macdrv_window_set_color_image；214–234 CreateWindowSurface关联cocoa_window | Linux侧直接依赖CG/opaque host对象，要替换为像素元数据+buffer/序号；host侧才构造CGImage/NSView |
| AppKit窗口实现 | W/cocoa_window.m 4097行，39+ NSWindow类别，320+ CALayer内容scale | 可作宿主原生行为参考，部分算法可移植；仍依赖进程全局app、Cocoa对象生命周期与Wine回调，不等于单独服务开箱可用 |
| 线程/事件 | W/cocoa_event.m:129 pipe；489–540 OnMainThread/dispatch semaphore；macdrv_cocoa.h:452–458 queue fd/copy/release | 同进程队列、指针和callback须改IPC、事件id、所有权/超时；host主线程不能同步等guest回调形成死锁 |
| Cocoa启动/会话 | W/macdrv_main.c:426–450 SessionGetInfo图形session、start_cocoa_app；W/cocoa_main.m:116–146 CFRunLoop主线程source | host helper主线程接管AppKit；Linux guest不能直接SessionGetInfo或调用CFRunLoopGetMain |
| 键鼠/DPI/显示 | W/keyboard.c1788行、mouse.c964、display.c1118、cocoa_display.m1031；W/event.c:463–466焦点事件 | Win32消息映射借鉴guest逻辑；输入采集/屏幕像素/scale来自host，必须明确双向坐标与focus序列 |
| 剪贴板/光标 | W/clipboard.c1526、cocoa_clipboard.m248、cocoa_cursorclipping.m507 | 不属单静态窗口最小门，后续跨进程所有权、格式/线程/约束另设计 |
| GL/Vulkan WSI | W/opengl.c2792；W/vulkan.c:46–76创建client surface/Metal device/view/layer，vkCreateMetalSurfaceEXT或vkCreateMacOSSurfaceMVK | 不能把Metal层指针传给Linux Vulkan loader；跨进程host对象与现有CPU Vulkan instance不在同一ABI，独立WSI/GPU工程，不随GDI窗口自动实现 |

W/macdrv_cocoa.h:102–108将window/view/Metal/context等定义为opaque指针；317–407事件结构含对象/查询生命周期。**不允许跨协议直接发送NSWindow*/CGImageRef/guest VA/HWND当宿主可解引用指针**。以稳定数值id+generation代替。

## 2. 主交付：职责切分与数据流

    Windows x64 PE / USER32 / Wine server（guest）
       HWND、class、style/owner、Win32消息语义
                  |
       Linux ELF Wine drv frontend（guest）
       Wine callbacks、window_surface、Win32坐标和事件转换
                  |
       versioned protocol + frame buffers + event/ACK queue
             [路线A：现有socket/文件映射]
             [路线B：runtime专用传输后端]
                  |
       Mach-O host service（macOS主线程AppKit）
       NSWindow/NSView、surface合成/显示、物理输入/屏幕scale采集

| 职责 | guest保留 | host接管 | 边界约束 |
|---|---|---|---|
| 窗口创建/几何 | Win32 HWND/class/style/owner/desktop关联、请求尺寸、Wine消息泵 | NSWindow生命周期/约束/宿主屏幕位置及关闭请求 | guest HWND≠NSWindow id；用id/generation映射，每个Wine进程/桌面有session namespace |
| 表面提交 | GDI dirty region、格式/stride、buffer写入、帧序号 | 按已协商format合成并呈现、使用完成后ACK | 不把commit返回当扫描输出；ACK分RECEIVED/CONSUMED，PRESENTED仅未来有真实依据时定义 |
| 输入 | Win32消息和捕获语义、按事件scale epoch映射logical坐标 | 采集鼠标/键盘/焦点/物理坐标/原生时间戳 | 物理→logical换算留guest，host提供坐标原点/scale/display id；禁止双方各自猜一次scale |
| DPI/resize | 生成Wine resize/DPI通知、客户端logical rect | 确认实际content backing尺寸、屏幕迁移和scale | resize generation切换，旧帧不可画到新尺寸buffer；不强行1pixel=1point |
| 多窗口 | owner/z-order意图、popup与子窗裁剪语义 | NSWindow排序/宿主激活 | 顶层HWND通常映射host窗；child HWND通常合成到父surface，不“一HWND一NSWindow”简单套用 |
| explorer/desktop | Wine桌面/窗口站/消息目标仍存在 | 只显示应用顶层窗口，不默认显示第二个explorer桌面 | 多explorer/桌面一对多session映射有独立策略；不为绕慢启动而取消语义 |

### 2.1 最小协议字段（候选v0，非现存格式）
全部明确小端、定长整数/长度前缀、总长度上限；消息内不得使用C bitfield或裸struct memcpy当ABI。

| 消息 | 必备字段 |
|---|---|
| 公共header/HELLO | magic、protocol_major/minor、message_type、message_length、session_id、request_id、capability_bits、clock_domain、max_frame_bytes |
| CREATE/DESTROY/SHOW | window_id、window_generation、parent_id、owner_id、style_flags、desktop_id、logical_x/y/w/h、initial_dpi、title_length/title_utf8、visibility；响应result/error_code |
| SURFACE_ALLOC/RESIZE | surface_id、surface_generation、window_id、buffer_id、slot_count、width_px、height_px、pitch_bytes、format_enum、alpha_mode、color_space、origin_top_left、allocation_bytes、transport_handle_or_path_token、resize_epoch |
| FRAME_COMMIT | surface_id/generation、buffer_id/slot、frame_sequence、dirty_rect_count及x/y/w/h、written_bytes、publish_timestamp/clock_domain、resize_epoch、producer_fence_token |
| ACK/ERROR | request_id、surface_id/generation、frame_sequence、stage(RECEIVED/CONSUMED)、consumer_fence_token、error_code、receiver_timestamp；不要将token冒充GPU可导入fence |
| INPUT_EVENT | window_id/generation、event_sequence、event_type(key/move/button/wheel/focus/close)、host_timestamp/clock_domain、physical_x/y、display_id、scale_num/den、scale_epoch、keycode、button、modifier_bits、wheel_delta、focus_state |
| DISPLAY/RESIZE_EVENT | window_id、event_sequence、content_width/height_px、content_width/height_logical、screen_rect_px、dpi或scale、scale_epoch、resize_epoch |
| DISCONNECT | session_id、reason、last_consumed_sequence；释放未ACK slot及所有host窗口 |

首版只支持RGBA8 opaque、top-left、单窗口单surface双buffer、最多一个in-flight commit；但保留generation/sequence以免后续重构ABI。尺寸/pitch/dirty rect必须有溢出及边界校验，buffer不可在ACK前覆盖。不要依赖跨进程裸原子锁自动可靠；发布顺序、cache可见性、ACK生命周期必须在M2实测。

## 3. 两路线比较
| 项目 | 路线A：Wine裁剪drv + 宿主服务 | 路线B：elfuse显示通道 + drv frontend |
|---|---|---|
| guest frontend | Linux ELF实现当前user_driver_funcs相关窗口/surface/event接口，参考winemac语义，不直接链接framework | 同样需要frontend；hypercall不会替代Wine回调/窗口模型 |
| host frontend | AppKit主线程持有NSWindow及CG/Metal对象；协议id映射 | 基本相同，可与A共用host协议处理层 |
| surface/commit | socket控制、live-shared buffer若实测可用；否则明确copy路径 | runtime管理guest内存导出/复制/生命周期，专用提交/事件接口 |
| 输入/焦点/DPI/光标 | host采集后socket事件fd唤醒Wine，guest转消息 | runtime事件队列+唤醒语义，仍须guest转消息 |
| 多窗口 | 统一session/window/surface ids及parent/owner映射 | 同协议，另有跨guest进程runtime持有对象的清理风险 |
| 是否改runtime | 目标不改，但需M2证实现有原语支持；不能从socket syscall存在推断可用 | 必须改独立派生runtime；新ABI和Hypervisor/guest线程交互要回归 |
| 回滚模型 | 新drv+显式Graphics选择、独立host helper、manifest记录；仅新prefix演示，原null配置保留 | 再加新runtime SHA/descriptor/配置及桥协议版本，原elfuse保留回滚；现有manifest验证能力需确认，不能假定支持未来所有IPC资源 |
| 相对投入 | 窗口/事件接线高，纯transport若现成可用中；首次规模更可控 | A的语义工作仍在，另加runtime内存/同步/治理高风险，整体相对更大 |
| 决策 | M2成功后优先推进A的单窗GDI闭环 | M2确定原语不支持且A copy方案不满足目标，才设计B最小transport实验；不直接开整驱动 |

**吞吐不够不自动证明 hypercall 更快。**必须区分拷贝、调度、socket ABI、共享映射一致性、host消费和渲染本身。B是否能提高性能或正确性仍UNKNOWN，不把runtime修改当成自动解药。

### 3.0 路线C：runtime进程内AppKit或由其dlopen的dylib

**C是第三条并列候选，不是本卡已实现能力，也不是把A helper改个文件后缀就能加载运行。**host native代码与elfuse guest映射处在同一宿主进程地址空间，因而消除了“另一个host进程如何取得同一对象/SCM_RIGHTS/跨进程handle导出”的需求；不需为读guest已映射buffer而新造hypercall。这里消失的是**外部进程导出问题**，不是全部内存/协议问题。

| 维度 | A：独立服务 | B：专用elfuse传输+服务 | C：进程内呈现 |
|---|---|---|---|
| 地址/对象导出 | 需现有共享对象/FD导出或payload copy | runtime显式导出/复制/桥接 | 不需跨进程导出；runtime内部仍需解析guest VA/GPA→host backing、权限/范围及generation |
| guest buffer消费 | host外部映射/接收 | runtime控制通道到服务 | native代码可读同一host backing，但必须pin/snapshot策略、发布/消费屏障、避免guest覆盖或munmap后悬挂 |
| 是否自动zero-copy | 未证 | 未证 | 去掉guest→外部服务复制的必要性，**并不自动证明从guest到屏幕全链zero-copy**；NSBitmapImageRep/CGImage/合成可能复制，task141原helper本来在presenter.m:58有memcpy |
| runtime修改 | 目标不改，需原语门 | 修改新ABI/内存/事件路径 | 改runtime入口/主线程/生命周期或提供插件API，版本化构建变体；不是仅调用dlopen |
| Wine frontend | 要 | 要 | 仍然要：create/commit与guest队列何时通知runtime、如何wake guest必须设计；“读buffer不用hypercall”不等于无需任何提交协议 |
| host AppKit | 独立主线程 | 独立主线程 | 必须保留宿主主线程给NSApplication/runloop，vCPU运行及阻塞操作不得占UI线程 |
| 输入 | IPC事件回传 | runtime队列后frontend接线 | 主线程采输入，投递有界队列，vCPU异步消费；不能在主线程同步等待guest处理消息 |
| 崩溃域 | helper与runtime隔离 | 部分分离，桥有共同风险 | UI/dylib崩溃能杀runtime及guest，合并故障域；内存越界后果更直接 |
| 多进程Wine | 单服务可汇聚多session | 可汇聚，runtime协调 | Wine可能产生多个elfuse宿主进程；一个进程内NSApp不能天然统管其他进程窗口，跨进程owner/focus/desktop协调仍可能需要协议 |
| 回滚 | helper+drv/配置 | runtime+helper+drv/配置 | 派生runtime+选配dylib+drv/配置整套SHA/版本；暂停并关闭窗口后回滚进程，不声称磁盘manifest能恢复活UI对象 |
| 相对代价 | transport门风险，隔离好 | runtime ABI/传输风险高 | 少导出环节，但主线程/HVF绑定、生命周期、崩溃域和多进程协调风险高；不预先断言比A/B省工 |

**C为何不违反“不写完整Linux VM”**：它保留现有elfuse执行Linux guest syscall/ABI的模型，只在既有macOS进程添加native显示/事件消费端，不引入Linux内核启动、完整虚拟显卡/桌面或完整VM设备栈。即便如此，它仍然是真正runtime开发，需要HVF线程/进程生命周期验证，不可称纯helper扩展。

源码依据与未证项：runtime src/main.c:230起为当前main，末尾直接调用elfuse_launch并在其返回后做sysroot等cleanup；没有本卡已证的AppKit主线程接管点。task141 presenter.m:14自己泵事件、43创建NSApplication，58将raw复制到bitmap。这些宿主贴图/颜色和view捕获代码可抽为dylib模块参考；不能原样保留main/全局NSApp初始化并假设与vCPU线程无冲突。HVF vCPU创建与执行是否必须同线程、当前launch线程归属、exec/fork后的AppKit有效性等均须独立查证，不能擅自把vCPU搬线程。

候选C最小调度合同：UI主线程只消费有界命令/帧队列；runtime线程负责guest执行及安全点；commit写slot后异步通知UI，UI消费完成才归还slot；队列满由guest/worker侧背压或明确丢帧策略，**不允许vCPU持有guest/user锁同步等待UI，而UI又同步调用回guest**。dylib接口至少有attach_runtime、resolve/pin/release_buffer、enqueue_commit、poll_input、shutdown，传入受校验的opaque runtime context，不公开任意guest指针给任意插件。

C的M2变体：先同进程native消费者读取guest已映射且被pin的buffer，只测CRC/ACK、无AppKit；再独立验证UI主线程事件泵与guest同时运行/退出无死锁。读前/后generation及seq、unmap/resize、进程退出压力都应测试。若取得正确host backing但仍有复制，不叫zero-copy；如果无需拷贝buffer读通但UI失败，不能宣布呈现完成。C同样进入M3真实Wine surface门，不跳过frontend/WSI/输入。

### 3.1 runtime现有原语的直接风险
源根E：sources/elfuse-once-panorama2-derived/src/syscall。
- E/dispatch.tbl:208 mmap、229–235 socket/socketpair/connect已有派发；只说明有实现入口。
- E/net.c:382–404将AF_UNIX映射到host；SEQPACKET特判只为rosettad，其他路径不能假定原生支持。首版协议选SOCK_STREAM+length framing+partial read/write处理。
- **E/mem.c:1020–1028明确file-backed MAP_SHARED为snapshot-style，coherence是msync-driven而非live page-cache；同段又明确anonymous shared映射保持原路径，不能外推其也是snapshot。**因此“guest和host同一buffer零额外拷贝”在本环境是高风险UNKNOWN；不能仅见MAP_SHARED成功就判共享可用，不能拿msync复制假称zero-copy。
- 正常private COW能力仍未解决，gate1不等于ABI正确性；共享协议不得扩大诊断别名对任意进程的假设。

## 4. 四道可判定门（M1→M2必须先于驱动）
### M1：固定版本/切分合同与已有证据完整性（lab当下可完成）
输入仅已有源码、task139–142证据、已存在host PNG，不依赖新drv/新transport。
执行inventory.py + check_baseline.py；列出不可跨ABI对象、null选择、目标格式/scale；确认原帧2f69987b和host-view PNG89876eee及PASS收据一致。
**PASS**：源码SHA/规模清单完整、原帧/截图/registry核验通过、guest/host职责和协议字段明确。**FAIL**：源码/运行证据版本不一致或来源帧不匹配，停在修正事实。
本卡已执行静态/完整性部分PASS，记录baseline-check.json；不意味着协议实现或传输门已通过。

### M2：独立传输门（下一实现任务，先做，不依赖Wine drv）
用真实Linux guest小producer、原elfuse及native host consumer；无NSWindow、无Wine window callbacks，隔离transport。两端各保留独立可验证随机seed/seq/CRC，720p RGBA8=3,686,400B；先1buffer正确性，再双buffer持续事务。

1. **路径A，按backing类型拆开的live-shared试验**：guest每帧写变化的全buffer，只有descriptor/序号/ACK走Unix stream。host直接读同一对象的映射并CRC，不额外像素copy。分别测试：
   - **(i-a) MAP_SHARED|MAP_ANONYMOUS**：先查有没有现有、受治理的host映射导出/句柄获取机制。guest匿名地址不能凭名字或数值直接被另一个host进程mmap；必须先证明两端获得同一底层对象，不能复制成另一个host buffer冒充共享。若原runtime不暴露此能力，结论是“外部host服务取得匿名映射的路径未支持/未证”，**不是“匿名页一定snapshot”**。不为该试验在本卡新增runtime导出。
   - **(i-b) 无路径对象/memfd等价物**：先确认实际memfd或等价对象的内核/模拟实现及FD传递机制，再用同一个对象让host映射；memfd是文件描述符支持的对象，并非自动等同MAP_ANONYMOUS，仍需核验它是否走同一snapshot路径。不能把SCM_RIGHTS支持或映射可见性当作既定事实。
   - **(ii) 普通file-backed MAP_SHARED**：按mem.c:1020–1028预期先做无msync负对照，再做msync变体；源码注释是风险线索，不取代真实读写证据。
   - 各backing分别保存字段：backing_kind、object/handle_identity、guest_write_start/end与clock_domain、sequence、CRC、msync_called及调用区间、host_first_observed_sequence/time、CRC检查、ACK时间、guest到host单向延迟及校时误差（无法校时则UNKNOWN，另报producer同域ACK RTT）。在host轮询超时后标记“未观察到更新”，不能把超时数值当成可见延迟。
   - 每种结论独立为“支持live-shared”“不支持live-shared（在该映射/导出路径实测）”或“对象导出/原语未支持，未完成可见性试验”。只有真共享读写无msync通过才算A的零额外拷贝候选；任何需要msync/重新pread/remap才看见的变体单列，不并入zero-copy。
   - file-backed对照失败**不能推出所有共享内存都失败**。若所有可导出的(i)与(ii)路径都不live，才能说“当前已测试backing需显式同步/复制，或进一步runtime改造”；仍不宣称未测试的其他共享方案都不可能。
2. **路径B，私有buffer + payload**：guest写私有buffer，socket/pipe发送实际3,686,400B，host读入独立buffer并CRC；测真实payload而非descriptor计数。包含实际copy及syscall/排队。不得写/dev/null替代消费。
3. **对照**：同尺寸guest本地memcpy+CRC、host本地memcpy+CRC；无像素payload ping/ACK RTT。A与B差值是“路径额外成本”，包含copy+socket/syscall/调度，**不直接等于纯memcpy成本**。纯copy只用本地校准另报；跨时钟延迟用producer同域发布→ACK RTT，单向需要校时/误差范围。
4. **持续负载**：warmup后至少10秒或600帧，逐帧sequence/CRC/ACK，报告p50/p90/p99/max RTT、丢/重帧、持续payload MB/s、queue depth、CPU用时。先pilot自适应预算；总超时事前对齐，超预算给分段结果和最后seq，不只报timeout。
5. **门槛定义（候选设计目标，不是本环境承诺）**：720p60 RGBA8至少221.184MB/s=210.938MiB/s有效payload，64fps为235.930MB/s；不是110MB/s（后者是2B/px）。建议10秒无错、无积压，ACK p99≤一个目标帧间隔16.667ms，另留host呈现/渲染预算；若需20%transport余量，单独目标265.421MB/s。这些是可行性门槛，达到也不证明游戏可玩。
6. **与文件通道对比**：task14120–42ms是publish到watcher观察的单向延迟；M2 socket RTT/throughput必须各自标单位/起止，不拿watcher值当socket RTT。AppKit创建/150ms settle也不混入M2transport。

**PASS**：明确至少一种有一致性保证的路径满足选定目标、无旧帧/半帧、消费ACK正确、资源关闭无泄漏，且注明A/B究竟哪条成功。**FAIL分流**：A一致性失败按anonymous/descriptor-backed/file-backed分开定位对象导出与MAP_SHARED/msync；B或ping失败查socket ABI；B慢但本地copy快查队列/调度；CPU copy本身慢不能断定hypercall可解。A不成立而B达到目标仍可先用A路线的copy transport；都不成立才评估B runtime最小通道，不直接宣判B一定成功。

### M3：单个真实Wine HWND→host surface闭环
以独立派生Linux frontend、显式测试Graphics配置和单窗GDI PE；**不是**把原PNG直接给host helper。窗口create→host id→真实WM_PAINT→window_surface flush→commit/ACK→destroy；测试host关闭/guest退出/host崩溃三种清理。
**PASS**：Windows自己的绘制变化可对应到同一host窗口，自有view截图逐像素/序列匹配，连续提交无撕裂，resize epoch暂锁定单尺寸，exit0且回滚前后指纹一致。宿主可见状态/自身view捕获与人眼/系统屏幕证据分层，不申请全局权限冒充确认。
**FAIL**：仅CreateWindow返回、仅独立helper窗、没有frontend flush、ACK死锁或窗口残留，均不算闭环。

**M1–M3全部通过，也只到“能看见一个静态/自绘窗口”，不等于能跑游戏；还需要WSI、输入子系统接线和前面未解决的COW。**

### M4：可交互窗口与桌面边界，WSI另案
分子门：键鼠/焦点/关闭消息；resize及scale2/1迁移；两个owner/popup/child关系；explorer desktop隔离；光标捕获/释放；断线重连及原manifest回滚。每子门独立事件序号与可判断消息记录。
**PASS**：输入到正确HWND，物理/逻辑坐标无重复scale，resize旧buffer不复用，多窗z-order/owner正确，host/guest退出全部资源归零。未测项保持UNKNOWN，不能用单一消息通过替代全门。
**WSI独立立项条件**：先决定CPU offscreen copy呈现还是host GPU后端；Vulkan surface/swapchain/acquire/present/semaphore/fence、DXVK/vkd3d路线都要真实app测试。无WSI情况下GDI窗口可用不代表3D应用；CPU重载与正常COW依旧游戏前置风险。

## 5. 风险及相对规模清单
相对等级只比较本项目内部子系统，不给人月/完成承诺。23,511行是参考实现规模，不等于待改规模。

| 子系统 | 相对规模 | 主要风险/需要证据 |
|---|---|---|
| 版本化协议/ids/格式校验 | 中 | ABI对齐、整型溢出、stale generation、partial read/write |
| M2 socket/live-shared一致性 | 中–高，前置硬门 | snapshot式MAP_SHARED、guest4K/host16K、无真实零拷贝、fd生命周期/凭据 |
| Wine drv callback/frontend | 高 | 当前user_driver_funcs版本、重入、Wine server/user锁、surface生命周期 |
| host AppKit服务 | 中→高 | 主线程/runloop、CG对象所有权、同步RPC死锁、activation/权限/图形session |
| GDI surface/dirty rect/alpha/color | 高 | BGRA/RGBA、premultiply、stride/负高度、双buffer背压与撕裂 |
| 输入/焦点/IME/快捷键 | 高 | 延迟、键盘布局、捕获、系统保留键、重入Wine消息与IME |
| DPI/多显示器/resize | 高 | points与pixels、origin、scale epoch、跨显示器、最小化后surface |
| 多窗口/explorer桌面映射 | 高 | child不是独立NSWindow；owner/popup z-order；多个guest进程/桌面争焦点 |
| 光标/剪贴板/全屏 | 中–高 | sandbox/clip、跨进程所有权、格式、宿主全屏与Win32模式差异 |
| runtime进程内UI/dylib（路线C额外） | 高 | 主线程/HVF绑定、fork/exec、buffer pin、崩溃域合并、多elfuse进程owner/focus协调；未证zero-copy全链 |
| runtime专用通道（路线B额外） | 高 | vCPU事件唤醒、共享内存一致性/治理、协议回归；仍不解决Wine语义 |
| GL/Vulkan WSI及GPU | 很高，独立工程 | 同ABI设备/instance/surface、swapchain/同步、跨进程Metal句柄与CPU Vulkan不兼容 |
| 正常COW/线程/进程正确性 | 很高、并行前置缺项 | gate1是诊断共享语义，窗口成功不证明一般Windows进程隔离/游戏可靠性 |
| 可逆部署/故障隔离 | 中 | host helper不留持久服务；只杀owned session；manifest无法自动回滚活对象需独立清理证明 |

## 6. 即使做完也不保证游戏运行的部分
- A/B/C的transport或进程内读达标，只能说明像素/消息通道，不是Wine驱动正确性。
- M3真实自绘窗口，不覆盖Vulkan/OpenGL/DXGI swapchain。
- M4输入多窗，不解决CPU软件渲染重负载、GPU后端、COW、FEX完整x64指令/异常/同步、音频、游戏逻辑、Steamworks或反作弊。
- 文件像素通道的成功和CPU轻载rate不等于可交互游戏体验；硬件GPU是否必须对所有目标仍UNKNOWN，性能目标必须逐app重新验证。

## 证据与本卡可复现命令
    python3 -I sources/display-driver-design/inventory.py
    python3 -I sources/display-driver-design/check_baseline.py

输出：logs/display-driver-design/source-inventory.json、inventory.log、baseline-check.json。报告引用本地一手源码固定路径/行号；未修改原Wine/runtime/backend/已有产物，不写Steam，无commit/push，无新增驱动或传输实现。旧任务报告只读参考：reports/display-probe.md、host-present.md、vk-throughput.md。
