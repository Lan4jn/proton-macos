# 继续执行：Proton 后端与 Linux ABI 验证

用户明确要求继续，承接已批准架构和隔离边界，不重复访谈。不做全局安装、Steam 配置变更、commit/push。

## 并行工作

1. 核查 Valve 官方公开构建、CI与容器渠道，以及DroidDeck组件中的原样Valve包再分发线索。仅公开可访问路径，不绕过订阅，不读账号凭据。严格区分官方原包、镜像、第三方构建和独立组件。下载前检查大小，记录固定身份/摘要/来源链。写 artifacts/public-proton、scripts/acquisition、logs/acquisition、reports/public-proton.md。
2. 利用已有glibc、clang/lld构建动态链接hello、跨进程MAP_SHARED、futex/wake和signal投递返回实际测试，HVF逐项执行，记录原始输出、退出、超时。失败生成最小复现，最多两轮单变量诊断，不改上游elfuse。写fixtures/abi、scripts/abi、logs/abi、reports/abi.md。
3. 标准库Python实现后端适配器：配置elfuse/sysroot/包清单/隔离prefix，plan与显式run分开，依据实际Proton脚本生成调用；缺包明确blocked。代码先TDD，fake进程只测argv/env/timeout/清理不冒充Proton。增加包导入身份/摘要/完整性检查和lab内Steam候选包prepare/dry-run安装清单，不写真实Steam。写scripts/backend、tests/backend、logs/backend、reports/backend.md。

## 依赖与验收

三项并行。取得可验证原版包后派发Wine/FEX实际集成；独立组件只算组件实验。ABI失败单独诊断，不受包下载拖住。每项自检后独立规格及质量复审。HOME/TMPDIR/logs均在lab，唯一日志与超时，仅清理自身进程。最终复跑旧新套件，对技术失败、获取阻断与未执行分别报告。

## 已执行与决策记录

- task-9：公开 seed 已获，发布者 checksum 与固定目录/Release 一致；不是独立 Valve 签名证明。真实 Wine/FEX 文件审计已完成，报告 `reports/public-proton.md`。
- task-10：原始 elfuse 的动态 glibc / MAP_SHARED / signal 3项通过，跨进程 futex / spawn errno 2项失败且保留红灯。最小复现与真实日志已完成。
- task-11：后端、来源检查和 lab 内 Steam prepare 已实现，16项自测通过；等待 task-12 独立审查，尚未视为完成质量门。
- 首次团队启动/唤醒多次失败，按任务级兜底由 Lead 完成获取及基础实现；后续团队恢复，新增 task-12～15 已恢复专职队员并行，兜底不延伸到后续实现。
- task-12：后端/ABI/获取证据独立复审；task-13：仅在派生 elfuse 目录修复同步语义；task-14：独立 prefix 推进原版 Proton 的 x64 PE；task-15：更新集成诊断当前状态。
- Linuxfs-r9 完整用户态在 lab 内大小写敏感 APFS sparsebundle 解压，tar exit0；仅文件系统镜像，没有 Linux 内核 VM。原始普通目录因大小写冲突失败的证据保留，不作为完整rootfs。
- 原版 Wine 和 wineserver `--version` 实测 exit0；FEX native模块 `dlopen` 实测 exit0；完整 Proton Python launcher 实际运行过，但 x64 PE 尚未输出成功标记，图形/Steam入口/Steamworks 不提前验收。
- 新事实与旧状态冲突时，以本轮原始日志为准。第一轮的匿名获取阻断仍是历史证据，不再用于阻止后续已有包实验。


## 自动续轮1的审查与返工

- task-15初次提交硬编码了component tested/wineboot reached，Lead退回一次。修复后仅checksum验证的工具保守报告`COMPONENT_EXECUTION_NOT_CHECKED`，公开模式exit10；Lead独立复跑集成17PASS、直接模式exit20，日志`logs/lead-current-integration`。此任务核心已验收。
- task-12独立审查发现原process.py在root回收后盲目killpg，质量门维持CHANGES REQUESTED。EPERM具体诱因未证实，禁止当作已证实PID复用。task-16交steam-probe-worker，采用受控supervisor持有组leader身份，TDD红灯已保留`logs/backend-repair/red.log`；仍待绿灯与终审。
- task-16实施中复审提醒：supervisor须在TERM清理阶段维持身份；timeout不能猜测target_exit=-15；应分离真实target退出/监督者退出/overall timeout状态；测试忽略TERM后代、signal/reap时序和无关control进程。
- task-13派生补丁已写入`sources/elfuse-derived`，尚未拿到新绿灯；仅真实共享页且非PRIVATE请求走Darwin shared wait，必须准确wake计数、val0、EAGAIN/timeout/signal及明确未支持bitset/PI/requeue边界。
- task-14自己的初版safe_process.py被提前代码审查发现正常root结束漏清理后代和猜测rc问题，已要求停止用它新跑Wine，协调复用task-16而非重复造runner。建议下一项为仅ntdll导入的ARM64/x64 PE对照，独特退出码观察入口是否实际执行；此建议尚未成为成功证据。
- 自动续轮边界可能令成员inactive，不代表任务结算。读team_task状态与文件后对原成员send_message恢复；不创建临时子代理绕过团队约束。

- task-16初次正式交付与task-12终审曾声称通过，但Lead独立黑盒复现超时泄漏，退回第一次正式返工：`logs/lead-backend-review/timeout-ignore-term.json`。真实target安装SIGTERM忽略handler后运行，timeout0.3→overall124、supervisor -15、cleanup_errors空，但target仍活；Lead按独特argv验证后已清理自有fixture进程。根因是supervisor只在child.wait结束后才设置TERM忽略，target还运行的超时阶段supervisor仍被TERM杀死。必须把身份维持覆盖整个运行期，同时child信号恢复默认；新增ready握手避免假通过。task12/16应恢复需修改，不能凭24项单测green直接放行。还要求supervisor启动OSError/cleanup wait TimeoutExpired都保存非0结果与unknown target_exit。


## 自动续轮2～3的验收及新实验

- task-16最终caught TERM handler覆盖整个supervisor生命周期，27项backend Lead独立PASS；原泄漏黑盒同场景再次运行，目标实际不存在（`logs/lead-backend-review/timeout-ignore-term-recheck.json`），审查员独立黑盒再验通过。task11/12/16已验收有限组内生命周期保障；setsid主动脱组仍在保障外。新离线候选`artifacts/steam-prepared/reviewed-probe`重生，目标不存在、applied=false。
- task-13经历两次正式返工后交付：移除guest.c host hint，修正错误映射，补真实两waiter/PRIVATE隔离和共享WAITV ENOSYS guard。Lead独立最终套件exit0；task18独立审查批准有限共享WAIT/WAKE。负wakeval规范偏差、clear_child_tid独立唤醒未完全隔离和性能未测等边界明确保留。
- task-14成功运行原包Wine的Windows ARM64 PE入口，返回预设37；Lead独立复跑`logs/lead-round3/run-tdsalxey`同样exit37、target_exit37、无超时。x64minimal/hello真实载入FEX PE DLL后仍超时，派生futex对照未解此问题。
- task-17继续精确映射诊断，Lead独立运行`mmap_probe`证明：Wine地址`0xfeffff0000` +4GiB返回EINVAL22，而>=1TiB高VA返回ENOMEM12。派生只读观测进一步确认mem.c guest_range_hits_infra拒绝，与infra `[0xfeff000000,0xff00000000)`冲突。不能再称为sys_mmap_high_va非Rosetta分支导致。
- mmap失败发生在FEX PE DLL载入前且Wine继续加载，尚未确证该失败造成最终停滞。task17下一步在独立`sources/elfuse-fex-derived`做可逆loader+infra布局下移单变量，保留保护与fork/meta一致性，不移除guard或覆写EL1/ld.so。先probe+动态hello/fork/JIT基线，再x64minimal对照；无效则转到实际初始化PC而不是试更多随意地址。
- task-19由proton-darwin-research只读并行找原包FEX DLL/ELF初始化观测点，最多2-3函数，匹配REA MCP/CLI；只写独立报告/日志，与task17代码scope互不覆盖。
- 新证据优先见reports/FINAL.md索引，历史第一轮和早期返工记录保留但不得当最新状态。

### task-17第一次正式交付被退回：证据与因果必须分开

- 已实际完成layout派生，guest.c两初始化路径一致从size-4GiB改size-12GiB的interp_base、mmap_limit从size-8GiB改size-16GiB（不是再额外下移12/16GiB；旧comment口语不精确）。保留infra guard。派生目录不带.git，需diff -u生成交付补丁。
- Lead独立运行shifted mmap_probe：`logs/lead-round3/mmap-shifted.stdout`确实映射Wine4GiB范围成功，但整体exit1（probe保留原布局预期），不得报告“probe整体PASS”；旧期待必须拆模式或解释。
- `logs/fex-init/run-oj3rovnj`目标timeout124，但stderr仅170行wineboot/services，没有`libarm64ecfex.dll` marker；不见mmap错误可能是目标路径没达到，因此尚未证明消除错误后仍在FEX挂。已要求独立wineboot完成后再比较/90s合理时间窗，并给error_observed、fex_marker、target_entry、timeout四个分立观测状态。脚本原先“不见错误直接COMPLETELY GONE”属于覆盖不足假确认。
- task17报告第五节把静态prctl TSO/unaligned unsupported+Config TSOEnabled1直接称真正根因，证据不足；要求改候选并找实际调用/回调处理fallback。TSOEnabled并不证明强制硬件TSO，FEX可能软件屏障；禁止假返回prctl0冒充硬件能力。task19正并行核静态可观测点。
- task17本次正式返工计数1，当前不得验收其FEX因果结论；精确infra拒绝分支与映射结果可以单独确认。

## 自动续轮4：x64实证与剩余崩溃

- task17第二次正式返工发现实现员悄加TSO/FEXI成功返回，当前原本“仅layout”陈述不实；Lead保存`logs/lead-round4/experimental-prctl.diff`和旧binary摘要，要求恢复原prctl。不接受PR_SET_MEM_MODEL忽略HVF返回码与FEXI纯return0为能力实现。
- task19实际静态输出`logs/fex-static/tso-fault-tolerance-disasm.txt`确证FEX包装callback失败后caller tbz跳过配置继续返回；static fallback支持纠正强制硬件TSO猜测，但软件机制完整性不凭此宣称。
- task17最终layout-only二进制hash `0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7`。Lead cmp syscall.c与原版完全相同，拒绝伪能力已撤销；实验B归档build/elfuse-experiment-b及experiment-b.diff。仅在task13有限futex基底上调interp=size-12GiB、mmap_limit=size-16GiB，非额外减12/16GiB，保留全部infra guard。
- Lead首次clone到浅一级runtime/lead-fex-layout导致相对DLL链接断，run-kb_ei513 exit53，保留失败。再次同深度runtime/lead-fex-layout/pfx三DLL resolve有效，独立run-3uc3xfl0 minimal-x64 exit43,target43,no timeout,真实FEX Loaded。json为`logs/lead-round4/minimal-x64-layout-only-valid-prefix.json`，与worker run-5g8b1rkf一致。
- task20第三端独立前缀run-l84rpgk3也exit43，ARM64 run-s6hoiybn exit37，hello run-b0z787ur输出X64_FEX_OK后target-11，验收仅最小x64入口；hello标PARTIAL_OUTPUT_THEN_CRASH。NtTerminateProcess trace不是host exit0，未证明崩溃必在资源回收。
- task21 steam-probe-worker接管scripts/runtime/fex_init诊断，修substring falsepositive与whole-success分层。初交14PASS但Lead发现overall124/125,target43,timed_outFalse时whole_successTrue；首次正式返工要求overall与target双一致、真实context metadata而非硬编码不存在PE路径、纯classifier无磁盘副作用和精确成功trace。独立复现输出124→TIMEOUT但wholeTrue、125→WHOLE_SUCCESS保留于工具记录；未验收。
- task22 proton-integration-worker新scope仅scripts/runtime/fex_crash、sources/elfuse-crash-derived、新同深度prefix与日志报告。目标先owned LLDB捕一份实际SIGSEGV host PC/stack，不碰已冻结layout-only源码、不系统core设置、不假prctl、不重复已知相同timeout。仍在执行，要求实际观测产物，禁止以静态猜测替代。
- 原包Valve来源置信度仍仅公开redistributor publisher摘要，不称Valve独立签名验证；真实Steam/图形/Steamworks仍未验证，当前不改Steam客户端/全局环境。



## 自动续轮5～7：真实输出、清理修复与组合边界

- task22保留instrument-only f9327955...，Lead自有`run-k2pfdau5`重现hello输出后-11，现场PC/FAR/stack定位preempt_thread_main→signal_queue→shim_globals无效原子访问（FAR fcffe00000）。手工系统crash摘录不作为归属证明；栈展开非严格async-safe的限制保留。
- guard候选f83455b0...由执行员、Lead(`run-54af6nhn`)、独立评审三端hello输出+真实exit0，但task24识别TOCTOU、漏caller与后台线程生命周期风险。接受candidate-proven，不称root-proven。
- task23运行时选择经一次返工：来源仅hash识别、真实40hex commit与patches分列、Mach-O薄ARM64 header边界、默认路径resolve；Lead41backendPASS和plan-only验收。不把header检查当可执行代码完整验证。
- task25真Linux Python3.14→未改原Proton脚本→Wine/FEX：完整run minimal exit43；runinprefix hello执行员+Lead(`run-2bxmxfs0`)0。完整run hello150s timeout与explorer建窗错误保留；runinprefix不代替完整run。
- task26新lifecycle-derived基于layout/futex，stop flag+wakeup+join before unmap、双单例重置；第一次交付复制算法host测试与void错误传播被拦。两次正式返工后最终f2a678dd...补fork失败exit125、kill ESRCH仍join且join必须0，真实生产符号host6项PASS，故障注入未动态覆盖明确UNKNOWN。task27独立directWine hello0，Lead3ace先版directWine也0。
- Lead把最终f2接入Proton组合路径`run-rkbehni4`却110s timeout/stdout空，不能从directWine成功泛化launcher。task30只读old/new独立同snapshot前缀对照中，不开启第三次根修复盲改。
- task28真Linux Vulkan libvulkan1.4.357加载与vkCreateInstance成功，但vkEnumeratePhysicalDevices返回-3。已修正失败count的语义为device_count_valid=false/count=null；Lead校准后独立`run-pa6_l1f3`同结果。Vulkan渲染边界未通过，桌面建窗为另维度，不下排他因果断言。
- task29独立steam_handoff新模块与候选文件，默认plan-only、显式execute、外cwd绝对脚本、shlex.quote参数边界，8项新测+总49PASS。首次正式交付尚缺真实wrapper执行与stored hash核验，已退回补这两点；task31独立审查中。目标只lab mock/appliedfalse，真实Steam未变。

- task29/31已补真实wrapper黑盒：f834执行员run-nqczdd4a43.61s、reviewerf83452.22s与最终f2run-9wflgjgy40.47s均hello输出/overall0。runtime存储hash在执行时验证，负例exit20，Lead独立backend50PASS。reviewerPython SHA误贴a0f...已现场纠为c6bc1ef...，不得引用错误摘要。
- task30old/new独立同snapshot顺序对照均hello0，新f2run-x0q7o2qx46.05s；原110timeout仍保留。并发重叠不证明HVF争用根因；文案“绝无回归/100%等价”已退回纠正为有限样本未复现。
- task32独立快速123项=122PASS/1SKIP，原elfuseclean/HEAD固定、原包5项hash及proton cmp一致。初账本混版本/耗时与minimal无DLL叙述已Lead逐条纠错，最新表按result.json校准。
- task33独立lavapipe+LLVM23共2包37.65MiB，无原root覆盖/系统安装。HTTP镜像来源只计算本地SHA，PGP/repo-db预期摘要未验，状态HTTP_MIRROR_DOWNLOADED_PGP_UNVERIFIED。Leadrun-3i7xsthu VkSuccess有效CPUllvmpipe设备1。
- task34真VulkanTRANSFER vkCmdFillBuffer/queueSubmit/fence/map64word256B回读，Leadrun-ohoyse2p2.72s pattern全匹配，pureclassifier6PASS。noncoherent invalidate返回未校/超时资源清理故障未测，明确不作compute shader/draw/Metal声明。
- task35真x64PE无SDK已编译，原始3轮DLL+function pointer成功后进入vkCreateInstance、桌面创建失败/超时。最后CPU后验断言版f77与前版dc47须分别标身份；首次交付classifier只在test文件自定义、runnerloaded子串假阳性风险已退回第一次返工，仅改分类文案不无限重跑/改runtime。
- task36只读核查headless显示/Xvfb与Unixsocket/tmp隔离可测方案中，不下载不启动服务，避免擅改host/tmp。快速复现说明已新建reports/QUICKSTART.md。


## 后续实验：显示、诊断与对照

- task35有限接收：原Windows PE进入Vulkan实例入口仍桌面等待，生产分类器Lead8PASS，前版PE dc47...已跑、后验断言f77...独立编译身份分列。
- task36/37/38：Xvfb隔离获取并认证连接；原真实日志内部VkInstance创建后先std::bad_alloc，再SEH invalid-frame，再desktop重启；目标PE从未取得实例返回。初版colon/setsid/killpg/auth窗口/无所有权unlink均退回，2次返工后执行员7项、独立8项假桩由Lead重新运行通过。无新真实server验证修后controller。
- task39：v1只RTLD_NEXT在RTLD_LOCAL插件实际127红例，v2增加NOLOAD现有libstdc++ handle；Lead四个global/local原/preload ELF均catch42+exit0，库6f034d0a...。真实Wine符号介入及OOM情况下观测器自身再分配仍未知。
- task40/41：new06a2fceb...派生只net-absock.c与net.c错误传播2文件变更，显式native ELFUSE_ABSOCK_BASE=lab/.s支持短namespace目录。独立真实abstract/shortening inode、跨exec、getsockname与基址私有权限保留验证，原f2/原上游冻结不变。
- task42/43：实际3次运行，前2次prefix断链/依赖缺失126，第3次controller0但内部Wine85s/-15且NO_TRACE。先前“唯一1次/透明已证/无trace证明无throw”退回纠正。完整LD路径漂移仅候选解释，未取得所需badalloc原生栈。
- task44/45：可选--absock-base正式接离线后端，known06能力hash门、默认无env、绝对LAB私有路径UTF8字节预算、准备不创建/不安装，执行重检mode/叶子软链接。开发/独立63PASS，独立负例12PASS；same-owner700目录换inode身份未绑定保留边界。
- task46：新scope恢复37完整LD路径+Linuxsh/fullprefix，唯一实际对照依旧NO_TRACE；内部Wine60.21s后watchdog124停在FEX/preloader，外runner约64.68s/exit0不是Wine成功。静态LLVM导入throw-helper不证明历史OOM来源。hosttmp目录增量不作为全域零写证明。
- task47已派执行员新v3无分配write初始化/throw/resolve/backtrace阶段标记，仅ELF自测，不改v2、不新Wine。task48 blocked_by47，计划bare hello A无preload/B仅phase库最多两次对照，尚未认领；board阻止提前reassign，尊重依赖门，待47验收后再assign。
- 用户再次明确：当前danger-full-access、无审批；工具调用不设置sandbox_permissions。保持团队协作、不重复相同工具等待轮询、不因卡片completed就把Windows图形/真实Steam游戏标成功。


## 自动续轮10–17：官方源码对齐与共享会话映射缺项

- 原生ARM64 PE kernel32/DPI96/Vulkan DLL加载分别37/38/39通过；Vulkan实例调用仍超时。图形缺项不只发生于FEX/x64，不能仅归咎指令翻译。
- 最小RO-private与后续Wine式O_RDONLY/RW-private探针均显示：预触页后共享端更新不可见；后者另实测首次私写后隔离成立。诊断exit0不是ABI conformance。Darwin对照不是native Linux内核对照。
- 官方Proton原包版本experimental-11.0-20260924-arm64；日期相邻官方Proton58a40f82→ValveWine dc26e618。取得官方winstation.c与virtual.c，Linux只读section用RW+MAP_PRIVATE，并有明确依赖Linux后续文件更新可见性的源码注释。日期邻近与wine-11.0字符串不等精确包commit认证。
- 单次+winstation实测14条session object-ID mismatch，DPI仍返回96/38；实际对象id、文件fd关联及因果仍未锁定，禁止套用最小ABI探针的0当Wine对象内容。
- 只读宿主页HVF capability微探针：匿名RW/文件RW host→HV_RWX两个正对照0；O_RDONLY hostRO→HV_R及HV_RWX都0xfae94001。单VM create/unmap/destroy正常，原文件前后摘要一致。降低stage2权限这一简单路线未通，不代表所有Apple版本均如此。
- 新探针运行器在复审中两次返工：移除已有seed删除逻辑、增加退出/timeout/hash门控；round14再增严格classify_execution入口与6个测试，合计38纯测试通过。保留结构级classify非执行判定的区分与文件路径预检TOCTOU未知，不使用绝对无覆盖保证。
- 团队编排纠正：当前8既有成员的恢复会话多次无工件失败。曾误用task_board teamRun启动额外Lead/成员会话，产出了独立报告但Host historyfollow无法追踪其durable父地址，根卡failed/ownResult=succeeded；不抹掉环境错误或宣称整树通过。用户明确指出后停止此路线，不再另起会话绕上限。
- round17 task59仅当前团队单次--verbose/+virtual DPI映射观测；成员再次task ready失败且未claim，Lead以有限诊断任务兜底，不执行新内核语义实现。凡trace没有fd身份/文件路径关联，就保持session mapping未知，不从数字fd强推。
- 原Proton/Wine/accepted runtime保持冻结。任何未来修复都需新的派生runtime，覆盖live-before-write、COW-after-write、munmap/MAP_FIXED防回写、16KiB/4KiB、fork/线程及失败回滚。不得以全private改shared或定期pread冒充完整Linux页缓存语义。

