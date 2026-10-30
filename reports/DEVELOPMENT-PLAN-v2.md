# proton-macos-lab 开发计划 v2（待确认）

## 目标与边界

以 reports/PROJECT-STATUS.md、display-driver-design.md、inproc-present.md 为事实基线。本计划只规划，不启动实现。
最终目标保持原生 macOS Steam + ARM64 Proton + x64/FEX，保留 elfuse/HVF 路线，不引入完整 Linux VM。
近期目标：单个真实 Windows HWND 的动态 GDI 绘制映射至 macOS 窗口，并有正确键鼠/关闭消息。
实验构建、原版 Valve 产物、派生 Wine/runtime 必须分别标识；所有改动在新派生树/新 prefix，原产物冻结，不 commit/push，不改真实 Steam/系统/全局包。

## 需要纠正的规划前提

- 现有 CPU 绘制负载不支持“2D/轻3D游戏可玩”的结论，也不给游戏 FPS 外推。
- 合作式 C 实验依赖主线程 dispatcher；双缓冲不解决无安全点时 UI 停更。
- 720p off/on 中位数差 +4.297ms 不是纯 UI 因果成本，也不是未来驱动性能的严格上界。
- 22/27 是本轮帧身份采样结果，不是普适丢帧率。实时显示可用明确 latest-frame-wins 策略；正确性模式则要求逐帧 ACK。
- 零导出不是零拷贝；未来软件呈现可能仍需复制/读回，不预设 WSI 路线一定免读回。
- Steam 客户端发现、内容获取、启动/Steamworks 分开验证。当前资料不足以宣判整体路线不可行。

## 阶段 DAG

P0 回归与隔离基线 → P1 呈现架构决策 → P2 真实 HWND/GDI 闭环 → P3 单窗输入 → P4 真实应用试用。
R1 COW 机制诊断/修复与 P1–P3 并行；R1 通过后才开放非诊断可靠性验收。
S1 Steam 三环节核查与 P1–P3 并行；真实客户端变更须独立明确批准。
P4 图形 API 清单 → G1 选择软件 WSI / DirectDraw / D3D / GPU 路线 → G2 目标应用验证。

## P0：建立可持续回归入口（先做）

范围：新 scripts/runtime/session_v2/、tests/session_v2/、logs/session-v2/；旧 runner 不原地覆盖。
任务：
- 把必要的历史执行流程迁移为新入口：每轮唯一目录、拒绝已有目录、按 owned PID/进程组清理。
- 收据同时记录 target/runner exit、两层 timeout、模块完整 SHA、prefix、配置、清理对象及结果。
- 旧裸 killall 入口保持历史证据，不作为默认执行路径。
- 原 runtime 与 C 派生 runtime 分别做无 opt-in 对照；同一个 PE/负载/预算形成可比较基线。
测试顺序：先写“误杀旁路进程/覆盖旧目录/内外 timeout 混淆”的失败测试，再实现新入口并独立复核。
验收：专门启动的无关 sentinel 存活；旧证据 SHA 不变；退出/超时/异常三路均只清理本 session。
产物：运行协议、回归收据与新入口；不把历史 90 tests 当本轮新测。

## P1：呈现架构决策门，而非继续堆合作式补丁

并行候选仅做有界可行性实验，共用版本化 frame/ACK 合同：
A-copy：独立 AppKit 服务 + SOCK_STREAM length framing，真实 RGBA8 payload，不先赌共享内存。
C-decoupled：先核实 HVF 创建/执行/销毁线程约束及 fork/exec，再设计 AppKit 主线程与 guest 执行分离。vCPU 不跨线程迁移；任何新线程方案必须实测验证。
共同协议：surface id/generation、尺寸/pitch/format、sequence、slot 状态、RECEIVED/CONSUMED ACK、关闭/错误；guest 地址不可裸传给外部进程。
内存策略：优先受治理复制到 host-owned slot，先证明所有权正确，再考虑 pin/零拷贝。READING slot 禁止覆写；resize/unmap 使用 generation 失效。
候选目标（待确认）：720p30 起步；RGBA8 有效载荷 110.592 MB/s，60Hz 目标另为 221.184 MB/s。持续至少 30 秒并记录 p50/p95/p99、队列深度及帧龄。
验收：
- 正确性模式连续 1000 个变化帧 CRC/sequence/ACK 正确，无半帧、越界、重复消费。
- 实时模式明确 latest-frame-wins 丢弃策略，不强迫所有 producer 帧都显示；记录被替换序号和消费延迟。
- guest 三秒纯计算期间，host 仍处理预排定 UI/关闭事件；不以旧帧保持显示代替事件泵响应。
- host/guest 任一退出和连接中断均有界清理，无互等。
决策：只选一个满足正确性/响应性且改动更小的后端进入 P2。A-copy 达标即可采用；C 胜出须有真实收益证据，不默认优先 C。不达标先归因，绝不自动推导 hypercall 更快。

## P2：真正的 Wine 单窗 GDI 驱动闭环

范围：新派生 Wine frontend、host surface 模块、独立测试 prefix；不改 sealed null 配置。
先固定 user_driver_funcs ABI、surface 生命周期、Wine 锁/重入规则，再做最小回调集。
实现链：CreateWindow/WindowPos → host window id → Wine window_surface/flush → 动态像素 commit → host 消费 ACK → DestroyWindow。
去掉固定 GVA、专用 packet 作为应用前提；测试 PE 用普通 Win32/GDI API，不主动调用实验提交协议。
首版只做单顶层窗口、固定尺寸、opaque、明确格式转换；WSI/多窗/IME 本阶段不展开。
验收：普通 x64 Windows PE 的计数器/移动图形动态出现在对应 host view；可逐像素/序列绑定；持续 5 分钟；guest退出、host关闭、host异常均无残留。
系统窗口可见状态、自身 view 捕获、桌面合成/人眼确认分层记录；不把缓存 PNG 单独当屏幕呈现证明。需要人工确认时单列验证步骤，不自动申请全局权限。

## P3：单窗可交互闭环

实现键盘、鼠标移动/按键/滚轮、焦点、关闭消息；一个固定 Retina scale 策略起步，物理坐标与 Win32 logical 分开。
测试事件带序号，验证正确 HWND、按下/释放配对、失焦不粘键、关闭可退出；消息等待不得阻塞 AppKit。
验收：普通 Windows 小程序可以点击按钮、键盘移动对象、响应关闭；连续操作 10 分钟无死锁/资源递增。resize/DPI变化作为下一子门，IME/多屏/全屏另排。

## R1：正常 COW 可靠性线（并行，不再无限后置）

先制作 4KiB guest / 16KiB host 混合映射最小矩阵，区分 backing、邻页、MAP_FIXED、mprotect、跨进程/跨线程、unmap/remap。
必须同时满足：共享更新可见、WRITECOPY 不污染 backing/兄弟映射、邻页共享保留。
依据实测选择 overlay/backing 改造、受限 Wine 适配或 fault 级方案；不预设单靠“Stage-2写保护+复制”就覆盖全部语义。
修复在独立 runtime/Wine 派生树，回归通过后 gate 未设置条件下重跑窗口/GDI/ARM64+x64离屏。
验收：矩阵全部通过，且标准运行不依赖 ELFUSE_DIAG_SESSION_SHARED。未达成前所有应用结果标诊断级，不称通用可靠运行。

## S1：Steam 三环节核查（并行）

一：客户端发现与启动入口；二：Windows 内容获取；三：登录态/Steamworks/启动参数。
先做不触碰真实 Steam 的一手资料及离线分发客户端分析，版本化记录证据。无法由资料判定的行为列出具体动态实验，不据搜索片段下最终结论。
明确拆分“客户端下载”“安装到真实系统”“登录账号”“修改库/配置”，后三项须独立确认；用户凭据只由用户输入。
自备程序路径是开发验证通道，不取代原生 Steam 最终目标。Steam 接入结论不阻塞显示/输入实现，但决定最终发行方案。

## P4：真实应用试用；G1/G2：图形扩展

在 P2/P3 后选固定版本、公开源码、无复杂启动器的 Windows x64 GDI 应用，记录实际所需 API，覆盖启动/操作/保存/关闭。
可靠性验收依赖 R1；诊断门下测试只用于提前发现兼容缺项。
再选一个有明确图形 API 的真实应用/小型游戏：GDI、DirectDraw、D3D或Vulkan分别建覆盖矩阵。
只有目标需要时才实现软件 WSI、DXVK/vkd3d 链或硬件 GPU 桥；分别测试 acquire/present/同步/resize。音频按目标应用需求立项。
目标定义为“该版本该场景实测通过”，不以单游戏结果泛化“大多数游戏”。

## 团队与验收

角色：Lead负责方案/依赖/接受判定；呈现执行员负责P0–P3；runtime执行员负责R1；集成研究员负责S1；独立reviewer复跑关键负测与验收场景。
复用现有队员；P1两候选写入不同目录，禁止并发编辑同一runtime或Wine源码。每任务含Goal/Boundary/Constraints/Acceptance/Evidence。
执行时先各阶段规格确认，再拆TDD小任务；不得把本路线图直接当实现代码规格。实现者自检后由独立reviewer核验，Lead最后接受。

## 第一轮执行范围（建议）

只启动P0、P1的架构验证、R1映射矩阵与S1离线核查；暂不开完整显示驱动、GPU桥、WSI、全屏/IME/多窗。
第一轮输出必须回答：采用A-copy还是C-decoupled、正常COW的最小可修边界、Steam下一项需要验证的具体行为。
每个门最多两轮同假设实验；若无新证据，停止扩充探针，给失败定位/候选变更/成本再决策。
无固定工期承诺；P1/R1结果回来后按实际文件与回归面估计下一阶段工作量。

## 计划批准

本文为待确认的新路线图；未派发实现任务。确认后先创建第一轮任务书与独立review安排，所有后续产物写新目录，封存53项证据只读。
