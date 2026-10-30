# Task144：C 路线进程内 guest 像素呈现 spike

## 最终结论（分层，不是驱动）
- **同进程直接读取 guest backing：PASS**。通过guest_ptr_bound将指定GVA解析成host pointer，dylib在同一elfuse进程直接memcpy读取；无FD/句柄导出、SCM_RIGHTS、新hypercall或外部服务。
- **64²无水印像素一致：PASS**，guest自己写入固定静态buffer，3个phase的自身view截图与直接读取全部4096像素/16384字节一致，SHA2f69987b。
- **720p真实draw/readback+CPU身份水印：非水印921599像素一致，pixel0单独等于seq编码**。不能宣称水印后全图等于未改源。水印不是shader输出，仅帧身份追踪。
- **NSWindow与自身view绘制：PASS**（windowNumber有效、isVisible=1）；**无遮挡/人眼见屏UNKNOWN**：本轮记录occlusion=0，包括有限150ms事件泵后仍0。不把view缓存PNG当WindowServer整屏确认，不申请全局截图权限。
- **线程模型适合真实驱动：FAIL/不适用**。UI只在主线程dispatcher安全点合作式执行，执行UI时guest该vCPU暂停；纯计算无syscall约3秒时UI也冻结约3秒。
- 多窗口/新surface是否重复付初始化、输入、正常COW、WSI、游戏兼容均UNKNOWN。

**这不是未来驱动的线程方案。**未来至少需要独立于guest执行的UI调度角色（AppKit必须宿主主线程）、锁或双缓冲/发布消费协议、不能阻塞vCPU、受治理的buffer生命周期及事件回传。不能任意把AppKit搬到worker；vCPU迁移前还须验证HVF创建/执行线程绑定。

## 设计、opt-in及权限/生命周期
仅派生sources/elfuse-inproc-present-derived，原sources/elfuse-once-panorama2-derived只读。唯一runtime源码差异为src/syscall/syscall.c，main/core launch及既有所有hook门控保持不变。新增诊断调用位于syscall_dispatch入口，不改原syscall语义；无opt-in时最先return、不加载dylib、不检查其余实验参数。原runtime仍SHA81803322。

- ELFUSE_INPROC_PRESENT_DYLIB：显式非空绝对dylib路径；RTLD_NOW|RTLD_LOCAL和dlsym查inproc_present_tick。此变量不设置或空串即关闭。
- ELFUSE_INPROC_PRESENT_GVA：必填指定guest VA，通过实际ELF符号/PE linker map取得，禁止假定guest VA就是host pointer。
- 默认64x64 RGBA8，legacy packet为ready/seq/phase各u64+16384B；READ范围16408B。帧循环新布局另有width/height/pitch/payload_bytes，56B header；FRAME_LAYOUT显式启用。
- WIDTH/HEIGHT范围1..1920/1..1080，长度经范围校验计算；metadata必须和W/H/pitch/payload_bytes逐项相同。读范围guest_ptr_bound(... MEM_PERM_R, length)，avail不足绝不截断或部分显示。
- WAIT_RANGE：默认无等待、未映射立即exit86。仅PE早期加载允许显式1..180秒等待范围及ready magic，超限exit88。由主线程safe point检查deadline，若guest完全不返回则还有独立runtime整体超时；不是任意线程后台实时timer。不能把永不ready变成成功或无限挂起。
- MAIN_ONLY：默认不设置，worker进入保护性exit86；显式设置后worker原子计数并return，**永不调用插件**；主线程才做UI。前者是保护，后者是新约束，不能混称“worker安全运行UI”。这些presence型flags以unset关闭，字符串0不当作关闭。

指针仅回调中借用，复制到局部NSBitmapImageRep后不保留guest backing引用；范围内为测试静态buffer，不munmap、不跨worker写入。没有实现通用pin、不解决其他guest线程并发修改页表；权限检查不等于任意对象生命周期保证。把bitmap复制/颜色标记/合成算入回调，**不是全链zero-copy**。

## 构建与复现
    sh sources/inproc-present-dylib/build.sh
    python3 -I scripts/runtime/inproc_present/run.py newoff off
    python3 -I scripts/runtime/inproc_present/run.py newon on
    python3 -I scripts/runtime/inproc_present/run.py newwaitnegative waitnotready
    python3 -I scripts/runtime/inproc_present/run_frames.py newframe720onmainonly

新label保护旧raw；run.py从llvm-nm读真实guest packet地址，run_frames.py从PE linker map读preferred地址；PE若重定位后地址不同，WAIT会有界失败，不能据首选地址猜测成功。frameoff标签不加载插件，frameon无mainonly保留严格worker负测。帧run180s内层/200s外层仅测量配置，不是生产设置。

系统clang构建AppKit/QuartzCore dylib（Mach-O arm64）；guest静态AArch64 Linux ELF用ld.lld；真实帧producer是Windows ARM64 PE，用同已验收shader与Vulkan代码派生，lld-link /base:0x30000000（不能用ARM64不支持的/fixed）；未改Wine/GPU后端。make派生runtime使用既有签名/entitlements流程，build log中git来源信息缺失提示保留，不捏造commit。

最终SHA见sealed-build-sha.json。最终runtime在帧实验所用构建基础上只增加“无DYLIB时提前return”，enabled路径相同；帧raw保留当时final-build-sha记录，sealedoff/sealedon对应最新构建。性能数据来自各轮实际raw，不假称所有历史轮使用同一个SHA。

## 心跳 vs 无syscall计算：线程实测
测试guest把编译时嵌入的真实2f帧复制进自身.bss，再发布ready；并非host把像素塞入guest。阶段1：200轮getpid/nanosleep1ms；阶段2：约3秒纯计算（读取cntvct、不svc、不断更新seq）；阶段3：再200轮心跳。显式COMPUTE_BEGIN syscall只在计算段之前，期间没有UI进入机会。

所有UI callback记录pthread_main_np=1，vCPU创建/运行线程原样未迁移。部分syscall可能走runtime快路径而不进此dispatcher，精确依赖是**主线程可触发的dispatcher安全点**，不是保证每个Linux syscall都会触发UI。

| 轮次 | 首次UI init ms | 去首回调median ms | 去首P95 ms | 去首max ms | 心跳1最大gap ms | 心跳3最大gap ms | 无syscall计算ms | 最大UI停更ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| on3 | 303.330 | 1.078 | 3.593 | 9.001 | 326.986 | 15.032 | 3009.092 | 3007.967 |
| on4 | 583.949 | 1.122 | 1.583 | 8.080 | 592.143 | 15.907 | 3008.329 | 3003.589 |
| finalon | 587.362 | 1.084 | 1.658 | 8.740 | 608.576 | 20.063 | 3008.900 | 3004.382 |
| sealedon | 535.035 | 1.066 | 1.566 | 6.783 | 551.015 | 16.767 | 3007.055 | 3004.171 |

303.330ms尖峰就是on3第一个初始化/建窗/首次颜色view捕获回调；on4加150ms首帧事件泵后首次583.949ms。去首最大均为个位数ms，未观察到周期百ms尖峰。phase切换自身view截图也计入回调：sealedon的切换回调见analysis.json，并非无成本。所有窗口快照occlusion一直0，**没有观察到occlusion切换，不能将尖峰归因于切换**。只能定位为首次初始化一揽子调用，未单独profile每个AppKit子调用，不把它断言全是shader或颜色转换。

16ms节流的设置上限62.5更新/s，还受safe point频率限制。sealedon心跳两个阶段约37.405/49.234更新/s（首阶段含初始化，不叫稳态FPS）；无syscall纯计算停更3004.171ms，计算本身3007.055ms。**无互等死锁不等于无阻塞**：最大guest心跳gap551.015ms直接显示首UI抢占；纯计算能继续但UI饿死。

## 真实draw帧循环：不是WSI present
现有Graphics=null且无显示驱动/WSI，所以本卡不虚构vkQueuePresentKHR。新PE每帧真实vkCmdDraw+submit+fence，readback组再map/invalidate/memcpy实际像素到packet，普通stdout写自然进入safe point；host合作式提交到自有view。三组draw/readback/clear、首帧/warmup/稳态及原始QPC序列都保留。

这是 **draw→readback→合作式host commit**。读回与CPU复制属于本spike，不代表未来驱动能直接合成的路径。报告“该负载下合作式提交的实测成本”，不把它当驱动可用性能；也不宣称测得的数是未来性能严格数学上界（调度/资源使用不同），只是含额外回读/拷贝/截图的受限实现代价。

### 保护负测与观测污染
- frameon/最终frameonstrictfinal2：CreateDevice阶段worker进入，INPROC_FAIL callback_not_main、exit86、无完整BENCH_FRAME，说明默认保护有效；不把它报FPS。
- frameonmainonly第一轮逐入口日志169万行：**本轮不计性能，仅计采样/内容行为**。所有当轮时序/FPS不用于性能结论。
- 后续用atomic聚合、每秒/退出snapshot，避免百万行日志。仍有观测开销，不给纯UI因果结论。
- main-only是“worker永不调用插件”，不是默认保护被关闭。未改变vCPU绑定。

### 64²/720p独立帧组
| 实验 | 分辨率 | readback稳态median ms | p90 ms | max ms | 首readback帧ms |
|---|---|---:|---:|---:|---:|
| frameoff | 64×64 | 1.133 | 7.255 | 9.137 | 6.184 |
| frameonmainonly2 | 64×64 | 1.375 | 2.524 | 9.888 | 671.501 |
| frame720off | 1280×720 | 10.442 | 18.625 | 31.294 | 16.277 |
| frame720onmainonlyfinal | 1280×720 | 14.739 | 26.194 | 37.095 | 768.260 |
| frametaggedonmainonly | 64×64 | 1.388 | 1.673 | 12.845 | 688.611 |

720p off median10.442→on14.739ms，独立run差+4.297ms；包括hook检查、聚合计数、guest读回/CPU水印、实际UI回调等，非随机多次对照，不能纯归因于UI复制。不是“64²只多约0.9ms所以可接受”。初始UI成本显著落入第一readback帧，不混入后20帧稳态。

| 有效呈现实验 | UI首次回调ms | 去首median ms | P95 ms | max ms | 去首观察更新率/s | commits | unique seq采样 |
|---|---:|---:|---:|---:|---:|---:|---:|
| frameonmainonly2 | 665.698 | 1.149 | 1.396 | 1.396 | 57.900 | 27 | 5 |
| frametaggedonmainonly | 684.432 | 1.186 | 2.457 | 2.457 | 53.778 | 27 | 4 |
| frame720onmainonlyfinal | 741.155 | 5.962 | 16.439 | 19.195 | 51.011 | 27 | 22 |

720p去首P95 16.439ms、max19.195ms已接近/超过单个60Hz帧预算，不宣称合作式成本可接受；同一进程后续没有再出现741ms级初始化，但新窗口/新surface是否重付初始化UNKNOWN。单窗口单surface证据不外推多窗。

### 主线程触发频率与worker入口
最终720p实际UI进程pid34263：主线程entry记录从1/worker0起，最终snapshot主线程14,350次、worker跳过602次；记录span82.522s含初始化，约173.893 entry/s不等于渲染阶段频率。其他进程分别保存于frame-analysis.json，不把重复snapshot相加。

像素ready到完成这段active窗口：主线程可触发插件入口3,233次/1.643s，约1,967.889 entry/s；去冷UI实际约51.011更新/s，47次更新/22个不同seq。没有证据表明这段loop因主线程完全没有syscall而饿死，主要采样原因见下表。全run主线程长gap含启动/等待，不与不同clock域的mach时间戳相减作单向延迟。

跳过worker统计是入口次数，不是线程数量；raw逐进程INPROC_STATS与最终snapshot保留。INPROC_ACTIVE phase4后可能重复打印相同总结，analyzer去重，不按重复次数累计。其他游戏主线程若长计算无safe point，仍将如前面的3秒对照一样冻结；有present/sync不自动保证足够频率。

## 帧身份采样：逐帧表与原因
原固定红三角27个commit内容相同，6/27只表示采样的seq身份，不是观察到78%视觉内容丢失。新实验仅在guest回读后给pixel0写CPU seq水印，让每帧身份可区分；其余像素仍实际Vulkan读回。**CPU水印不参与渲染正确性结论。**

720p最终27个水印commit，22个seq曾进入host view，缺5个18.52%；64²水印27个仅4个身份采样。UI重复画最后一帧不算新内容帧。每次INPROC_DEFER明确记录16ms门未到；被该门跳过后producer覆盖同一slot，导致中间身份永久未呈现。单slot覆盖是当前实现没有ACK/双buffer的真实约束，不是guest渲染失败。

若某seq既无UPDATE也无DEFER，analyzer会标“未观察到eligible main callback，原因UNKNOWN”，而非凭空说被节流。本次最终720p缺的5帧均有DEFER证据，因此归因为节流后被single-slot覆盖；不声称这些场景与真实游戏有同等丢帧率。

| commit seq | 720p采样 | 64²水印采样 | 720p原因 |
|---:|---|---|---|
| 1 | 是 | 是 | 进入host view |
| 2 | 是 | 否 | 进入host view |
| 3 | 是 | 否 | 进入host view |
| 4 | 是 | 否 | 进入host view |
| 5 | 是 | 否 | 进入host view |
| 6 | 是 | 是 | 进入host view |
| 7 | 是 | 否 | 进入host view |
| 8 | 否 | 否 | 16ms节流后被单slot覆盖 |
| 9 | 是 | 否 | 进入host view |
| 10 | 是 | 否 | 进入host view |
| 11 | 是 | 否 | 进入host view |
| 12 | 否 | 否 | 16ms节流后被单slot覆盖 |
| 13 | 是 | 否 | 进入host view |
| 14 | 是 | 否 | 进入host view |
| 15 | 否 | 否 | 16ms节流后被单slot覆盖 |
| 16 | 是 | 否 | 进入host view |
| 17 | 是 | 是 | 进入host view |
| 18 | 是 | 否 | 进入host view |
| 19 | 是 | 否 | 进入host view |
| 20 | 否 | 否 | 16ms节流后被单slot覆盖 |
| 21 | 是 | 否 | 进入host view |
| 22 | 否 | 否 | 16ms节流后被单slot覆盖 |
| 23 | 是 | 否 | 进入host view |
| 24 | 是 | 否 | 进入host view |
| 25 | 是 | 否 | 进入host view |
| 26 | 是 | 否 | 进入host view |
| 27 | 是 | 是 | 进入host view |

逐帧原始CSV/JSON：各frame*/frame-sampling.csv/json；不根据“commit数/UI更新数”简单算内容遗漏，因为有重复显示同seq。样本短、无输入、无WSI，所以更新率不是扫描输出Hz或游戏FPS。

## 像素证据和错误边界
- sealedon：无水印64²，phase1/2/3的guest-direct/raw/PNG解码与原source全部相等2f69987b，独立Pillow -I验证；没有全局截图权限。
- 最终720p：phase1 PNG解码和正确56B header后的guest-direct完全一致；排除pixel0后921599像素逐字节等于bench-readback.raw，pixel0=[1,0,128,255]单独符合seq1。原真实渲染raw SHA e3fcea5f；水印截图不再使用原source SHA冒充相同。
- metadata版早期frame720onmainonly/frametaggedonmainonly的PNG正确，但guest-direct dump/log曾沿用24B偏移；这些direct dump无效，已在frame-png-validation.json标出，不当内存正确性证据。最终frame720onmainonlyfinal已修正为56B，独立匹配。
- on2：重编译guest后旧固定GVA未更新，exit0但无ready/无截图，不算呈现成功；后从nm动态解析。永久notready负测防同类静默误判。

| 最终负测 | 结果 | 具体行为 |
|---|---|---|
| invalid | exit86 | 地址范围加长度溢出/address_config |
| invalidrange | exit86 | unreadable_range avail=0 |
| crossrange | exit86 | 起点可读但全范围跨未映射页，avail6600<16408，拒绝部分读取 |
| badlayout | exit87 | W/H/pitch/payload metadata不匹配，dimensions_payload_mismatch |
| baddimensions | exit86 | WIDTH=0非法，尺寸/长度配置不接受 |
| waitnotready | exit88约1.517s | WAIT=1秒，范围可读但magic永不ready，明确timeout而非成功/无限等 |
| frameonstrictfinal2 | exit86 | 默认worker进入callback_not_main，MAIN_ONLY未设 |
| sealedoff | exit0 | 无dylib加载/NSWindow，原guest可完成 |

长度由有效W/H及RGBA4B算出，packet length不精确或metadata payload/stride不同立即fail；跨页只读部分没有降级显示。WAIT只为早期映射，不用于遮掩错GVA、错schema。暂无任意恶意guest的内存生命周期防护，不能当通用安全接口。

## 需要下一步而不是包装成成功的部分
1. occlusion持续0：自身view像素可证，但无遮挡/人眼可见仍UNKNOWN。最小下一步独立查NSApp激活/宿主会话及WindowServer列表，不靠篡改截图补证。
2. 协作式UI抢主线程且无syscall冻结：需要宿主主线程独立事件循环、受治理guest执行线程与HVF绑定验证，异步双buffer/ACK不阻塞vCPU；本卡不擅自搬线程。
3. 单slot覆盖/16ms节流使帧身份跳过：后续要明确mailbox/drop/backpressure策略和frame ownership；不是加速计时器就解决生命周期。
4. 窗口/输入/多进程/WSI正常COW仍UNKNOWN。MAIN_ONLY只是让worker不碰UI，不实现跨线程/跨进程通用显示驱动。

## 交付与证据
sources/inproc-present-dylib：guest.c/frame.h、present.m/dylib、真实frame_probe_arm64.c/exe、build.sh/build_frame_probe.py与linker map。
sources/elfuse-inproc-present-derived：独立派生构建，原runtime不动。
scripts/runtime/inproc_present：run.py、run_frames.py、analyze.py、analyze_frames.py。
logs/inproc-present：各run raw、receipt/plan/安装回滚、analysis.json、frame-analysis.json、逐帧采样CSV、final-pixel-validation.json、final-build-sha.json/sealed-build-sha.json、runtime.patch/source-diff、tests-red/green/final.log、evidence-sha256.json。

全部正测exit0、无runtime timeout、cleanup_errors=[]；帧安装使用原plan/apply/verify/rollback且指纹一致。该结论不把负测exit86/88解释成失败部署。保留所有初次失败和性能作废日志，不删除证据。没有完整Linux VM、新Wine驱动、新WSI或游戏支持声明。
