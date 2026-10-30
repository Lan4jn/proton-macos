# PROJECT-STATUS：已验证成果、阻塞与复现索引

> Task145 收口快照，只整理已有验证，不新增功能或重新测性能。工作目录 /Users/mewcapoo/Projects/proton-macos-lab。每条结论通过下列路径绑定证据，完整SHA256见附录及logs/status-check/artifact-manifest.json。前缀仅便读，引用时用完整值。

**目前不是可用的macOS Wine显示驱动，也没有证实游戏、真实Steam或硬件GPU支持已完成。**已完成的是受限诊断环境中的补丁、可逆部署/离线包、CPU Vulkan离屏、Windows消息链、host自身view呈现与合作式C路线实验。

**零导出≠全链零拷贝。**C路线省去外部handle export，但present.m显式memcpy至NSBitmapImageRep。合作式UI会暂停guest，无syscall长计算会冻结UI。**这不是未来驱动的线程方案。**

## 第一层：已实测验证
| 成果 | 可引用范围 | 文件/收据绑定（完整SHA在附录） |
|---|---|---|
| pure-guard补丁 | pristine apply-check、三文件应用结果逐字节匹配；patched win32u=59a76b05、shipped winevulkan=2786ca6f；adea是实测结构/运行兼容基线，不假称官方唯一对应commit | sources/patch-release/wine-vulkan-reentrancy-guard-adea6cbac.patch、evidence-summary.json、apply-check.log、README.md、commit-message.txt；reports/patch-release.md |
| backend可逆部署 | 既有90 tests；fixture范围plan/apply/verify/rollback指纹恢复，VDF生成/扫描，不等于真实Steam发现 | scripts/backend/steam_plan.py；logs/compat-package/backend-tests.log；reports/compat-package.md |
| 离线包 | 约3.0GiB，90 tests+7自检，8107清单项（8105文件+2链接）；包内模块/VDF/扫描/回滚已测 | logs/compat-package/receipt.json、proton-macos-lab-arm64-diag/SHA256SUMS.json |
| ARM64离屏 | PE112377ef，count1/8点PASS，normal exit0、skip_draw exit21，64² framebuffer 2f69987b | sources/vk-offscreen-probe/vk_offscreen_arm64.exe；logs/vk-offscreen/receipt.json、framebuffer.raw；normal日志绑定run-l0u2l4b_ |
| x64离屏 | PEaba1c08c，FEX路径真实draw/readback，count1/8点PASS，framebuffer同2f69987b | sources/vk-offscreen-x64/vk_offscreen_x64.exe；logs/vk-offscreen-x64/receipt.json、normal_framebuffer.raw |
| Windows窗口链 | PEd6625afe真实CreateWindow/WM_PAINT/消息链，不代表宿主画面 | sources/win-window-probe/window_x64.exe；logs/win-window/baseline/receipt.json；reports/win-window.md |
| 外部host呈现spike | helpere0bd32e6，文件交接后真实NSWindow、自有view捕获4096像素一致，非Wine驱动 | sources/host-present-spike/presenter；logs/host-present/trial2/receipt.json；reports/host-present.md |
| 多帧CPU吞吐 | 既有9组负载，约1.22e8/3.36e8/5.32e8覆盖像素/s；轻载主要受submit等固定开销约束，不是硬件GPU速度 | logs/vk-throughput/summary.json、slopes.json；reports/vk-throughput.md |
| 显示路线设计 | A/B/C、M1–M4方案与判据完成；设计完成≠驱动已实现 | reports/display-driver-design.md |
| C路线内存/像素 | 当前elfuse3b146bbe+dylib8605a3b3，同进程受检guest范围直接读取、零导出；无水印4096/4096一致；720p排除pixel0后921599像素一致，pixel0单独核seq | logs/inproc-present/sealed-build-sha.json、sealedon/receipt.json、final-pixel-validation.json；reports/inproc-present.md |
| C路线线程/采样 | 720p off/on readback median差+4.297ms（本spike受限代价），去冷UI约51Hz，22/27水印身份采样，缺5帧18.52%；纯计算3007ms时UI停更3004ms | logs/inproc-present/frame-analysis.json、frame720onmainonlyfinal/frame-sampling.csv；reports/inproc-present.md |
| C路线负测 | 默认worker进入exit86；WAIT永久notready有界exit88；跨页不足/尺寸/metadata错均fail不部分显示 | reports/inproc-present.md及其定位的frameonstrictfinal2/finalwaitnotready等receipt；复现索引inproc-wait-negative |

以上图形实验依赖ELFUSE_DIAG_SESSION_SHARED=1诊断门；它牺牲标准文件私有COW，不代表生产ABI/正常映射已正确。

## 第二层：未验证或明确阻塞
| 项目 | 当前状态与边界 | 文件/SHA绑定 |
|---|---|---|
| 标准COW、16KiB/4KiB粒度 | BLOCKED；不可把诊断shared映射当Linux标准私有映射；生产候选未解除阻碍 | logs/ro-section/phase_a_receipt.json、production.patch；reports/ro-section.md、private-cow-decision.md |
| Wine null driver | Graphics=null、CreateWindowSurface FALSE；WM_PAINT成功不是宿主显示，不是简单“窗口隐藏” | reports/win-window.md、display-driver-design.md；窗口receipt |
| WSI/显示驱动 | 未实现Wine到macOS驱动/WSI。C spike为draw→readback→host commit，非vkQueuePresentKHR | reports/inproc-present.md、display-driver-design.md |
| 输入/DPI | 输入、光标、多屏、完整DPI桥未验证；旧DPI96探针不等于DPI支持 | reports/win-window.md、display-driver-design.md |
| 硬件GPU | 当前设备为llvmpipe CPU；硬件GPU/Metal路径及性能未验证 | reports/vk-throughput.md、vk-offscreen.md |
| 真实Steam机制 | fixture VDF/扫描/回滚已证；真实客户端发现/启动/Steamworks仍存疑待测 | reports/compat-package.md、包receipt |
| C可见性 | isVisible=1、自身view像素已证；occlusion持续0，无遮挡/人眼见屏UNKNOWN | reports/inproc-present.md、final-pixel-validation.json |
| C线程/多窗口 | 合作式主线程safe point会阻塞guest；新窗口/new surface会否重复付500–741ms初始化UNKNOWN | reports/inproc-present.md、frame-analysis.json |
| 多进程、unmap/pin | 静态buffer范围实验，不证明通用生命周期、并发页表或多进程驱动 | reports/inproc-present.md及其runtime.patch |

不能把这一层写成“仅剩优化”。原runtime81803322与C派生3b146bbe不同，未擅自迁移vCPU/HVF线程绑定。

## 第三层：风险与不可外推
- **零导出不是零拷贝**：dylib有memcpy，AppKit可能再复制。证据inproc-present.md/present.dylib。
- **CPU水印不是shader产物**：仅身份追踪。无水印4096/4096；64²水印只比较4095非水印像素，720p为921599，pixel0独立断言。证据final-pixel-validation.json。
- **回读代价不是未来驱动性能**：+4.297ms含本spike回读、CPU拷贝、观测及合作式UI，单次独立run差不纯归因UI，也不能因此宣称可接受。直接合成实现可能不同。证据frame-analysis.json。
- **单帧/启动总时长不是FPS**：首初始化与稳态P95/max分开，不拿81s总启动时间作UI频率；CPU-only吞吐不外推游戏。证据vk-throughput.md/inproc-present.md。
- **身份缺失不是恒定图像内容丢失**：旧27帧全同像素，6个seq采样不代表丢78%视觉内容。新水印18.52%仍非普适游戏掉帧率。证据逐帧CSV。
- **无互等不等于无阻塞**：UI由guest主线程dispatcher safe point驱动；UI占用时vCPU暂停，无syscall则UI停更。需要独立UI调度、同步/双缓冲、生命周期及HVF验证。证据inproc-present.md。
- **当前SHA可核≠历史无干预**：历史进程清理不可审计，见下节；不能反推当时无其他elfuse受影响。

## 危险/不可直接重放的历史入口
| 源码入口 | 实际调用 | 固定目录/覆盖行为 |
|---|---|---|
| scripts/runtime/vk_offscreen/run_vk_offscreen.py:80 | killall -9 elfuse | 固定logs/vk-offscreen，重写顶层stdout/stderr/receipt/raw，test root复用 |
| scripts/backend/run_adapter_vulkan_config.py:64 | killall -9 elfuse | 固定logs/adapter-vulkan-config/runs/<label>，已存在trial会rmtree重建 |
| scripts/runtime/cow_recovery/run_fair_gate_comparison.py:37 | killall -9 elfuse | 固定logs/cow-recovery/fair_comparison/<label>，已存在trial会rmtree重建 |

三处无-u、无PID白名单、无进程组限定。SIGKILL影响面是调用者具发信号权限的所有同名elfuse，不是任意进程，也不越过OS权限。capture_output结果未持久化，receipt不记受影响PID。

**历史批次的进程清理不可审计。**不等于像素/SHA数据无效；现存字节仍可核，但“当时无其他elfuse误杀”没有证据。不能原样直接重放这些入口。本卡不修改旧runner。

**前向规则：后续任何脚本禁止裸killall；必须按进程组或记录PID清理，并在receipt写受影响PID列表和结果。新run用唯一run-id/独立目录，固定证据目录只读。**

### 历史复用/覆盖审计边界
详logs/status-check/history-integrity.json、process-kill-audit.json（附录SHA）：
1. ARM存活run-6njm0gi2、run-vwmj5xtt、run-l0u2l4b_三个独立run-id，说明root复用。**证据需按run-id绑定，顶层文件不可单独引用。**
2. 顶层normal stdout SHA1de0da87与vwm/l0相同；顶层stderr SHA1eb31bfd仅与l0相同。因此当前normal副本绑定l0；vwm stderr=eeee6bff仍独立保留，不把两次性能混算。
3. 这不证明某raw已被后续错误内容覆盖。当前framebuffer仍匹配receipt原存2f完整SHA，未发现足以认定最终像素结论受覆盖损坏的证据，不因此降级当前像素结果。较早run的完整receipt关联不可凭同stdout重建。
4. adapter当前receipt引用6个raw/status文件存活且mtime不晚于receipt；COW gate_on的3个同样如此。未发现已证“当前引用指向后来不同raw”冲突；rmtree删去的更早历史不在快照内，不能声称从未覆盖。
5. **mtime是弱证据**：touch、复制、解包都可改变，不晚于receipt不证明内容当时正确。强内容绑定须由receipt原本记录的hash支持。本卡新算hash只冻结当前快照，不追认旧时已有hash链；ARM framebuffer另有原receipt hash可核，两者分开。

## SHA一致性：并列冲突、不同构建与引用优先级
分类清单另见logs/status-check/conflicts-classified.json；consistency.json核对202条显式路径/语义字段/冻结索引/具名报告表绑定，147个基础路径另加扩展绑定哈希。不是全仓历史穷举；11个未绑定的报告full SHA单列unbound_report_hashes，不自动判一致或冲突。

### Snapshot drift：1条已解释
同一路径sources/elfuse-inproc-present-derived/build/elfuse：
- 历史final-build-sha.json：cdcd276bef99adbf621bb4146c70a58799e891caa33587b907ea7b05551e9217。
- 当前实文件、sealed-build-sha.json、evidence-sha256.json：3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926。
- inproc-present.md记录帧实验后增加“无DYLIB opt-in最先return”的最终改动。**当前部署引用3b；历史帧实验保留cdcd，不重写旧SHA或声称旧run用了新构建。**

### 不同构建/对象：不是同产物冲突
原elfuse81803322与C派生3b、ARM64 PE112377ef与x64 PEaba1c08c、shipped原win32u4f6013fa/pristine自建96de5f0a/guard patched59a76b05为不同对象。以路径和receipt角色区分，不按basename混为一物。

### 真正未解释的同产物冲突
**🔴 本次明确绑定的当前有效产物中，未发现尚未解释的SHA冲突。**不是全仓零冲突声明。未来若同一语义版本/路径SHA不同且无构建记录，必须在此标红并暂停该项引用，不能静默择一。

补丁evidence-summary的dlls/...相对路径应绑定nested Wine根sources/wine-pin-adea/patched/wine-adea6cbac9d00bb22910145354d00c463fcf3afc/，三文件均匹配；初始审计错误绑定lab根造成的“文件缺失”不是产物冲突，初始输出保留为consistency-before-path-normalization.json。

FINAL.md保留时间线旧“尚未渲染”等段落，不能抽作最新状态；后续诊断门下离屏receipt已覆盖这些阶段结论，但不能反推标准COW或完整图形已完成。

## 不应被引用的历史结论
| 项目 | 为什么失效 / 正确替代 |
|---|---|
| 169万逐入口日志轮性能/FPS | 整轮时序被观测污染，性能作废，仅留采样/内容行为；用聚合计数版frame-analysis.json |
| metadata packet 24B offset direct dump/log | 新schema应56B，旧dump不能证明内存一致；legacy三u64 header仍24B合法。用frame720onmainonlyfinal正确dump+PNG |
| 30s超时=死锁 | 冷启动/预算不足不证明互等；读长预算治理运行的target_exit/timeout/raw阶段 |
| 78%视觉内容丢失 | 原同像素图的seq采样，不等于内容缺失；用新CPU水印逐帧身份表，仍不外推游戏 |
| 中位UI约1ms所以成本可接受 | 隐藏首帧303–741ms和720p P95/max、guest暂停及无syscall冻结；必须分层报 |
| 单帧或启动时间当游戏FPS | 非连续稳态；用真实多帧窗口分布且保留CPU-only条件 |
| view缓存PNG=无遮挡/WSI/零拷贝 | 不证合成器输出，存在memcpy且无WSI；分层报告 |
| 不同clock直接相减的一程延迟 | 时基未校准；用同clock ACK RTT，未校准一程UNKNOWN |
| 审计最初3个dlls文件缺失 | 审计器路径基准错误；正确nested Wine根hash已一致 |
| 固定root顶层stdout代表唯一run | 多run stdout可同而stderr不同；必须run-id+stderr/receipt/hash绑定 |

## 复现索引与本卡自检
    python3 -I scripts/repro_index.py
    python3 -I scripts/repro_index.py --json
    python3 -I scripts/repro_index.py --item arm64-offscreen

11项覆盖补丁apply-check、backend、ARM64/x64离屏、窗口、兼容包、C路线及负测、host呈现、COW和吞吐。每项标类型/命令/期望退出/完整SHA；默认只打印。只读raw+receipt/hash复核首选，独立目录实跑次选。

ARM/x64次选复用无killall的既有x64 runner，以Python常量只重定向实际PE与新logs/status-check/repro-*；ARM时内部x64名称只是标签，架构须核实际PE/SHA。**这些命令本卡只做shell语法检查，没有执行，不新增验证结果。**其他实跑均用新label。

目标退出与runner退出分开：WAIT负测runner可exit0但receipt target exit88。重跑须读target_exit/timed_out/cleanup/raw/rollback，不只看Python最后一行。

index-tests.log：6 tests OK（必需覆盖、SHA、仅打印、无全局kill/delete、shell语法不执行、源码无执行API）。不重跑既有90/7测试冒称新测。示例repro-index-example.txt/repro-index-output.json。本卡仅写本报告、scripts/repro_index.py、logs/status-check，无commit/push、不改runtime/Wine/backend/原产物。

## 附录：当前产物与证据完整SHA256
机读artifact-manifest.json；本报告/索引自身另封存delivery-sha256.json，避免自引用。

| 文件 | SHA256 |
|---|---|
| sources/patch-release/wine-vulkan-reentrancy-guard-adea6cbac.patch | a22655b6f7b77edabbf0796fe6ad9d613a01cb2282dd27b1d09c29cadc7443a2 |
| sources/patch-release/evidence-summary.json | 3927f2d153f46fa551ba955a3c70c3e0c0293474a3aecfa231928517ceb680fd |
| sources/patch-release/apply-check.log | b8f91590b5bdaf04ee701f6c0cfe8ec2ff57c58501afa876a2b8f8a4d387a495 |
| scripts/backend/steam_plan.py | 104fcda4f31f5e92e871c7d77fda28f630eda58c232bf5d911a4176ce8d0d0aa |
| logs/compat-package/backend-tests.log | 241a29e43017b247fbfba972d68866d35a012b969dfe37bec92c71eb850cfb15 |
| sources/vk-offscreen-probe/vk_offscreen_arm64.exe | 112377ef135b5bb3d240646b665b1747bc21078ec8ee2272208bec2c1ae11e22 |
| logs/vk-offscreen/framebuffer.raw | 2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050 |
| logs/vk-offscreen/receipt.json | f9f94c7b000dca0f831520dc6f75631ad95f3615a297036b20909bfeb7b3cac3 |
| scripts/runtime/vk_offscreen_x64/run_probe.py | 0302f2443ead54f7474ca6fd3df97379651d9bf5b0a65cdd792a1d8c07ff74ce |
| sources/vk-offscreen-x64/vk_offscreen_x64.exe | aba1c08ccbc7c8f4569c7177cc96032a7baf87c3b255506f1c8f5a452a0a1ae9 |
| logs/vk-offscreen-x64/normal_framebuffer.raw | 2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050 |
| logs/vk-offscreen-x64/receipt.json | c81601ffa4612604b986d87980f29ce5ef3417130ceab35f2c4905009167ac30 |
| sources/win-window-probe/window_x64.exe | d6625afe061295e9c02525a15214054c5615eca8db6b5ac348f5c570e7c02365 |
| scripts/runtime/win_window/run_probe.py | d9f7865efe8d293350f3fcb7925ce1eb893ab0ee3e0afe1a3ca6d3ec6b8dff67 |
| logs/win-window/baseline/receipt.json | 8ae572f4f8656730b9821e1315cfecc6d5abbb4c765cfb1275e16917d01a5436 |
| scripts/backend/build_compat_package.py | e219baa14b5ab974dd7f990ef79602acfba4c662c7a7a94684f7c15d84a25d8a |
| logs/compat-package/proton-macos-lab-arm64-diag/SHA256SUMS.json | 12190148816a97965eca4996e2e679603bc5dbb4e71b27bb019ae9da2a16690d |
| logs/compat-package/receipt.json | 564d494e4e731307a8fdb9fc65c6ccd57b0353f79d42456cc943a57f59e73a6d |
| sources/elfuse-inproc-present-derived/build/elfuse | 3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926 |
| sources/inproc-present-dylib/present.dylib | 8605a3b37168bc2fdc0ceb264162b6f13ae08ea18d97f3709d9b7f867c3e3746 |
| scripts/runtime/inproc_present/run.py | 764a5e93a76e6ade6d535bfc1cfb24feeccae9abcc85c39485cc974681dbab1b |
| logs/inproc-present/sealedon/receipt.json | 749b15bbb992d0188d407b9bd0df2f09b9aac14346f642a6513c118e3b7b3c8e |
| logs/inproc-present/finalwaitnotready/receipt.json | 1645ce0720727df063182297e5e02f0a6a006bdbe413028791aee4a93ee6c788 |
| sources/host-present-spike/presenter | e0bd32e60d93468d9b07dc43862be302b7485a7114b9b810117ba36943deccf0 |
| scripts/runtime/host_present/run_spike.py | 0d0348929c8ac41e84ca1f24bb867c3c9ee24ef933f56bda90664e5eac8eb765 |
| logs/host-present/trial2/receipt.json | 1aa3cb0bf1be47d5e365b9dfe90fc422ee7f2c26e33041c5ec4141769f1ba647 |
| logs/ro-section/phase_a_receipt.json | 5ac228f31d6c8f1c51e8a042284337a875295be37e9b1afded19458e051484fe |
| logs/ro-section/production.patch | 27bb2c82502ac75517bfc900cc6c026e60d201cc3eabefeb7e901a6e3ef4dccf |
| reports/ro-section.md | 051a91d0427c50e6f6c166dbe12646f019719225ce48fe5c7026a1fa36552a75 |
| reports/vk-throughput.md | b97a54dfe30ca6daacbdb9593a93aa0a62a5295ca8f601933653332a9478b04f |
| logs/vk-throughput/summary.json | 505615bbc7d2f7ca08d9da7e91e174829ba2a41e8439881353592132b4d919e9 |
| logs/vk-throughput/slopes.json | 66389e5043cd4ce6bc3963fb0cab4cc21e52f747f65f4480048f446a845246d8 |
| sources/patch-release/commit-message.txt | da330d650c7a6b15f0495a37d9bbbbb3635b9ac988ea94d97091fc22d269b0af |
| sources/patch-release/README.md | bb90e048f4e9723333b0ed70785a6d6f3d464860d0df1c7e9973d008428962a7 |
| sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so | 59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed |
| fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/winevulkan.so | 2786ca6f5f440821972e91a371e609d2d482597a8b6d75bcf02e287f83eea9ab |
| reports/vk-offscreen.md | d3933c6ae769b113806613d67fddcca84eee4c769d03b0cc8e6b76b232533864 |
| reports/vk-offscreen-x64.md | de0350376a144f725d7b741221a4b48aaa58e34c2145359106acacb0d855b5fc |
| reports/win-window.md | 086a6b3bc6c92ef95dc5d9838a4524737da3a28de41d1b74dde584f8afd38612 |
| reports/patch-release.md | d83c5440ea6695cc37f41c858ed48f50a9b89d49a3009098638a1b17223b9e9b |
| reports/compat-package.md | a9636710fda3ae136282402b0d5a1086b3d0b00ca3ef904f936de65e5d2448ac |
| reports/host-present.md | 4b7325ca0a9dbeceff908c57d1ba4548dd9cecba48ad95b600b601826fc80874 |
| reports/display-driver-design.md | 451ae174644790874b5514165be48eccc7c9fbf9e4d146cd6fb4b681b41958fe |
| reports/inproc-present.md | c9fc2cf8625ad98a0309d814e52cb155dbf06d4caa3466685335f305f1e11a9b |
| reports/private-cow-decision.md | 5e9c68c873638d33be781957fabcee9d7e5fbd20f84129cfadb457580002a95e |
| logs/inproc-present/sealed-build-sha.json | b43207341cdda22273d98009c7a98ffe1d2627a3075c6f7285a7a49057d43595 |
| logs/inproc-present/final-build-sha.json | 38020d4300ec678508c64e88ccc3f0f0aa3051c8fc96c38f1c7222990197fb99 |
| logs/inproc-present/frame720onmainonlyfinal/frame-sampling.csv | 65fd5a1cc29d24d7e0a28f6a50094d340eefe99c11c13c9d988a34933ac2c11e |
| logs/inproc-present/frame-analysis.json | dc9f1304ebb06227627fe0b445e53c56a57fb81a7c06ebeb68bf603b34c0d357 |
| logs/inproc-present/final-pixel-validation.json | 726f983686eabdcc703c8280fc484b83ef22cf906a99db16dcee1ff701e25153 |
| logs/status-check/consistency.json | 7e3400d4aa8c150ffc626e9b2e514007ee410c8114c1b862a01f1c8f2e0bf079 |
| logs/status-check/process-kill-audit.json | 7f54f9229f844cf684a74ad0f822f601ffbe6aa8cedc986c44bce1057f78a6d3 |
| logs/status-check/history-integrity.json | bbcf12d4a2455a751414cbbf862f11b5e62f752d2982d3b34289d923bbbd823e |
