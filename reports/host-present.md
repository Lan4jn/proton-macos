# Task141：guest像素 → 宿主AppKit窗口单帧呈现spike

## 结论
**(a)只证单帧像素运输+宿主显示，不证driver可行。**

复用已验收guest真实64x64 RGBA读回文件，原子文件交接到独立host helper。在三个独立试验trial2/3/4中，真实NSWindow已orderFront、isVisible=true、occlusionStateVisible=true、onActiveSpace=true，窗口编号非0；批准的自身view渲染接口产出64x64 PNG，全部4,096像素及16,384字节与guest源一致。helper正常exit0并关闭窗口。

不使用系统屏幕截图权限；证据是自身view缓存截图，不是桌面截图，也不是人眼看到屏幕的证明。人眼确认UNKNOWN。原Wine HWND与host窗口没有映射关系；没有实现Wine drv、输入、完整窗口管理或游戏支持。

## 设计对比与批准选择
| 方案 | 最小内容 | 对真实驱动演进的意义 | 部署与代价 |
|---|---|---|---|
| (a)guest写文件/host watcher | frame.rgba+ready元数据原子rename，AppKit定时观察后显示 | 只验证像素可到host；文件单帧不验证驱动、时序/输入/生命周期，不能称driver可行 | 零runtime改动；独立helper及handoff目录可移除，最低成本 |
| (b)unix socket+共享内存 | 版本化消息、surface id、像素buffer、序号/fence、dirty rect、ACK/反压 | 可以承载未来驱动transport，但仍需Wine surface/event接线；fd及进程清理须验证 | 独立helper+未来driver模块，可套plan/apply/rollback；中等协议与同步成本 |
| (c)elfuse显示hypercall/专用通道 | guest ABI、内存校验、宿主事件队列、线程唤醒、共享buffer | 可做未来runtime桥，但通道自身不是Wine驱动；仍需driver frontend | 独立派生runtime及SHA/外部descriptor，有更高runtime耦合及回归成本 |

Lead已批准(a)并指定bitmapImageRepForCachingDisplayInRect/cacheDisplayInRect自有view捕获，避免全局权限。以上三种都可不写完整Linux VM；本spike只实现(a)，不修改elfuse或Wine。

## 来源与文件交接
只读源：logs/vk-offscreen/framebuffer.raw，64x64、RGBA8、pitch256、16,384字节。
SHA256：2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050。
这是此前真实Windows PE/Vulkan读回产物；本轮获准复用，没有重新运行guest渲染，也没有把重新生成的CPU图形冒充guest输出。三轮后源文件SHA不变。

receiver helper先完成AppKit初始化并输出HELPER_READY。native publisher以同一helper --publish模式只读原帧，写独立trial目录frame.rgba.tmp，再rename为frame.rgba；元数据frame.ready.json.tmp最后原子rename为frame.ready.json。ready出现前viewer不读取，不会消费半截帧。

native publisher与viewer都用mach_absolute_time和mach_timebase_info转换纳秒，同域测publish→receive→commit→view capture。Python仅启动/治理进程，不参与跨进程时间戳减法。此计时不是新guest渲染到显示延迟，精确定义为“复用guest产物开始复制/发布到host自身view捕获”。

## 实现与构建
源码：sources/host-present-spike/presenter.m。
构建脚本：sources/host-present-spike/build.sh。

    sh sources/host-present-spike/build.sh

实际使用系统/usr/bin/clang -fobjc-arc -O2 -Wall -Wextra，链接系统AppKit和QuartzCore；module cache写任务源码目录；没有第三方SDK、X11或全局包安装。

file：Mach-O 64-bit executable arm64。
最终helper SHA256：e0bd32e60d93468d9b07dc43862be302b7485a7114b9b810117ba36943deccf0。

复现（新label保护证据）：

    python3 -I scripts/runtime/host_present/run_spike.py trial5
    python3 -I scripts/runtime/host_present/verify_pixels.py

-I用于隔离外部Python路径及site初始化；发布端和接收端计时仍由native helper负责。每轮目录以exist_ok=False创建，不覆盖原raw。

## Retina、颜色与真实view捕获
运行屏幕backingScaleFactor=2，窗口内容32x32 points，对应64x64 backing pixels；源图representation与view均设置32points，NSImageScaleNone，每源像素恰好一个backing像素。layer minification/magnification为nearest，本轮无额外缩放/插值。该单一固定scale试验不等同已实现通用DPI策略。

view实际调用：bitmapImageRepForCachingDisplayInRect:view.bounds，然后cacheDisplayInRect:view.bounds toBitmapImageRep:capture。PNG直接由该capture生成，未编辑、未重绘补色、未用源帧替换。host-view.rgba通过capture.getPixel读取真实截图逻辑通道样本。全部alpha=255，无预乘反解。

独立验证再用隔离的工作区Pillow解码保存PNG为RGBA，比对全部4,096像素；PNG解码字节、capture raw、guest原字节三者一致：

- 解码像素SHA：2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050。
- 三轮PNG文件SHA：89876eeee3522b45d1ccdb6238bde774c2506b358f93af1f250b183f3268f7fb。
- independent-png-verification.json记录尺寸64x64、逐字节一致及文件SHA。
- trial2/host-view.png已read_image检查，红三角、深蓝背景。预览工具可能重编码，但核验的是磁盘原PNG，不是预览副本。

窗口证据HOST_WINDOW行包含实际windowNumber、visible=1、occlusion_visible=1、active_space=1；并在1.5秒事件泵后主动关闭。自身view捕获不是整个WindowServer合成屏，因此不宣称人眼或外部录像确认。没有调用CGRequestScreenCaptureAccess、系统screencapture或屏幕捕获API。

## 延迟与吞吐量级
单位ms；三个试验都重新启动helper并创建独立窗口。commit指orderFront及displayIfNeeded/CATransaction flush后的时间，capture前有明确150ms事件泵settle，不是垂直同步或实际扫描输出时刻。

| 项目 | trial2 | trial3 | trial4 |
|---|---:|---:|---:|
| 原帧开始复制→ready发布计时点 | 1.016 | 0.289 | 0.280 |
| publish→receiver看见ready | 20.172 | 34.814 | 41.813 |
| receive→commit | 187.232 | 241.359 | 187.166 |
| receive→view capture | 345.039 | 392.650 | 341.151 |
| publish→view capture | 365.211 | 427.463 | 382.965 |
| copy begin→view capture | 366.227 | 427.752 | 383.245 |
| 16,384B / publish-to-capture 秒（B/s） | 44,861.686 | 38,328.434 | 42,781.987 |

publish时间在序列化ready之前记录，包含元数据写入和原子rename。watcher轮询目标5ms但实际含AppKit调度/文件观察开销，不把20-42ms说成纯磁盘带宽。

单帧端到端366-428ms（中位383.245ms），观测有效payload约3.8e4-4.5e4 B/s。这个数被AppKit初始化/窗口创建与150ms settle主导，**不是持续传输带宽、刷新率、FPS或游戏性能**。本轮不测连续帧，不从单帧推算可玩性。

## 初轮失败与修正（证据保留）
trial1为INCOMPLETE，未标通过：
1. 自有PNG实际原始样本已等于guest，但host-view.rgba曾通过getColor再转换sRGB，造成重复颜色解释（例如深蓝变1,25,147）。随后改为读取capture.getPixel的原始样本，不修改PNG；独立PNG解码证明最终数值一致。
2. trial1 Python monotonic_ns为本进程相对量，和native mach绝对时间相减产生荒谬约3.56e7ms，故trial1跨时钟延迟/效能数值**无效，不得用于性能结论**。后改同一native二进制publisher/viewer统一时钟，重新独立试验trial2/3/4。不是对旧时间戳补造校正值。
3. 最初图片解码环境受外部PYTHONPATH污染，Pillow导入失败；使用工作区bundled Python -I隔离后正确解码。此问题不影响native截图。

trial1原stdout/stderr/result/PNG/raw保留不覆盖；invalid-trial1.json记录失效口径。旧helper SHA755d6ff…不作为最终可用构建。

## 下一步演进所需最小接口面
这些仅为清单，均未实现：
- Window生命周期：Wine HWND/surface与host window id映射、create/show/hide/destroy、owner/z-order、位置及resize ack。
- Surface：RGBA格式/pitch/色彩空间、dirty rectangles、buffer生命周期、frame sequence/fence、背压、失联清理、跨进程内存边界校验。
- Input：键盘/鼠标/滚轮/按钮、焦点、捕获、坐标转换、事件队列唤醒回Wine。
- 尺寸/DPI：logical vs backing像素、Retina迁移、resize与DPI change通知；当前固定scale2不替代它。
- 光标及剪贴板：cursor图像/热点/可见性，选择/粘贴所有权及数据格式。
- 图形交换：GDI window_surface flush接线；游戏需要Vulkan/OpenGL swapchain/呈现同步另行桥接，离屏CPU三角形不等同swapchain。
- 可逆部署：未来新增Wine driver与注册表选项、host服务、协议版本均应独立manifest/SHA及rollback；当前仅普通本地进程，没有注册持久服务。

要谈“看得见地玩游戏”，至少先完成窗口/surface生命周期、持续帧提交与同步、输入/焦点回传、DPI坐标、真实Wine drv接线及目标图形API呈现；光标/剪贴板等可分期但仍是常用桌面功能缺项。

## 分层验收
| 层次 | 结论 |
|---|---|
| 已验证guest产物来源及文件交接 | PASS |
| native host窗口创建/orderFront/可见且未遮挡状态 | PASS（AppKit自身状态证据） |
| 自有view截图全部像素与guest一致 | PASS，4,096/4,096 |
| 人眼/全桌面合成截图确认 | UNKNOWN，未请求全局权限 |
| 原Wine HWND实际宿主可见 | UNKNOWN，不是本helper窗口 |
| Wine驱动集成可行性 | UNKNOWN；文件spike不证明它 |
| 窗口管理/输入/DPI策略/多窗口 | UNKNOWN |
| 游戏兼容/硬件GPU | UNKNOWN |

本轮不修改已验收backend/runtime/Wine/fixture/Steam；不改变现有gate=1及CPU软件渲染历史边界；仅新增task141目录中的helper、脚本、日志及报告。

## 证据清册
- build.log（初版）、build-revised.log（最终系统构建类型与SHA）
- tests-red.log / tests-green.log / tests-final.log（4项全图/单字节损坏/尺寸负测试）
- trial2/3/4：frame.rgba、frame.ready.json、publisher raw、host raw、host-result.json、host-view.png/rgba、pixel-verification.json、receipt.json
- independent-png-verification.json
- trial1保留失败raw及invalid-trial1.json
- evidence-sha256.json为交付完整性索引
