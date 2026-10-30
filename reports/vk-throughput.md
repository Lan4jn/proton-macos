# Task142：llvmpipe 连续真实绘制吞吐测量

## 结论先行
仅报告本环境的简单单色三角形离屏负载。轻载下提交/同步与固定每帧成本占主导：20帧720p clear median 5.538ms甚至略高于draw 5.211ms，不能写成“720p游戏能跑158FPS”。120帧后draw median4.033ms、clear1.889ms，仍是很轻负载而不是复杂游戏模型。

真正增加覆盖后：100个重叠实例在720p draw median75.150ms、p90 90.637ms，1080p median115.355ms、p90 160.406ms；这两个固定负载下CPU路径明显不适合要求平滑高刷新交互的目标。它不证明所有游戏不可用，也不证明硬件GPU是任何场景都必须：只说明若目标包含本轮这种反复覆盖量和30/60Hz要求，当前CPU配置已经不满足，需要GPU加速或减轻实际工作量；能否用GPU解决、与硬件GPU差距均UNKNOWN。

本实验不包含宿主窗口显示、Wine driver、输入或swapchain，不外推游戏性能。gate=1具有已知COW诊断语义代价；CPU为llvmpipe LLVM23.1.1，LP_NUM_THREADS=1。

## 构建与来源
在新目录派生已验收x64 Vulkan源码及相同SPIR-V，不修改旧source/产物。
- sources/vk-throughput-probe/generate.py → vk_throughput_x64.c。
- sh sources/vk-throughput-probe/build.sh，Clang x86_64-windows，llvm-lib x64，lld-link零CRT。
- file：PE32+ console x86-64 for MS Windows。
- 轻载PE SHA：c9bce00bc3e7491f28684c17ddce8a3afafa770c6d07c4fed4e02a93f3de07ce；保留logs/vk-throughput/light-c9bce00b.exe。
- 支持实例/1080p的最终PE SHA：c35b10b7b16b90a66d35913d3c086e4fa922b4390d117cf5a15b0a14cdbf3f82。
- build.log/build-heavy.log记录实际编译及SHA；失败构建日志单独保留。

## 负载定义与计时边界
同一VkPipeline、同一顶点/片元shader，每个测量组1首帧+5warmup+N稳态+1计时外验证帧；三组顺序draw→readback→clear。首组draw是本进程首次执行，后两组首帧不再是冷JIT，不作三次冷启动。pipeline创建单独计时；驱动/磁盘shader cache未清除，因此pipeline冷启动仅是进程局部定义，非全系统冷缓存。

- draw：每帧vkResetCommandBuffer/reset fence、begin、renderpass clear、bind、真实vkCmdDraw(3,instanceCount)、end、queueSubmit、wait fence。没有像素读回。
- readback：同样真实draw，外加image→buffer、transfer→host barrier、fence、map整个allocation、invalidate、实际memcpy完整RGBA至静态snapshot、unmap。计时内不写磁盘。
- clear：相同renderpass clear及bind/submit/fence，但没有vkCmdDraw，是固定/清空基线，不是渲染成果，也不是独立于Vulkan的纯CPU循环。
- 验证帧：每组额外提交，draw/readback画对应实例，clear无draw；计时外读回8点验证并写raw，host另做全图颜色计数和draw/readback SHA一致检查。
- 输出逐帧raw start/end/ticks放在组结束后，打印不计入单帧；连续区间FPS同时包含帧间少量循环开销，报告以该连续区间rate为准。未包含初始化、末尾验证写盘、宿主显示/vsync。
- 总draw/submit数按组帧数严格核对：20帧时54 draw/81 submit，120帧时254/381，各3次验证；重载draw次数指API调用，每次instanceCount个三角形。

重载固定单色opaque、无depth attachment/深度测试，无blend；每个实例使用相同几何，约18%屏面积重叠，不是100个不同复杂模型。假定每实例都独立光栅；20→100增幅没有变平，但未使用硬件计数器证实每个片元，驱动批处理/优化未排除。不能把实例斜率简单命名为不含填充成本的纯每实例CPU开销。

## 预算与环境diff
**为测量目的放宽预算，非生产配置：内层elfuse --timeout180s，外层run_isolated200s。**外层留20s治理余量，不会先于内层正常预算结束杀进程。每组先测首帧+5pilot，再按max pilot×2安全系数和10s组预算选择稳态帧数；最低20，若20也放不下则明确BENCH_ABORT_BUDGET exit70而不是撞timeout。实际20与120完整组未发生自动缩减；20帧是Lead在初始化风险后主动批准的测量样本缩减，不伪称120完成。

已验收offscreen环境与本轮差异逐项：
- 同elfuse81803322、win32u59a76b05、shipped winevulkan2786ca6f、同基线prefix只读复制、同patched-full布局+share/default_pfx；gate1不变。
- 最终复用全部ELFUSE_* OBSERVE/FIXTURE/ONCE诊断变量、同WINEDEBUG +timestamp,+winstation,+vulkan,+explorer,+driver,warn+vulkan，host VK_ICD_FILENAMES相同。
- guest LD_LIBRARY_PATH同lavapipe/usr/lib:sysroot/usr/lib，VK_LOADER_DEBUG=all不变；显式新增LP_NUM_THREADS=1及同路径VK_ICD_FILENAMES作为guest参数。它们是测量约束，不假称原成功runner文本完全相同。
- PE及目标路径为新benchmark；args增加分辨率/帧数/instance选项；实际argv和env逐轮在runtime-plan.json/receipt.json中完整保存。
- 为调整硬编码90秒而不改backend，本任务runner调用现有build_plan，复制其argv仅把--timeout改180，再按原steam_handoff逻辑注入guest env，调用原run_isolated200；没有把host LD_LIBRARY_PATH用于动态加载。
- 保留plan/apply/verify/源目录移开/rollback安装模式，新独立prefix，不写真实Steam。

## 每组完整分布
rate=稳态帧数/连续QPC区间秒，不是游戏FPS。单位ms；first不含pipeline创建。20样本与120样本独立进程，不混合成一组。

| 实验/尺寸/实例/N | 组 | 首帧 | min | median | p90 | max | 连续区间ms | 实测轻/重负载rate (/s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| small20 64×64 I1 N20 | draw | 130.196 | 0.852 | 1.596 | 7.924 | 9.675 | 60.648 | 329.771 |
| small20 64×64 I1 N20 | readback | 1.658 | 1.105 | 1.484 | 8.326 | 10.322 | 59.249 | 337.559 |
| small20 64×64 I1 N20 | clear | 1.031 | 0.842 | 1.036 | 1.244 | 5.945 | 26.089 | 766.612 |
| p720measure 1280×720 I1 N20 | draw | 145.465 | 3.518 | 5.211 | 10.400 | 15.194 | 126.513 | 158.086 |
| p720measure 1280×720 I1 N20 | readback | 9.060 | 4.213 | 9.151 | 12.678 | 17.830 | 187.762 | 106.518 |
| p720measure 1280×720 I1 N20 | clear | 11.588 | 2.801 | 5.538 | 14.491 | 16.573 | 145.049 | 137.884 |
| smalllong 64×64 I1 N120 | draw | 114.080 | 0.690 | 1.087 | 2.098 | 8.158 | 185.661 | 646.339 |
| smalllong 64×64 I1 N120 | readback | 3.714 | 0.380 | 1.119 | 4.410 | 10.079 | 198.060 | 605.875 |
| smalllong 64×64 I1 N120 | clear | 1.159 | 0.769 | 1.108 | 6.077 | 12.126 | 261.244 | 459.340 |
| p720long 1280×720 I1 N120 | draw | 123.481 | 2.488 | 4.033 | 10.984 | 14.906 | 692.506 | 173.284 |
| p720long 1280×720 I1 N120 | readback | 3.517 | 2.885 | 6.141 | 14.694 | 38.676 | 946.209 | 126.822 |
| p720long 1280×720 I1 N120 | clear | 3.164 | 1.516 | 1.889 | 6.822 | 14.444 | 367.810 | 326.255 |
| smallinst100 64×64 I100 N20 | draw | 95.277 | 1.901 | 2.318 | 6.535 | 9.527 | 68.132 | 293.546 |
| smallinst100 64×64 I100 N20 | readback | 2.644 | 1.711 | 1.893 | 6.347 | 9.197 | 54.308 | 368.269 |
| smallinst100 64×64 I100 N20 | clear | 16.630 | 0.972 | 1.205 | 2.100 | 10.476 | 38.535 | 519.002 |
| p360inst100 640×360 I100 N20 | draw | 107.025 | 27.962 | 35.906 | 48.225 | 62.245 | 769.701 | 25.984 |
| p360inst100 640×360 I100 N20 | readback | 32.832 | 22.826 | 34.281 | 46.527 | 51.975 | 739.633 | 27.040 |
| p360inst100 640×360 I100 N20 | clear | 10.615 | 1.121 | 1.450 | 6.409 | 14.373 | 62.048 | 322.332 |
| p720inst100 1280×720 I100 N20 | draw | 182.034 | 61.148 | 75.150 | 90.636 | 116.123 | 1588.771 | 12.588 |
| p720inst100 1280×720 I100 N20 | readback | 98.213 | 63.292 | 87.831 | 119.721 | 130.262 | 1841.446 | 10.861 |
| p720inst100 1280×720 I100 N20 | clear | 2.410 | 2.081 | 3.675 | 7.104 | 13.017 | 87.715 | 228.011 |
| p1080inst100 1920×1080 I100 N20 | draw | 183.191 | 71.246 | 115.355 | 160.406 | 217.793 | 2506.991 | 7.978 |
| p1080inst100 1920×1080 I100 N20 | readback | 83.020 | 63.053 | 110.038 | 144.493 | 149.983 | 2229.896 | 8.969 |
| p1080inst100 1920×1080 I100 N20 | clear | 8.592 | 2.507 | 4.918 | 9.098 | 12.945 | 114.688 | 174.386 |
| p720inst20 1280×720 I20 N20 | draw | 121.299 | 14.654 | 22.684 | 27.854 | 28.536 | 456.850 | 43.778 |
| p720inst20 1280×720 I20 N20 | readback | 15.080 | 16.781 | 25.434 | 33.687 | 37.154 | 511.168 | 39.126 |
| p720inst20 1280×720 I20 N20 | clear | 4.036 | 1.640 | 2.127 | 6.019 | 11.014 | 65.050 | 307.456 |

readback组独立，不混算draw FPS。组间差值仅是分别测量的中位数差，可能受调度噪声为负；例如64²120帧readback-draw +0.032ms、720p120帧+2.108ms，720p百实例+12.681ms，但1080p百实例readback甚至略快，不能据此说读回没有成本。组顺序未随机化、每配置仅一次长/短样本，不给统计置信区间或可保证持续帧率。最长单组稳态仅数秒，非长时间热稳态/温控实验。

## 500实例主动预算停止
720p I500首帧410.646ms，5个warmup分别340.880/346.071/417.400/308.070/392.496ms；max417.400ms，以2×安全系数20稳态约16.7秒超10秒组预算，主动exit70 BENCH_ABORT_BUDGET。wall123.067s、timed_out=false、cleanup_errors=[]；只有pilot，无BENCH_DONE/稳态FPS/末尾raw，不发布500实例稳态rate。降至100实例的完整成功组已存在，因此没有必要反复重跑撞预算。

## QPC保真与独立时钟
QPC frequency固定10,000,000Hz，100ns量子；完整组每帧ticks>0、end-start=ticks、跨帧时间单调，20组78个、120组378个记录。样本tick有大量不同值，不属于单帧不可分辨的粗粒度时钟。若检测到零值/非单调/计数不完整则analyzer报错不生成有效统计。

| 实验 | QPC总区间ms | GetTickCount64区间ms | QPC/第二时钟 | 最小frame ticks | 不同ticks数量 |
|---|---:|---:|---:|---:|---:|
| small20 | 425.736 | 470 | 0.905821 | 8418 | 78 |
| p720measure | 918.548 | 960 | 0.956821 | 28008 | 78 |
| smalllong | 1089.947 | 1110 | 0.981935 | 3799 | 367 |
| p720long | 2545.742 | 2584 | 0.985194 | 15159 | 378 |
| smallinst100 | 379.297 | 366 | 1.036331 | 9323 | 78 |
| p360inst100 | 2293.108 | 2330 | 0.984167 | 11209 | 78 |
| p720inst100 | 4996.087 | 4995 | 1.000218 | 20814 | 78 |
| p1080inst100 | 6732.362 | 6794 | 0.990928 | 23997 | 78 |
| p720inst20 | 1586.729 | 1595 | 0.994814 | 16397 | 78 |

短20帧轻载两钟差约4.3–9.4%；120帧降至1.48–1.81%。720p百实例差0.022%、1080p0.91%，与较长区间更一致。独立clock仅做交叉检查，QPC不是绝对真值；上述间隔包含pilot、组间打印/验证，而连续rate按各组首尾QPC计算。

## 正交斜率：限定模型而非通用填充率
先扣除各配置自身clear中位数，再取有限差分。假定覆盖像素数为host验证raw中红像素数×instanceCount；这不是硬件fragment计数，可能受边界/优化影响。
- 固定100实例，64²→360p：新增覆盖4,075,000个、净draw增33.343ms，模型有效1.222e8覆盖像素/s。
- 360p→720p：新增12,441,600个、净增37.019ms，3.361e8覆盖像素/s。
- 720p→1080p：新增20,736,000个、净增38.963ms，5.322e8覆盖像素/s。
三个斜率差异大、非线性，不压成一个“真实填充率X”。只能说此opaque重叠三角的增量量级约1.2e8–5.3e8覆盖像素/s，包含执行/内存/调度及采样差异。
- 固定720p，I20→I100：扣clear后净增50.918ms/80实例，约636.474微秒/新增实例。这个数**仍包含每新增实例165,888个覆盖像素的光栅成本**，不是与分辨率无关的每实例CPU开销。
正交实测证明工作量增大导致显著成本，但没有足够独立重复与统一线性模型分离纯顶点/instance固定开销和纯填充；两项净参数精确值UNKNOWN。slopes.json保留输入与公式。

## 初始化/非测量占比
“outside”是wall减pipeline与整个benchmark loop，**不是已经精确识别的wineboot耗时**；包含Proton/Wine/FEX加载、桌面初始化及最后资源清理/退出等。render loop含三组首帧/warmup/steady/验证/打印，不能拆成全为GPU执行。

| 实验 | 整体wall ms | pipeline创建ms | benchmark总loop ms | 其中draw稳态ms | 其中readback稳态ms | 其余outside ms | outside占比 |
|---|---:|---:|---:|---:|---:|---:|---:|
| small20 | 111217.210 | 3.681 | 425.736 | 60.648 | 59.249 | 110787.793 | 99.614% |
| p720measure | 118035.337 | 6.169 | 918.548 | 126.513 | 187.762 | 117110.620 | 99.217% |
| smalllong | 119895.496 | 0.946 | 1089.947 | 185.661 | 198.060 | 118804.603 | 99.090% |
| p720long | 117764.000 | 1.145 | 2545.742 | 692.506 | 946.209 | 115217.113 | 97.837% |
| smallinst100 | 120327.046 | 1.032 | 379.297 | 68.132 | 54.308 | 119946.717 | 99.684% |
| p360inst100 | 125909.909 | 0.891 | 2293.108 | 769.701 | 739.633 | 123615.909 | 98.178% |
| p720inst100 | 141523.690 | 1.431 | 4996.087 | 1588.771 | 1841.446 | 136526.172 | 96.469% |
| p1080inst100 | 128004.135 | 0.866 | 6732.362 | 2506.991 | 2229.896 | 121270.907 | 94.740% |
| p720inst20 | 123632.219 | 0.986 | 1586.729 | 456.850 | 511.168 | 122044.504 | 98.716% |

- wineboot单独耗时：UNKNOWN，没有完整匹配的start/end标记；不能把118秒剩余全部叫wineboot。
- explorer-desktop：trace可见get_desktop_window starting explorer；仅以边界记录，不把其他子进程同时启动区段重复加到总时长。具体marker在summary.json。task140已对另一次窗口探针拆出该路径同步等待，不能直接挪作本轮精确时长。
- pipeline创建：上述实测；首帧draw独立保留，冷JIT大于稳态，但不保证每个缓存首次编译。
- draw/readback循环：表中明确区间；readback内部copy vs submit/fence没有额外细分timer，不能把readback整组都叫memcpy耗时。
- outside仅表明优化优先级不能只看帧率：本轮94.7–99.7%墙钟在测量循环和pipeline之外；需要进一步分层profile后才能归因具体函数。

## 正确性、失败与约束
完整9个配置均exit0/no timeout/cleanup_errors=[]，原rollback成功且前后指纹一致。draw/readback各末尾8点PASS；host检查全图只包含红与深蓝，clear全深蓝；64²raw保持2f69987b，720p draw/readback同e3fcea5f5010b720d345afac8e47736ca98b29a14b19cf27dcea52e66287c431；其余SHA详各capture-validation.json。重载重复覆盖最终像素不变是预期，不以结果不变推断没有draw，draw实例数来自真实Vk调用与源码。

首次small4/small5在120秒预算vkCreateInstance/desktop初始化未完成，无BENCH_FRAME、无FPS。最后raw的explorer阶段、timed_out与清理结果保存，不当作吞吐失败；按Lead扩预算180/200并复用完整环境后完成。small/small2/small3为prelaunch API参数错误，未执行guest且原manifest均回滚。错误构建/旧收据保留。部分早期receipt因runner复用曾含window阶段判定，后据独立analyzer更正为throughput verdict，旧receipt-before-throughput-verdict.json保留，不更改原stdout/stderr。

5项统计单测PASS（tests-final.log）：正常统计、缺/重帧、零tick、错误draw count、缺完成标记均覆盖。原backend/runtime/已验收探针/真实Steam保持只读，无commit/push。

## 交付索引与复现
- scripts/runtime/vk_throughput/run_probe.py：独立安装、计划修正180、run_isolated200、清理。
- analyze.py：严格完整性和时钟检查；finalize.py：全图检查/summary/slopes。
- logs/vk-throughput/summary.json、slopes.json、finalize.log、tests-final.log、build-heavy.log。
- 各label/probe.stdout.log为完整逐帧start/end/ticks原始序列，probe.stderr.log为运行原raw；statistics.json、capture-validation.json、receipt.json保存派生检查；runtime-plan.json记录实际argv及env。
- p720inst500保留主动预算停止原标记，不算完整成功组。

示例（需新label保护证据）：python3 -I scripts/runtime/vk_throughput/run_probe.py p720inst100repeat；标签含720/360/1080选择分辨率、inst20/100/500选择实例，long为120稳态否则20。每组仍有pilot预算。现有finalize.py汇总固定已完成label，后续实验自行追加再复核。

## 分层最终判定
多帧真实draw/fence与验证读回PASS；特定负载稳态分布已测；读回为独立组且受顺序/噪声影响；纯硬件GPU差距UNKNOWN；游戏性能UNKNOWN；是否所有目标都必须GPU UNKNOWN。重覆盖负载在当前CPU配置明显变慢是已证事实，不用轻载rate作乐观游戏估计。
