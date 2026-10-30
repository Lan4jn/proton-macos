# 实验交付索引

## 后续证据更新（task-106–115）

整体目标仍未达成；历史轮次结论须结合本节，派生实验及单元测试不等于完整 Steam / Vulkan 成功。

### 最新实测（task-144 续）：720p 合作式呈现开销

- 720p readback 稳态：off median 10.442 / p90 18.625 / max 31.294 ms；on 14.739 / 26.194 / 37.095 ms，**差约 +4.297 ms**（本 spike 上界，非纯 UI 因果）。
- 首个 host 回调 741.155 ms 单独列；去首后 median 5.962 / P95 16.439 / max 19.195 ms，**后续无百毫秒尖峰**（不证明多窗口 init 成本）。
- 47 次 UI 更新、distinct seq 22/27，5 个身份未采样（18.52%），由 CPU seq 水印区分并逐帧归因节流/单 slot 覆盖。
- post-init UI 约 51.011 Hz；present 进程 active 主线程入口 3233 次/1.643 s ≈ 1967.9 Hz，**主线程并不缺 syscall**，瓶颈是合作式节流/回调与单 slot。
- 像素校验：720p 排除 pixel0 后 **921,599 像素逐点等于真实 readback**，pixel0 单独等于 seq1；64² 对应 4095 像素。**不声称水印后全图 4096 等源**。
- 旧 direct dump 的 24 字节 offset 已标失效；最终 56 字节布局将再次独立核验。

### 最新实测（task-144）：C 路线核心假设成立，线程模型受限

- 派生 runtime 以显式 env opt-in dlopen 呈现 dylib；在 syscall_dispatch 主线程经 guest_ptr_bound 校验只读 GVA 0x224638，同进程 backing 0x7eb0224638，无任何 FD 导出/hypercall。
- 三个 phase 自身 view 捕获均 4096/4096 = 2f69987b…；on3 exit0、6.851 s、cleanup_errors=[]；非法/未映射范围 exit86；opt-in 关闭时无加载。
- 线程限制实测：回调 min 0.388 / median 1.079 / max 303.330 ms；guest heartbeat 最大 gap 326.986 ms；无 syscall 纯计算段 3009.092 ms 期间 UI 更新 gap 3007.967 ms → 确证 UI 更新依赖 guest 发起系统调用。有心跳时约 42–49 Hz，16 ms 节流上限 62.5 Hz。
- 未搬动 vCPU/main；明确“UI 期间 guest 暂停”，不是并行、也不是未来线程方案。
- 窗口 number 4533、isVisible=1，但瞬时 occlusion=0，报告未声称人眼见屏/无遮挡。

### 最新实测（task-142）：CPU 渲染吞吐与光栅成本

- 轻载（单 triangle／clear）720p draw median 5.211 ms、p90 10.400；**720p clear 5.538 ms 反而慢于 draw** → 轻载每帧成本由提交/同步固定开销主导，不能当作游戏 FPS。
- 重载正交（100 个重叠三角、18% 屏面积、固定 opaque shader）：draw median 64² 2.318／360p 35.906／720p 75.150／1080p 115.355 ms；720p 固定分辨率 instance 20→22.684、100→75.150 ms，clear 基线 2.127/3.675 ms，增长明显。
- 填充率**不能压成单一常数**：固定 100 实例按分辨率有限差分给出约 1.22e8 / 3.36e8 / 5.32e8 覆盖像素每秒（64²/360p/720p/1080p 区间），差异大源自每帧固定成本（约 2 ms 量级）被摊薄的程度不同；Lead 早期用 3–4 ns/像素折算的说法属简化，以本轮多档实测为准。
- 500 instance pilot 首帧 410.6 ms，20 帧稳态超预算 → 主动 exit70 BENCH_ABORT_BUDGET，**未发布该组 FPS**。
- QPC：frequency 1e7、与 GetTickCount64 差在 120 帧区间降至 1.5–1.8%（重载 0.02–0.9%），tick 全为正且单调。
- 初始化占比：仅 pipeline 与测量循环可精确定位；wineboot/explorer 只到 trace 边界，其余标 UNKNOWN，未为凑满墙钟而拼凑分段。

### 最新验收（task-141）：guest 像素证实可呈现在 macOS 宿主窗口

- host helper 为系统 clang + AppKit 构建的 Mach-O arm64（SHA `e0bd32e6…`）；guest 源用只读复制的已验收 framebuffer（`2f69987b…`）。
- 三次 trial（2/3/4）均：NSWindow `number=3790`、`scale=2`、`occlusion_visible=1`；以自身 view 的 `bitmapImageRepForCachingDisplay`/`cacheDisplay` 取图，**未申请任何系统截图权限**。
- 像素核验：`pixels_compared=4096`、`mismatched_pixels=0`，decode 后 SHA 与 guest 源同为 `2f69987b…`；`png_all_4096_pixels_equal_source=true`、`host_capture_raw_equals_png=true`，PNG 文件 SHA `89876eee…`。
- 时延：publish→receive 20.2/34.8/41.8 ms；view capture 366/428/383 ms（含显式 150 ms settle）。**单帧效能，不是持续吞吐或 FPS**。
- 首轮 trial1 失败（deviceRGB 二次转 sRGB + 跨域计时异常）raw 保留，未删改。
- 边界：只证明**单帧像素运输 + 宿主显示**；显示驱动集成、窗口映射、输入回传、DPI、多窗口、人眼确认均 UNKNOWN。

### 最新验收（task-139）：x64 真实窗口链打通（但无显示驱动）

- 真实 x86-64 PE `d6625afe…` 从安装目标 wrapper（源目录移开）执行，exit 0、无超时，`cleanup_errors=[]`。
- 完整链路：USER32/GDI32 加载 → RegisterClassEx → CreateWindowEx → ShowWindow → 消息循环 → **真实 WM_PAINT(15)** → BeginPaint/FillRect/TextOut/EndPaint → PostQuitMessage → GetMessage 返回 0 → DestroyWindow。
- 时间：wrapper 78.257 s，PE 21.045 s；其中 **RegisterClassEx 独占 20.678 s**，CreateWindowEx 3 ms、ShowWindow 2 ms、paint 2 ms——首要慢点是注册窗口类而非建窗，无冻结。
- **关键边界**：stderr 明确 `load_graphics_driver … using null driver`（baseline 行 52/76）。因此这是 **Win32 窗口对象 + GDI 绘制成功**，**不是宿主可见窗口，也没有屏幕呈现**。
- 结论分层：Win32 窗口 PASS、GDI 绘制 PASS、宿主可见窗口 FAIL/UNKNOWN（null driver）、输入事件 UNKNOWN。
- 证据口径修正：null driver 是 stderr **显式行**（baseline 第 52/53、76/77 行 `load_graphics_driver … using null driver` / `driver L"null"`，SHA `0878f85d…`），不是"没打印"的推断。
- 附带事实：`run` verb 对照 0.823 s exit 1，首错为 Proton prefix upgrade 缺本轮 compat/tracked_files，PE 未启动——该路径另有缺口，未叠 launcher 改动。
- 预算口径：adapter 外层 115 s，实际 elfuse argv 为 `--timeout 90`；本轮 78.257 s 未触及，但后续 trace 实验若需 110 s 必须同时调整底层预算。

### 最新验收（task-137）：x64 图形路径打通

- 真实 x86-64 PE（`file` 确认 PE32+ x86-64）SHA `aba1c08c…`，与 ARM64 版同一 C 逻辑与同一 SPIR-V 重编译，绘制逻辑未改。
- 负对照 `--skip-draw`：target_exit 21，内部像素为蓝，正确判负。
- 正常绘制：target_exit 0、count=1、llvmpipe、真实 `vkCmdDraw(3)`+fence、8 点像素 PASS；framebuffer 16,384B SHA `2f69987b…`（与 ARM64 版一致）。
- 两路 cleanup_errors 为空；安装回滚 success、pre/post 指纹一致；源包移开后从安装目标 wrapper 执行。
- 边界：仍 gate=1 诊断共享映射、CPU llvmpipe 非硬件 GPU、游戏窗口未测；FEX 归属证据仅限 Darwin arm64 上真实执行 AMD64 PE 与 prefix 中 libarm64ecfex.dll 注册，未启用模块加载 trace。

### 最新验收：安装目标适配器（task-133）

- 最终代码收敛后，Lead 再次独立复跑：**90 tests，OK（6.129s，exit 0）**，日志 `logs/adapter-vulkan-config/lead-final-tests.log`。guest 解释器未匹配时显式返回 20／execution_performed=false，移除固定下标回退；本次未重跑 Vulkan 长实验，以下运行数据保留为此前实测。

- Lead 独立复跑 backend：89 tests，OK（6.227s）；读取两组原始 stdout，未修复组 `VkResult=-9 / exit 12`，修复组 `count=1 / llvmpipe / WIN_ARM64_VULKAN_OK / exit 0`。
- 在隔离兼容工具目录安装、移走源目录后，从目标 wrapper 实际启动 elfuse → Linux Python → Proton → Wine → ARM64 Vulkan 探针；外部 lab Python、适配脚本、sysroot、elfuse 与 lavapipe 依赖仍显式保留，并非独立可分发安装包。
- 修复为 guest_env 经 elfuse `--env` 传入 guest 的 LD_LIBRARY_PATH，宿主 process.py 的 LD_* / DYLD_* 隔离规则保持原样。驱动依赖 libLLVM.so.23.1 位于独立 lavapipe 目录，缺少 guest 搜索路径时 loader 报 Found no drivers。
- 两组收据均记录回滚成功、安装根前后指纹一致；此结果仍依赖 ELFUSE_DIAG_SESSION_SHARED=1，真实 Steam 发现/启动、正常 COW 语义、硬件 GPU、游戏呈现均未通过。
- 证据：reports/adapter-vulkan-config.md；logs/adapter-vulkan-config/receipt.json；runs/trial_a_unfixed/logs/run-1scdub10 与 runs/trial_b_fixed/logs/run-phlrpkbn。


> **【状态与边界核心声明】**：
> 1. **已通过范围**：所谓“通过 / WIN_ARM64_VULKAN_OK”仅指在 `ELFUSE_DIAG_SESSION_SHARED=1` 诊断映射环境下的 Windows ARM64 原生 Vulkan CPU 设备（llvmpipe）枚举测试。该诊断映射丢弃了 Linux 标准文件私有页缓存 Copy-On-Write (COW) 隔离语义，**绝不等于生产全链路已完成**；
> 2. **源码 Pin 定位**：Commit `adea6cbac9d00bb22910145354d00c463fcf3afc`（等价区间 `[66ee546cbea4..adea6cbac]`）为经由结构体尺寸与运行验证的**兼容基线**，并非经 Valve 官方 submodule 指针证明的唯一精确构建源；
> 3. **运行实体隔离**：基线死锁运行（`shipped_baseline`，`run-73d055tk`）直接基于 Valve 原版 Shipped 二进制（`4f6013fa...`）；而源码编译出的 `adea pristine` 二进制（`96de5f0a...`）仅用于静态反汇编结构体偏移自检，两者严格分立；
> 4. **工作区状态说明**：lab 根目录当前未检测到 git 仓库（`git diff` 报告 `Not a git repository`），空输出不证明干净，真实文件边界须结合各派生目录逐文件核查确认。
- 单 NOP Wine 派生实验：原控制字重入减少，但 Vulkan 未返回；收据哈希及有效性判据已更正，见 [win32u-fix.md](win32u-fix.md)。
- 次级 once `0x20102d478`：同线程两次进入及六级 FP 身份重合确证活跃栈内递归，见 [once478.md](once478.md)。结论限于该派生实验环境。
- guard v2：实际 callback 失败注入证实 once 永久完成缺陷，暂不进入 Wine 运行验证，见 [wine-guard-v2.md](wine-guard-v2.md)。
- guard v3：Lead 复跑宿主原生八项测试通过；task-116 的 guest glibc + TLSDESC 晚加载共享库与线程隔离探针亦经 Lead 独立复跑 exit 0，见 [guest-dynamic-tls.md](guest-dynamic-tls.md)。DTV 是否实际新分配及完整 Wine 集成仍未验证。
- x64 启动：root 同一 read 在 fd 8 请求 16 字节，24 个匹配 pending-call 快照、root 日志未截断；子进程有截断，写端责任及真实 open 状态仍未知，见 [x64-pipe-lifecycle.md](x64-pipe-lifecycle.md)。
- 真实构建突破（task-118）：从 Valve Wine 完整公开源码（56 MB／12,523 条目，tar 校验通过）实际编译出 ARM64 ELF `win32u.so`：基线 `be356a89…`、补丁 `b6e7b1ea…`。补丁版含 `is_vulkan_init_in_progress`、`vulkan_init_guard_enter/exit/cleanup` 与 TLS 变量 `d3dkmt_init_depth@0`、`vulkan_init_depth@4`；新增 4 个导入符号（`__pthread_register_cancel` 等，GLIBC_2.34／2.17）经核在 guest libc 中均可解析。此前的“只能提取代码测试”阶段已结束。
- 端到端第一轮（task-119）不可用作补丁判定：观测地址硬编码为旧布局 `0x20102d478`，而本轮实际 once 位于 `0x200fd62a0`；原版模块未复现 `moduletrace8` 的 `has_step3=true` 基线，真因为 62s 超时截断 wineboot 退出刷新（放宽至 90s 后基线稳定复现 Step 1–3）。`get_shared_desktop` 自旋三组均出现（22／12／12），属既有行为。
- 端到端第二轮（task-120）同样不可用作 guard 因果判定：`target_patched_build/config.log:24688` 明确 `libvulkan and libMoltenVK development files not found, Vulkan will not be supported`，故重建的 pristine 与 patched 的 `win32u.so` 均无 Vulkan 支持，运行时 `err:vulkan:vulkan_init_once Wine was built without Vulkan support.` 后直接返回 `VkResult=-3`。关键反证：**pristine（无 guard）与 patched（有 guard）结果完全相同（-3／exit 12／约 44s）**，说明两者都未进入 `0x20102d440`／`0x20102d478` 递归路径，补丁解除死锁未获证明。已派 task-121：先让 configure 检测到 Vulkan 并重编，要求带 Vulkan 的 pristine 先复现死锁，再判 guard。
- **关键突破（task-121，Lead 已核原始日志）**：configure 真实使能 Vulkan（`config.h:845 SONAME_LIBVULKAN "libvulkan.so.1"`、`ac_cv_lib_soname_vulkan=libvulkan.so.1`；根因是 `aarch64-linux-gnu-readelf` 缺失被退化成 `/usr/bin/true`）。重编后：
  - Pristine（无 guard，带 Vulkan）SHA `341ddb62…`：`0x201039970` 先 `word=0`（total_count=54），约 9.1 s 后同线程 `word=1` 再入（total_count=71），随即 `FUTEX_WAIT_PRIVATE`，90.2 s 超时 → **故障因果前提复现**。
  - Patched（带 guard）SHA `60f7b323…`：该地址 0 次进入，`VkInstance created at 0x00aaf580`，推进到 Step 4，62.5 s 正常退出（exit 13）→ **递归死锁被切断，`vkCreateInstance` 首次返回 VK_SUCCESS**。
  - stderr 含 `init_physical_device` 扩展协商行，说明 Wine 驱动层确实进入设备初始化。
- **仍未达成（Step 4 枚举）**：`Physical device count: 17035872` 为无效计数，第二次 `vkEnumeratePhysicalDevices` 返回 `VkResult=5 (VK_INCOMPLETE)`，即设备枚举尚未真正工作；ARM64 探针源码不在 lab，不能假定其与 x64 版逻辑一致。已派 task-122 定位探针或驱动侧原因。
- **结构体错位定位（task-122）**：诊断探针把哨兵 `0xaaaaaaaa` 送进第一次枚举，loader 写回 `17035200 = 0x103efc0`；stderr 记录 `Created instance 0x103ef80`，而 `0x103ef80 + 0x40 = 0x103efc0`，即读到了 `physical_devices` 指针低 32 位。说明 shipped `winevulkan.so` 与自建 `win32u.so` 的 `struct vulkan_instance` 相差 8 字节（一个实例函数指针）。驱动端确有 1 个宿主设备（`Host physical device extensions`，stderr:20017）。
- **同源部署结果（task-123）**：`pristine win32u + pristine winevulkan` 仍死锁于 `0x201039970`（word 0→1 + FUTEX_WAIT_PRIVATE）→ **死锁源确证位于 win32u 初始化路径**。`patched win32u + patched winevulkan` 无死锁、62.6 s 正常退出，但在 Step 3 抛 `err:vulkan:vkCreateInstance Exception 0xc0000005`，日志显示 `thunk64_vkDestroyBuffer` 被当作 `vkCreateInstance` 调用 → **PE 端 shipped `winevulkan.dll` 与自建 Unix `winevulkan.so` 枚举表错位**。
- **策略修正**：Unix 端 `winevulkan.so` 必须保持 shipped（`2786ca6f…`，与 PE `winevulkan.dll` 配对），改为让自建 `win32u.so` 适配其结构体布局。在办：task-124 用二进制偏移指纹反查 shipped 对应精确 Wine commit 与差异成员；task-125 据此对齐布局后复测枚举。
- **Vulkan 端到端打通（task-125，Lead 已核原始 stdout）**：保持 shipped `winevulkan.so`(`2786ca6f…`)、`winevulkan.dll`、`ntdll.so` 原样，仅替换自建 `win32u.so`（`0af4125e…`，guard + 结构体对齐到 shipped 布局 `physical_devices@0x2e0`／`count@0x2e8`／`sizeof=0x2f8`），运行结果：
  - `Step 4: Physical device count: 1`
  - `deviceName: llvmpipe (LLVM 23.1.1, 128 bits)`、`deviceType: 4 (VK_PHYSICAL_DEVICE_TYPE_CPU)`、`apiVersion: 1.4.354`
  - `VkInstance destroyed cleanly` → `FINAL_STATUS: WIN_ARM64_VULKAN_OK`，**exit 0**（原版探针与诊断探针各一次，均同结果）
  - 对照 `shipped_baseline`：同环境仍 `Step 3` 后死锁，exit 124 → 成功归因于 guard + 布局对齐，而非环境变化
- 完整性：`fixtures` 内 `win32u.so` 仍为 `4f6013fa…`、`winevulkan.so` 仍为 `2786ca6f…`，未被改写；lab 根未检测到 git 仓库（空输出不证明干净，经各派生目录核查确认未改原件）。
- 仍未达成：GDI display cache 自然恢复、真实 Steam/Steamworks 接入、x64(FEX) 路径、真实 GPU 驱动（当前仅 llvmpipe CPU 设备）、完整 Windows 应用建窗运行。
- **精确源码版本反查（task-124）**：结构证据成立——shipped `winevulkan.json` 为 `api_version 1.4.357`（两处副本）；`winevulkan.so` 含 3 个 ARM 扩展函数（ShaderInstrumentationMetricsARM、DataGraphEngineOperationPropertiesARM、DataGraphOpticalFlowImageFormatsARM，字符串 16 处），而 `dc26e618` 构建为 0 处；instance 函数数 82 vs 79 = 3 指针 = 24 字节，与偏移差完全一致。
- **但 task-124 的 commit 推断已被证伪，勿引用**：它用 `version` 串 `1790245028` 换算 `2026-09-24T10:17:08Z` 取 HEAD 得 `3c1a3fef…`；该 commit author 为 `2026-09-24T22:17:15Z`、committer `23:32:35Z`，晚于构建 12 小时，不可能是当时 HEAD。该数字很可能是 Steam build id 而非时间戳。已派 task-126 改用 `make_vulkan` 生成器计数（82 个 instance 函数 + 1.4.357）在多个候选上判定，保留“构建后 sizeof(struct vulkan_instance) 不等于 0x2f8 即证伪”的判据。
- **commit 已收敛（task-126，Lead 复核）**：撤回“可能是 build id”的怀疑——Proton `Makefile.in:1430` 确为 ``echo `date "+%s"` `git describe --tags` > $(DIST_VERSION)``，首字段就是 POSIX 时间戳（`2026-09-24T10:17:08Z`）。判据改为生成器计数：`dc26e618`（1.4.339／79 函数／0x2e0）FAIL；`20d85e62`（1.4.357／82 函数但缺 `api_version`／0x2f0）FAIL；`66ee546c`（首次达 0x2f8）起为 PASS。**结构等价区间 `[66ee546cbea4 .. adea6cbac9d0]`，推荐 HEAD 候选 `adea6cbac9d00bb22910145354d00c463fcf3afc`**（committer `2026-09-24T00:51:45Z`，早于构建 9.5 小时，已核 commit 真实存在）。
- 在办 task-127：从 `adea6cbac` 构建，先静态验证 `sizeof=0x2f8`／`physical_devices@0x2e0`／`count@0x2e8`（不等即按证伪判据停止），再只加 guard（去掉手工布局对齐），用 shipped `winevulkan.so/dll` 跑 90 秒，目标产出仅含 guard 的可移植最小补丁。
- **可交付形态达成（task-127，Lead 已核补丁与反汇编）**：从 `adea6cbac` 构建后，偏移**由源码天然满足** shipped 规范（`ldr w8,[x22,#0x2e8]`、`ldr x21,[x22,#0x2e0]`、`add x23,x23,#0x288`、`sizeof struct instance=0x368`），不再需要任何手工对齐。
  - 最小补丁：`sources/wine-pin-adea/wine_vulkan_reentrancy_guard_adea6cbac.patch`（248 行，仅 guard：`__thread` 深度计数 + `guard_enter/exit/cleanup` + `is_vulkan_init_in_progress`，**0 处结构体/padding 改动**）。
  - 产物：adea pristine（`96de5f0a…`，仅静态偏移自检）／patched `win32u.so`（`59a76b05…`，动态运行验证）；部署时保持 shipped `winevulkan.so(2786ca6f…)`／`winevulkan.dll`／`ntdll.so` 不变。
  - 运行：patched `FINAL_STATUS: WIN_ARM64_VULKAN_OK`、count=1、llvmpipe、exit 0（48.18 s）；shipped 基线（使用原版 Shipped `4f6013fa…`，与 adea pristine 分开）Step 3 死锁 exit 124。
- 结论：已具备“从真实源码构建、仅含 guard 逻辑、与 shipped 模块共存”的最小补丁形态；换 Proton 版本需重新确认 commit 与偏移。
- **可逆发布链路接入（task-129，Lead 已独立复跑）**：补丁模块纳入 `scripts/backend/steam_plan.py`（新增 `validate_elf_architecture`／`create_compat_module_plan`／apply 的 `replace_compat_module`／verify／rollback 扩展）。Lead 亲自执行 `python3 -m unittest discover -s tests/backend`：**Ran 75 tests, OK**（既有 69 + 新增 6）。e2e：`4f6013fa…` → apply → `59a76b05…` → rollback → `4f6013fa…`，`pre_fingerprint_matches_post=true`、`zero_write_outside_fixture=true`，隔离根在 `logs/steam-plan-compat/fixture_steam_root`。
- 交付文档：`reports/vulkan-guard-handoff.md`（245 行）、`reports/steam-plan-compat.md`。
- 在办：task-120 基线复现＋补丁单变量判定；task-115／117 已完成 read16 协议静态候选与动态调用栈绑定（`wait_select_reply` 直接命中）。

## 当前状态（续轮37–40，Vulkan 递归重入死锁已确证为 Wine/winevulkan 桥特有，Linux 原生路径全通，信号与可逆安装端到端闭环，真实 Steam 仍待验证）

Round39–40（最新信号语义修复、可逆安装方案、全景按进程惰性布防与 L/W Vulkan 对照终局裁决，已由执行员与独立复核员验收）：
1. **L 与 W 对照终局裁决：once 递归重入死锁确证系 Wine 桥特有 (Task-94 突破)**：
   - **布防机制技术突破**：查明 Task-92 全景插桩因 `execve` 未重置宿主全局布防状态导致主进程断点错位的假阴性缺陷（留证于 `reports/once-panorama.md`）；在 `sources/elfuse-once-panorama2-derived` 中实现按进程惰性布防（在 `exec.c` 中 `guest_reset` 时调用 `once_count_exec_reset`，并在 `guest_region_find` 命中目标映射时按进程自身 libc 基址安装）；
   - **先证明尺子能量 (Control Verification)**：在正式跑测前，通过 `scripts/runtime/once_panorama2/run_control.py` 在已知重复目标 `0x203000440` 上进行控制测试，确证捕获 `target_count=1 (word=0)` 与 `target_count=2 (word=2)`（收据：`logs/once-panorama2/control.json`, exit=0），证明插桩具备捕获重复进入与状态机跃迁的核心能力；
   - **正式物理跑测对比**：在相同底层虚拟化与同一运行时二进制（SHA256: `81803322...`）下执行两条链路：
     * **Windows ARM64 Vulkan (Wine 桥)**：`vk_enum_arm64.exe` 耗时 62.122s (`exit: 124`, `run_valid: true`)，捕获主进程全部 19 次 once 调用（5 个独立控制字）；目标 `0x20102d440` 确凿被同线程进入 2 次（首次 `ts=985307557385, word=0, LR=0x200f39d24`，相隔 9.017 秒后二次进入 `ts=985316574046, word=1, LR=0x200f3a3f8`），直接触发 `FUTEX_WAIT_PRIVATE` 死锁，未完成项 `uncompleted_word1_count=1`，**`windows_closed_loop = true`**；
     * **Linux ARM64 原生 Vulkan (Lavapipe)**：`probe_queue_fill.py` 耗时 0.941s (`exit: 0`, `run_valid: true`)，捕获全部 2,895 次 once 调用（254 个独立控制字），所有控制字初次执行后均成功归 2，无任何未完成项（`uncompleted_word1_count=0`），且完整跑通逻辑设备创建、图形队列提交与 256 字节 `0x1234abcd` 预设图案内存回读（`PATTERN_MATCH_OK`），**`linux_closed_loop = false`**；
   - **终局判定 (Raw Verdict from logs/once-panorama2/comparison.json)**：
     ```json
     { "windows_closed_loop": true, "linux_closed_loop": false, "is_bridge_specific": true }
     ```
     **终局裁决结论**：`pthread_once` 单线程递归重入死锁确凿系「Windows ARM64 / winevulkan 桥接层与 Wine 用户态状态机协同场景下特有」，绝非 Linux 侧 Khronos Loader 或 Mesa Lavapipe 驱动自身的固有缺陷。详见[全景对照终局报告](once-panorama2.md)。
2. **guest 信号语义全覆盖与 SIGCHLD si_status 贯通修复 (Task-89/90/91 成果)**：
   - **信号语义基线补测 (Task-89)**：构建 `test_signals` 测试套件全面补测 guest 信号语义，覆盖 7 项核心能力（基本投递与 sa_mask、阻塞读 EINTR、SA_RESTART 透明重启、SA_SIGINFO 元数据、sigaltstack 备用栈、sigprocmask 阻塞与解阻、setitimer 真实定时器均通过），精准发现 SIGCHLD 时 `siginfo_t.si_status` 为 0 的未填充缺陷（RED: exit=32, failure_mask=0x20）；
   - **内核到用户态端到端修复 (Task-90)**：在 `sources/elfuse-sigchld-status-derived` 中完成最小改动贯通（补丁：`logs/sigchld-status/sigchld_status.patch`），在 `linux_siginfo_t` 中对齐 `_sigchld.si_status` 布局，在子进程退出时通过 `proc_send_guest_signal_info` 将 `wait_status` (`WEXITSTATUS`/`WTERMSIG`) 跨进程序列化发往父进程，并在父进程装配 `rt_sigframe` 时完整注入 `si_status`，**实现 7 项信号测试 100% 全绿 (exit=0, 0 回归)**；
   - **独立复验与规范性核定 (Task-91)**：独立复算确证 7 项测试重跑一致；针对 Lead 此前怀疑“SIGCHLD 的 si_code 被补丁传成 0 (SI_USER)”，复验时通过补丁源码逐行比对（确认子进程退出时已显式设置 `int32_t exit_si_code = CLD_EXITED;` 并按 `WCOREDUMP` 选取 `CLD_DUMPED/CLD_KILLED` 贯通至父进程）与现场探针实测（准确捕获 `si_code=1 (CLD_EXITED)`、`si_pid=2`、`si_status=42`），已彻底证伪该怀疑；最终定论为：**si_status 与 si_code 均符合规范，无残留缺陷**。详见[信号测试报告](signals.md)、[SIGCHLD修复报告](sigchld-status.md)、[信号独立复验报告](sigchld-verify.md)。
3. **端到端可逆安装方案与清单验证 (Task-93 成果)**：
   - 在 `scripts/backend/` 中实现了基于计划与清单的端到端可逆安装机制：`plan` (确定性输入输出，支持无副作用 JSON 导出) → `apply` (仅作用于隔离 fixture 根) → `manifest` (逐路径记录 SHA256 摘要与来源) → `verify` → `rollback` (依据清单按字节比对恢复原状，快照证实 fixture 根之外零写入)；
   - 包含负向路径越界拦截测试，既有 63 项后端测试保持全绿，100% 封闭在 lab 内部，绝不触碰真实宿主 Steam 或系统路径。详见[可逆安装方案报告](steam-plan.md)。

4. **guest 调用栈深度回溯：重入环栈级绝对坐实与 win32u.so 归属确证 (Task-96 重大突破)**：
   - **AArch64 X29 有界帧指针栈回溯**：在 `sources/elfuse-once-backtrace-derived` 中，在 `pthread_once` 入口 BRK 处增加有界栈回溯（支持最深 32 帧，内建循环、越界与未对齐断路保护），仅在目标地址 `0x20102d440` 命中时选择性捕获（两轮总开销不足 100µs，完全不改变时序），直接输出物理帧列与内核映射模块及偏移；
   - **首次 (Call 1) 与二次 (Call 2) 调用栈严格比对**：
     * **首次进入 (Call 1: target_count=1, word=0)**：回溯 9 帧，直接追溯至 PE 二进制：`depth 0: win32u.so off=0x139d24` → `depth 1: winevulkan.so off=0x9568` → `depth 2: ntdll.so off=0x404e4` → `depth 3: winevulkan.dll off=0x1adb0` → `ntdll.dll` → `kernelbase.dll` → `winevulkan.dll vkCreateInstance` → `vk_enum_arm64.exe off=0x4dc`；
     * **二次进入 (Call 2: target_count=2, word=1, 相隔 9.017s)**：回溯 27 帧，**其 Depth 18 至 26 帧与 Call 1 的 Depth 0 至 8 帧发生 100% 字节级、地址级、模块级一一完全重合！**（Call 2 depth 18 为 `win32u.so off=0x139d24`，depth 19 为 `winevulkan.so off=0x9568`，直至 depth 25 为 `vk_enum_arm64.exe`）；
     * **例程存活与自递归证据**：Call 2 的 Depth 16–17 帧确凿为 glibc `pthread_once` 调用首个初始化回调例程（`blr x5`，`libc.so.6 off=0x8e10c`），Depth 15 为该例程函数体（`win32u.so off=0x13a374`）；该例程在未退出时经 14 层子调用最终在 Depth 0（`win32u.so off=0x13a3f8`）重新调用了同一控制字；
   - **重大认知纠偏与物理归属定论**：
     * **彻底证伪 libvulkan.so.1 归属假设**：此前推测的 `0x200f39d24` 与 `0x200f3a3f8` 经内核映射确证**均位于 Wine Unix 端核心图形驱动库 `win32u.so`（偏移 0x139d24 与 0x13a3f8）**，绝非 Khronos 官方 Vulkan Loader！
     * **终局定论**：首次调用的全部上层调用栈依然活在栈底未退出，**重入环在调用栈物理拓扑层面获得绝对坐实（STACK-LEVEL CONCLUSIVELY PROVEN）**；分支 A_alt（异常提前退出未置 2）彻底证伪。详见[调用栈深度抓取报告](once-backtrace.md)。


5. **x64 Vulkan 探针同插桩对照测试与新增取指异常缺项 (Task-102 成果)**：
   - **最小 x64 PE 探针**：构建零 CRT 依赖的 `scripts/runtime/x64_vk/vk_enum_x64.exe` (PE32+ x86-64, SHA256: `d408405c...`)，动态 LoadLibraryA("vulkan-1.dll") + GetProcAddress；
   - **物理实测与未达门槛留证**：收据 `logs/x64-vk/receipt.json` 记录 `exit_code=124`，耗时 62.128s，`stdout_bytes=0`，`has_step3=false`，**`run_valid = false / FAILED` (未达有效性门槛)**；
   - **严格原文异常归因**：`logs/x64-vk/run-t9qrkmmc/stderr.log` 第 2435 行确凿记录 `src/syscall/proc.c:4571: elfuse: worker: unexpected exception EC=0x20 syndrome=0x82000007 VA=0xf148 PA=0xf148`，伴随翻译诊断 `## Translation diagnostics (PC=0xf148)` 与 `L3[15]=0xf7e7 -> IPA 0xf148`；按原文定性为**“guest 进程在 elfuse 下发生指令取指异常 (VA=0xf148)”**，系本次新暴露的**未定位技术缺项**（疑点：极低地址 `0xf148` 可能为错误跳转或 FEX 翻译层初始化异常）；
   - **架构无关性终态判定**：因 x64 路径在上游启动期即被 `VA=0xf148` 取指异常阻断，物理上从未触达 `vkCreateInstance` 阶段，因此“`win32u.so` 递归自锁与架构无关”假说在 x64 上属于【**不可观测（Unobservable due to Upstream Block）**】，既未证实也未证伪；写明其可反驳条件（修复 `VA=0xf148` 使 x64 成功推进至 Step 3 后，若在 `win32u.so` 同样捕获到 `0x20102d440` 二次重入则证实；若 Step 3 顺利通过则证伪）。详见[x64对照测试报告](x64-vk.md)。
6. **私有映射会话中继架构设计方案 (Task-103 成果，DESIGN ONLY，未实现)**：
   - 在 `reports/private-map-relay-design.md` 中交付设计方案（**DESIGN ONLY，153 行，SHA256: `59572e19b6b58e0e3a3f3e677f9ae33ee794a038fc570df72a95aad380ae43b4`**）；
   - 论证了方式 B 单独不满足语义 (b)，设计了 1.29 MiB / 324 页的影子副本内存比对协议与 TOCTOU 缓解策略；
   - **明确标注本方案仅为技术方案设计，未在 elfuse 中落地实现，严禁宣称已修复**。详见[会话中继设计报告](private-map-relay-design.md)。

## 当前状态（续轮37–38，Vulkan 递归重入死锁已确证，私有映射门禁回写风险已留证，成因在 win32u.so 调用图而非 elfuse，图形与真实 Steam 仍待验证）

Round37–38（最新指令级断点计数、嵌套重入时间线、诊断放行对照与私有映射 COW 审计，已由独立复核员验收）：
1. **指令级断点计数确证重入死锁**：在 `sources/elfuse-once-count-derived` 中，宿主于 guest glibc (`libc.so.6`) 的 `pthread_once` 公共入口（`pc=0x2000ce1a0`）布设 `BRK` 指令级硬件陷阱（证据：`entry_pc=0x2000ce1a0`, `orig_insn=0x88dffc02`, `brk_insn=0xd4200000`）。主线程（`gtid=1`）对目标控制字 `0x20102d440` 确凿进入恰好 2 次：首次进入于 `ts_us=977897241236`（`word=0`, `LR=0x200f39d24`，归属 `win32u.so`），原子 CAS 设 1；二次进入于 `ts_us=977906698324`（相隔 9.457 秒后，`word=1`, `LR=0x200f3a3f8`，归属 `win32u.so`）。结合 glibc 语义（正常返回必然在 `0x8e120 stlr` 存入 2，而控制字全程未曾出现 2）得出：首次调用尚未完成，二次进入为同一线程嵌套重入，直接触发 `SYS_futex(0x20102d440, FUTEX_WAIT_PRIVATE, 1)` 无限挂起。**单线程递归重入自锁获得指令级事实确证（CONCLUSIVELY PROVEN）**。
2. **多重 once 嵌套链时间线与环路闭合**：全量断点计数（19 次调用/5 个不同地址）刻画出主线程的嵌套级联链：
   `0x200ffdd10` (ts…836386, word=0) → #1 `0x20102d440` (ts…241236, word=0) → `0x20d6a15dc` (14次, word 0→2 完成) → #2 `0x20102d478` (+2.93s, word=0) → #3 `0x20100de08` (ts…698307, word=0) → #1重入 (ts…698324, 距 #3 仅 17µs, word=1) → 挂死。
   三个控制字（#1 `0x20102d440`, #2 `0x20102d478`, #3 `0x20100de08`）同时处于“已设 1、初始化中、未置 2”的活跃状态，环路在最后闭合。
3. **泛化同线程重入放行实验与次级缺项定位 (Task-97 成果，DIAGNOSTIC / BORROWED ONLY，非修复)**：
   在 `sources/elfuse-reentry-release-derived` (SHA256: `5ccc1160...`) 中实现动态追踪线程活跃 once 集合并在重入等待时放行（强制置 2 并令 futex 返回 0）。实测连续放行 #1 `0x20102d440` (seq=1) 与 #2 `0x20102d478` (seq=2，相隔仅 62µs)；放行后进程未崩溃，但 `vkCreateInstance` 仍未返回（未达 Step 4），上层扩展枚举逻辑陷入对 `0x20102d478` 的高频快路径轮询（**单次运行循环调用达 528,990 次**，字段取自 `logs/reentry-release/comparison.json` 之 `total_once_calls_in_loop`，对应现象 `Infinite tail-call spin loop in lazydrv_map_instance_extensions` 与 `100% spin until 62s timeout`，stderr 暴涨至 91,027,602 字节约 91MB，收据：`logs/reentry-release/release/receipt.json`，`run-1zz1q22q`，exit: 124，run_valid: true）；基线对照 (`run-g7zrkts0`, exit: 124, 706,842B) 仍卡死于原点。**归因定位**：伪造置 2 跳过初始化后，上层 `struct loader_scanned_icd` / `lazydrv` 驱动函数跳转表并未真正就绪，导致懒加载桩陷入自调用死循环。**必须严格标注该结论来自诊断性放行，绝非修复或进展**。
4. **私有文件映射语义测试与架构级决策评估 (Task-87/88/98 成果)**：
   - **TDD Red-First 基线赤字与门禁缺陷**：无门禁下走 `pread` 快照致活文件修改不可见（`test_private_cow` exit=1, RED: `[TEST_A_FAIL] Live file modification INVISIBLE: got 0x10 expected 0xAA`）；开 `ELFUSE_DIAG_SESSION_SHARED=1` 虽伪造 MAP_SHARED 穿透，但不仅破坏 COW 隔离（Test B FAIL: got 0xbb expected 0x55），更会将 guest 写入回写到底层文件（Test C FAIL: pread got 0x77 expected 0x10，exit=6, RED），属篡改底层文件的严重风险行为。此前所有依赖该门禁的 Vulkan 运行收据均处于该风险限定之下；末端 once 死锁控制字 `0x20102d440` 为匿名私有堆内存（flags=0x22），完全不受此缺陷影响；
   - **架构级决策评估 (Task-98)**：Linux 标准私有文件映射三条语义中：(a) 活文件可见性【当前不可达】（宿主 macOS XNU 内核无针对虚拟机已映射私有页的反向失效通道）、(b) COW 隔离【条件可达】（需实现 Stage-2 Write-Fault 拦截器与动态物理页分裂复制）、(c) 不回写文件【可达】（写入仅作用于匿名副本时）；改动面涉及 `src/core/mmu.c`, `src/syscall/mem.c`, `src/syscall/proc.c` 约 600~900 行核心 C 代码与异常栈处理；回归红线包含与合法 SIGSEGV 冲突、动摇 futex 哈希桶物理单调性、干扰 sigaltstack 时序；验收标准直接以既有三条红测试转绿为准；**结论**：在 macOS/HVF 现有 API 下当前不可直接实现完整原生语义，建议采用会话文件宿主中继协议桥或受控白名单替代方案，**严禁在无替换方案前简单移除门禁**。详见[私有映射决策评估报告](private-cow-decision.md)。
5. **本轮否证、模块归属更正与边界澄清**：
   - **更正模块归属自相矛盾并彻底否证 libvulkan.so.1**：此前推测的调用点返回地址 `0x200f39d24` 与 `0x200f3a3f8` 经 Task-96 深度调用栈物理回溯确证**均归属于 Wine Unix 端核心图形驱动库 `win32u.so`（偏移 0x139d24 与 0x13a3f8）**；`libvulkan.so.1` 归属假设已被 Task-96 彻底证伪（**该库在调用栈物理收据中出现 0 次**）；
   - **否证 Loader 递归告警猜测**：对全量日志检索，Khronos loader 的 `points to the loader / infinite recursion` 告警匹配数严格为 **0 命中**（宽松匹配亦为 0），故"ICD 函数指针指回 loader"这一具体机制未被证实，不得写入结论；
   - **记录平台机理限制**：macOS / Apple HVF 下宿主内核统一虚拟内存对于 `MAP_PRIVATE` 映射无法向已建立 stage-2 映射的虚拟机私有页做反向失效（后续 pwrite 不可见），不能仅靠宿主映射获取 Linux 语义，必须由 `elfuse` 内部内存管理层介入实现。
6. **四分法定论**：
   - **已确立**：Windows ARM64 Vulkan 仍被 guest 侧初始化重入死锁阻断，且**成因在 `win32u.so` 调用图状态机闭环而非 `elfuse` 的 futex 实现缺陷**（`libvulkan.so.1` 归属假设已被 task-96 证伪，该库在调用栈收据中出现 0 次）；主线程单线程存活无唤醒者；私有文件映射存在活文件不可见与回写文件双重缺陷；
   - **已排除**：排除底层 futex 实现缺陷、排除单线程 pthread_once 缺陷、排除匿名页脏数据、排除 COW 穿透泄漏、排除子进程早退遗留、排除 Loader 递归显式告警、排除 libvulkan.so.1 直接重入归属假设；
   - **未决**：泛化放行后上层 `struct loader_scanned_icd` 未就绪导致的高频轮询死循环根治；私有文件映射在宿主与客体间的替代性会话中继协议设计；
   - **仍未实证**：Vulkan 图形设备枚举与真实渲染流水线返回（Windows 路径仍阻断在 vkCreateInstance，从未实证）、真实 Steam 客户端与 Steamworks API 通信（仅在离线 fixture 根下验证）、Valve 官方直接签名、正确且符合 POSIX/Linux 标准的原生全局 COW 内存实现、以及新增的 x64 guest 指令取指异常 (VA=0xf148 / EC=0x20) 的物理定位与修复。详见[私有映射决策评估报告](private-cow-decision.md)、[泛化重入放行诊断报告](reentry-release-diagnostic.md)、[调用栈深度抓取报告](once-backtrace.md)、[x64对照测试报告](x64-vk.md)、[终局状态声明](final-state.md)。

> ### ⚠️ 权威定论声明：  
> **本阶段实验目标【未完成】（TARGET NOT MET），严禁表述为已完成、已解决或已跑通！**  
> 虽然在指令级断点、AArch64 X29 深度栈回溯、模块物理归属（`win32u.so`）、跨架构对照以及信号语义完整性方面取得了决定性的诊断证据突破，但 Windows 侧 Vulkan 实例创建当前依然被 Wine 用户态驱动死锁阻断，x64 链路发生未定位的 `VA=0xf148` 取指异常，图形流水线返回与真实 Steam 客户端握手依然属于**仍未实证**状态。


Round37 (前期阶段记录)：
1. 内存跃迁时间线（task74 / task76已复核）：在主Wine进程中，匿名私有页[0x200ffe000, 0x20106e000) 建立首读时，控制字0x20102d440严格为0x00（reason=first_mapped，完全排除首次可见即非0/堆残留假设A2）；相隔324.207ms（324207µs，跨越约324个1.0ms采样周期，独立复核已纠正原文误写为324.2µs的1000倍量级笔误）后发生唯一一次写1跃迁（val_change：prev=0→val=1，发生在vkCreateInstance早期ICD加载期）；随后在id=855处主线程再次到达该控制字，读取值为1陷入FUTEX_WAIT_PRIVATE无限等待（直到62.11s超时）。
2. 竞争假设最终定性：基于进程内单线程存活、初值全0、随后写1、末端无WAKE挂起的事实，"单线程递归重入自锁"为当前最强证据排他性推测；但在未捕获到指令瞬间casa/stxr及两次完整用户态调用栈前，不能完全排除"异常退出未置2"分支，故定性为强证据推测，撤销"确凿证实"断言。
3. 勘误与规范收敛：task74报告手填错误（run_dir错填为不存在的run-d19x74b_、stderr_bytes第三次错填为149432）已全面纠正为收据与磁盘物理事实：run_dir真实为run-rx848drl、stderr_bytes真实为685764。详见[R36-R37综合验收汇总](r36-r37-summary.md)、[once跃迁复核](once-transition-review.md)。

Round36：团队执行恢复（明确Gemini路由新建成员可正常get/claim；旧成员在claim前失败，且当时Host无成员移除接口，用户已扩大名额）。task69独立复审通过：独立复算R30 95对全配对/0未配对/max 1590419us、R31与R33 cap未耗尽(856/4096)、R33 stderr162616B（报告曾漏填）；并从源码证实两条EL1快路径——shim.S:572 futex_wait_fast仅word!=val时返EAGAIN且必bail回宿主，shim.S:1001 futex_wake_fast仅桶内无等待者时返0、有等待者WAITER_BAIL，故真实WAKE会进入dispatcher被观测。task70首轮不通过（run-dsfxes37 stdout0B无Step3、stderr2558B、FUTEX_OWNER_*全0、误用R33 PID）已驳回重做；重做后VALID：run-7v5a6pa2 stdout486B含Step3、stderr149432B、pid91073/gtid1/id855、62.22s exit124。新硬事实：uaddr0x20102d440不在驱动so，而在匿名私有映射[0x200ffe000,0x20106e000) rw- flags0x22(PRIVATE|ANON) off0x2f440；ELR0x2000ce084/LR0x2000ce048属guest libc.so.6 r-x段off0x8e084/0x8e048；挂起瞬间进程仅gtid=1一个线程，全运行该地址仅此1次futex调用且无WAKE。故非丢唤醒，而是等待发生时同进程无可用唤醒线程；边界：thread_for_each仅覆盖elfuse guest线程表。task71已验收：独立复算libc.so.6反汇编确认0x8e080 svc#0(x8=98,x1=0x80,x2=word)、0x8e05c tbz w3,#0x0→val==1走futex_wait、初始化路径_pthread_cleanup_push→blr x5→stlr存2→x1=0x81 FUTEX_WAKE|PRIVATE,x2=INT_MAX；符号pthread_once@0x8e1a0经ldar w2,tbz #0x1快速返回，慢路径0x8dfc4为静态实现（反汇编器标签pthread_mutexattr_settype只是前一个动态符号，__pthread_once_slow系语义推断非符号命名）。故锁类型确定为pthread_once_t且word=1=正在初始化。task72追踪生命周期确认主进程pid92897全程唯一线程、tid49仅为存活16.7ms的独立子进程，挂起前124事务已回收，与末端等待无关；报告手填错误已勘误（run_dir实为run-iagdhuck，stderr_bytes实为666817，递归自锁下调为推断）。task73四项最小测试在elfuse下实测排除单线程pthread_once通用缺陷、排除全新匿名映射非零、排除fork/clone私有内存泄漏。详见[R36独立复核报告](r36-independent-review.md)。

Round33：task68执行前失败三次后任务级Lead兜底，新ccdc6732观察末端pid55012/gtid1/id855：uaddr0x20102d440/op0x80=WAIT_PRIVATE/val1/word1/timeout0，ELR/LR状态0；未返回到55.11977s截止。EAGAIN/timeout/跨线程WAIT-WAKE控制脚本0.252s/0，但EAGAIN快捷路径与其它线程waker未被完整metadata覆盖。下一步绑定锁对象与同进程精确地址waker。独立审查task69三次执行前失败仍pending，不以Lead自检充独立验收。详[futex参数](futex-args.md)。

Round31：新cc083604固定线程全部syscall尾部856entry（cap4096未耗尽、stderr166KiB内），前855返回，唯一未配对id855 nr98=已核对futex，x0地址8606897216/x2比较值1；尚缺op/timeout/waker。最后read64已返回，不再追管道read挂死。唯一run55.107s/124/targetnull/cleanup[]、0mismatch，下一步有界futex等待唤醒身份与控制。详[syscall尾部](syscall-tail.md)。

Round30：新69dff2bf在统一dispatcher对read/sendmsg/recvmsg配对，五行为控制短读/EOF/EAGAIN/socket收发0.193s/0。实际同pid45108/gtid1共95对全返回（低于128cap），无selected负值、最长1.590419s，最后read64返回64；目标仍55.120s/124/targetnull/cleanup[]。所以不能继续把后续停滞归成这95次I/O某一未返回；下一步覆盖固定线程所有syscall的尾部状态而非全量verbose，详[I/O事务](io-transactions.md)。

Round29：新1676a04c仅固定Step3线程前16个wait入口，短pipe控制红→绿。实际pid42288/gtid1标记后14条read64(gfd6同FIFO)、1recvmsg(POLLIN)及1sendmsg(POLLOUT)同socket；不是启动read16，也非已证单次read长期挂。入口cap用尽，不提供返回配对/全程轨迹，下一步有限事务进入/返回，不采载荷。唯一run55.124s/124/targetnull/cleanup[]、0mismatch，详[调用后窗口](poststep-wait.md)。

Round28：流式scanner红→绿（dup/writev/split原3失败，新7case全过），新4c6273c7诊断实际捕获Step3 pid34442/gtid1/gfd10，下一行vkCreateInstance；解释旧fd1限制漏检。身份/path/start/owned组核对后sample成功，88主线程样本全在io_xfer→io_wait→poll。此次实际PE归属已闭合；具体fd/方向尚未闭合，标记后没有新阈值行，不套启动read16。唯一run55.122s/124/targetnull/cleanup[]、0mismatch。详[流式身份与PE栈](stream-identity-sample.md)。

Round27：冻结ef7cd2a8身份检测器真实小矩阵：plain write识别；dup fd、writev跨iov、split write均漏检；无关输出不误报。五次目标均0/noTimeout/cleanup[]，0.15–0.17s；1 test-method含5 subcases用于刻画缺口而非修复通过。普通发现8 tests、7pass/1live skip，无Wine重跑。下一步共享有界流式scanner与host输出对象核对，先负例转正再重采样。详[身份覆盖矩阵](fixture-identity-coverage.md)。

Round25–26：fixture stdout身份观测的初版控制发现sys_write快速路径绕过；诊断gate下送既有slow_path后最小控制0.186s/0且单标记成功。但唯一实际Wine运行虽有Step3 stdout，metadata仍缺失（55.104s/124/targetnull/cleanup[]），未选择PID、未执行sample。限fd1/sys_write覆盖未闭合，后续先小控制查dup/writev/分片，不重复相同重跑。详[PE身份采样覆盖](pe-identity-sample.md)。

最新里程碑：离线Steam-shaped wrapper→elfuse/HVF→真正Linux Python→未改Proton脚本→Wine/FEX→x64 hello 已由执行员和独立审查员实测输出`X64_FEX_OK`且整体/目标均exit0。生命周期最终派生版`f2a678dd...`也通过这条离线wrapper链，证据`logs/steam-handoff-review/run-9wflgjgy`（40.47s）。这不是原生Steam检测/点击Play实测，也不是图形游戏可玩证明。快速回归独立123项：122 PASS、1显式live测试SKIP。原上游源码clean、原包关键hash及Proton脚本cmp均通过，见[最终分层审计](continuation-final-review.md)。

Round24重要纠正：新01129827诊断读取阈值guest ELR/LR、gtid/syscall，控制2.528s/0；实际rootPID30942 read16/syscall63在stderr20行，vkCreateInstance在263行。故round22宿主栈仅证明owned启动根在poll，尚未绑定执行PE的Wine子进程，不得等同Vulkan调用线程栈。下步先建立有限owned进程树与PE对应身份，停止凭16B/rootPID误归因，详[I/O调用现场纠正](io-wait-context.md)。Vulkan仍55.114s/124/targetnull/cleanup[]，0mismatch，未完成。


Round23：新19040d51诊断仅io.c阈值元数据，管道控制2.509s/0/cleanup[]。唯一Vulkan55.121s/124/targetnull，0 mismatch；34条>=2s等待全是FIFO POLLIN，33条want16、1条未知context。缩小为pipe读等待而非write堵塞，尚未绑定主Vulkan线程及对端；官方ntdll server.c wake_up_reply为候选非证明。详[I/O等待身份](io-wait-identity.md)，不把正常后台wait当死锁，下一步关联具体pipe/wait调用点。


Round22：对精确owned target核对PID/PPID/start/proc_pidpath后，唯一native sample1秒exit0、87主线程样本全为syscall_dispatch→io_xfer→io_wait_fd_timed_or_interrupted→host poll；无GDB。故采样窗口主等待是host I/O就绪，而非guest持续执行。方向/具体fd/peer尚未知，不等于poll缺陷或WineServer已定位。原io.c未变；预算55.106s/124/targetnull/cleanup[]，0 mismatch。下一步定点阈值I/O元数据，不重复Vulkan参数实验，详[native等待栈](native-wait-sample.md)。


Round21：新增有界read-only GDB RSP客户端及7项纯测试均过；06runtime上busy-loop控制实测interrupt返回PC/SP、detach OK、目标3.20s/0。相同接口对60诊断版Vulkan在Step3+null确认后连接成功但没有停止回复，receive超时，未取得PC；最终仍70.123s/124/targetnull，0 mismatch。禁止声称抓到栈或由此证明host阻塞；下一步精确owned target的有限native sample，不重复GDB中断。详[GDB探针](gdb-probe.md)。


继续批次：目标已由本次明确继续指令扩为40轮并恢复active。官方Wine显示宿主扩展枚举后进入user driver惰性加载/desktop消息同步候选；新独立prefix仅设Graphics=null，实际explorer日志确认null生效，但同60诊断版Vulkan仍70.12716s/124/targetnull/timeout，0 mismatch。显式null也不足以解除停滞，不再盲延时或重复；下一步使用elfuse自带loopback GDB RSP捕获guest线程PC。详[Vulkan下一等待](vulkan-next-wait.md)。


Round20：同60binary关gate反向A'恢复14 mismatch（39.217388s/DPI96/38/noTimeout/cleanup[]），加强shared更新可见性→警告因果证据。gate开后唯一ARM64 Vulkan验证0 mismatch但vkCreateInstance仍未返回，outer70.121939s/124/targetnull/timeout；宿主扩展列表可达，不是实例成功。因此会话可见性不是解除Vulkan停滞的充分条件。63backend+38probe纯回归通过，四冻结摘要及原sourceclean再次核对。详[因果最终分层报告](mmap-causal-final.md)。诊断PRIVATE→SHARED牺牲COW，不得默认接入；正确兼容实现/图形/真实Steam与独立复验仍欠缺，总目标未完成。


Round19因果诊断：独立60f87660...仅在明确envgate下把O_RDWR/unlinked/off0/len0x144000/privateRW候选按SHARED走完整既有bookkeeping，四进程命中同inode；一次DPI39.3093s/38、DPI96/noTimeout/cleanup[]，ID mismatch从上轮14条降至0。支持候选映射更新可见性与警告因果联系，但该干预故意牺牲PRIVATE写隔离，**不是ABI修复、不可接默认后端**；尚待同binary关gate反向对照与独立复验，Vulkan未测。见[因果干预](mmap-intervention.md)。


Round18：新增独立仅mem.c诊断派生3bd19d04...，bounded PID/dev/inode/F_GETFL观测先控制0.25181s/0，再唯一DPI39.529472s/38、DPI96且14 mismatch仍在。23条记录/8PID/stderr8124B：unlinked同inode17175306长度0x144000，server候选sharedRW与4client候选privateRW|fixed均实际O_RDWR，纠正把O_RDONLY旁证直接套真实候选的假设。未绑定section名/实际objectid，不改映射语义或接默认后端。见[mmap文件身份](mmap-file-identity.md)。当前团队两成员恢复失败，独立审查欠缺仍明确保留。


Round17：task59新COW前缀、冻结06runtime的唯一--verbose/+virtual DPI运行47.976382s，DPI96/overall38/target38/noTimeout/cleanup[]，仍14条session ID mismatch。实际有1427条匹配到的RW+PRIVATE|FIXED文件mmap请求，但日志无fd路径/access与可靠per-process身份，故session文件身份/因果仍未闭合。全量trace435648689B已保留且仅流式抽取摘要，不再重复此低效观测，见[wine-map-trace](wine-map-trace.md)。下一诊断需独立派生runtime的有上限PID/dev/inode/hostfd access定点观测，不能凭数字fd推断会话文件。


Round16回到官方源码：原包build label为experimental-11.0-20260924-arm64；官方日期邻近Proton58a40f82→Valve Wine dc26e618（候选，非认证精确构建）。该Wine virtual.c明确Linux只读section使用RW+MAP_PRIVATE并依赖Linux文件修改可见性，不是简单RO；新增O_RDONLY/RW-private对照实测：后续共享更新仍不可见，但client私写不污染server/文件，0.241372s/exit0/noTimeout/cleanup[]。见[官方源码对齐](proton-wine-source-alignment.md)。未改原件、未新执行会话；现有团队恢复仍失败，新增对齐/对照不声称独立验收。


Round13–14：HVF真实四case证据已由总Lead逐项复核：匿名hostRW与文件hostRW→HV_RWX均0，但O_RDONLY/hostR→HV_R及HV_RWX均0xfae94001，create/unmap/destroy正常、seed前后摘要一致；因此降stage-2权限的简单路线未通，见[总Lead复核](hvf-readonly-lead-verification.md)。新的运行器加固经团队完成后又发现缺执行元数据仍可判定的问题；round14新增严格classify_execution入口并切换运行器，38项纯测试通过，原JSONL离线重分类仍同结果，见[执行级补验](hvf-execution-evidence-followup.md)。没有额外HVF/Wine重跑；当前团队成员恢复仍失败，新补验不声称独立复核。依用户反馈停止通过任务板另建执行会话绕过当前8成员上限。


Round12–13独立复核补齐：新Gemini任务板团队已产出[私有映射独立复核](private-map-coherence-review.md)与[团队审查汇总](mapping-team-review-summary.md)，真实7/7纯测试及原日志计数已由本Lead读件复核；Lead另跑21项新增探针分类器测试均通过，`logs/lead-round12/new-probes-tests.log`。根卡f741853b的最终状态failed原因是Host跟踪子会话历史地址失败（ownResult=succeeded），不是质量失败；子卡5ee78fe6记录外部审查完成及报告，不能写成Host整树成功。REA进程采集在运行测试前因缺失其Swift辅助源文件失败，已改用现成CLI执行纯测试，未修全局包。新HVF权限微探针团队bfa2578c/a703d2eb已启动，限一次短HOST API进程，无guest执行；原runtime冻结。

Round11：最小文件映射观测已完成，见[私有映射可见性](private-map-coherence.md)。Darwin与elfuse下均复现private RO仍0而shared RO/RW及pread文件均0x1234abcd；Linux ELF诊断0.229729s/0/noTimeout/cleanup[]。7纯测试通过。该结果不等同POSIX保证或Wine根因已证；版本Wine11.0源码已证session locator校验失败路径，随后单次+winstation原生DPI观察已得到14条live object-ID mismatch（目标仍返回96 DPI/exit38、无timeout/cleanup），详[会话ID观察](wine-session-id.md)。实际Wine内存对象id值未读；private快照与该缺项因果关系仍待派生runtime RED→GREEN，不直接放开MAP_PRIVATE写共享。团队恢复尝试：当前允许模型gemini/gemini-3.8-flash-high；显式新成员创建在修复空reasoningEffort参数后返回Team member limit8 reached，既有8成员均inactive且本会话无成员移除/重设路由工具，新增独立复核仍欠缺。


Round10补充：团队会话反复失败后，task55/56仅按任务级兜底执行，独立复核仍欠缺，未扩展为默认单人流程。原生ARM64新增阶段探针已实测通过kernel32输出/37、user32加载及GetDpiForSystem=96/38、vulkan-1加载返回/39（三次各约40s、无timeout/cleanup错误），见[ARM64加载阶段](arm64-loader-probe.md)。task57随后已验API：原生ARM64 PE成功加载DLL并解析函数，但vkCreateInstance未返回，outer70s超时124、target_exit=null、cleanup[]；时间戳确认desktop/shared-session错误，详[原生ARM64 Vulkan API](arm64-vulkan-probe.md)。这说明缺项不只出现在x64/FEX目标，仍不宣称实例/设备已通。task58转向最小文件映射可见性测试：elfuse的readonly MAP_PRIVATE走pread快照，与Wine会话共享文件更新的Linux特定假设可能不匹配；该线索尚待真实ABI测试，未修改运行时。另[官方发布补查](official-source-recheck.md)在最新三个Valve GitHub release的assets均为空，仅源码tarball，现有seed来源置信度不提升。


### 最新增量验收（task39–54）

| 层级 | 最新证据 | 判定 |
|---|---|---|
| 原件完整性 | Lead再验上游clean/HEAD 8612033d...；f2、06、phase摘要一致；派生Proton脚本与公开包原件cmp0 | 有限完整性通过；发布者身份声明不等Valve签名认证 |
| 后端/中继计划 | Lead后端63项6.116s通过、未再出现ResourceWarning；新增计划命令PLAN_READY且execution_performed=false | 计划态与路径校验通过；未安装真实Steam |
| 新runtime+phase裸FEX | A79.28s、B63.98s均hello/overall0/target0，无timeout/cleanup错误 | 此控制台配置通过；不作性能/全应用泛化 |
| Windows Vulkan | 原PE实例入口未返回；task54新观测停在LoadLibrary Step1，内部90.34s/-15，9处INIT_DONE/未见throw marker | 图形尚未通过 |
| Linux软件Vulkan | CPU设备枚举与256B TRANSFER回读已独立实测 | 不代表Windows桥、shader或Metal已通 |

本索引下文包含各阶段历史测试计数，不能简单求和当作当前唯一套件计数；卡片完成只表示该实验记录或修复任务已交付。


下列按实验推进顺序记录，失败对照不因后续绿灯被覆盖：

第一轮的包获取阻断已有新进展：公开再分发 Proton seed 已取得并核验发布者摘要；Wine/wineserver 版本查询与 FEX native 模块加载已在 elfuse/HVF 下实测成功。Windows ARM64 最小 PE 入口执行已由 Lead 独立复现，返回预设退出码37、未超时（`logs/lead-round3/run-tdsalxey`）。Windows x64 最小 PE 也已由 Lead 在独立前缀复现入口执行，返回预设43、无超时，FEX成功Loaded（`logs/lead-round4/run-3uc3xfl0`）。该验收使用恢复原始prctl行为的layout-only派生elfuse（SHA256 `0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7`），不是原始未修elfuse；先前假能力实验B仅归档，不作为验收件。layout-only版本Win32 hello仍输出后-11；新增空指针保护候选已由Lead独立跑出X64_FEX_OK且overall/target均0（`logs/lead-round5/run-54af6nhn`），仅验收当前case防护，不宣称后台线程生命周期已完整修复。不得把下方第一轮历史状态继续作为最新结果。

- [公开包获取、来源置信度与真实二进制审计](public-proton.md)
- [动态 glibc / 共享内存 / 信号 / futex / spawn 实测](continuation-abi.md)：当前原始 elfuse 3PASS、2FAIL
- [隔离后端与 Steam 离线准备](continuation-backend.md)、[后端返工交付](backend.md)：Lead 独立后端27项通过，并复验超时忽略TERM目标已清理；真实Steam仍未接入
- [当前集成诊断](current-integration.md)：新增显式公开清单模式，不把包摘要验证写成组件执行成功；Lead 独立复跑集成17项通过，公开模式 exit10、历史直接模式 exit20，见 `logs/lead-current-integration`
- 本轮总复跑：`logs/continuation-validation/summary.json`
- [独立复审](continuation-review.md)：进程身份清理经历两次缺陷发现及真实黑盒复验，27项后端与独立黑盒通过后已批准；该批准不涵盖 x64/FEX 游戏运行
- [派生 futex 修复](abi-fix.md)、[独立边界审查](abi-independent-review.md)：原始最小用例已由红转绿，Lead 独立套件通过；WAITV/错误映射最后修订已核实，批准范围为有限共享WAIT/WAKE实验支持，负wake计数/独立clear_child_tid验证等限制明确保留，不称全Linux同步兼容
- [Windows PE 初轮对照](runtime-worker.md)、[地址布局修正与x64入口](fex-init.md)：历史x64超时已推进至layout-only minimal-x64 exit43；完整hello输出后崩溃仍未解决。独立克隆需保持prefix相对链接深度，首次Lead浅层clone导致c0000135的失败同样保留。
- [FEX初始化静态观测点](fex-init-static.md)：硬件TSO/unaligned回调失败分支可继续返回，不将静态unsupported当停滞根因；真实layout-only运行也已证实无需伪prctl成功。
- [layout-only运行独立终验](fex-runtime-review.md)：第三端独立前缀run-l84rpgk3再次x64 exit43/no timeout，ARM64 exit37；hello独立再现输出后-11，批准仅限最小入口执行。
- [FEX日志诊断修复](fex-diagnostics.md)：Lead独立24PASS，并回放真实加载失败、x64入口成功、hello输出后崩溃三类日志，分别正确分类；初版overall失败却whole_success为True的问题已返工修复。证据`logs/lead-round4/diagnostics-final.log`。
- [host崩溃观测与候选保护](fex-crash.md)：已改用进程内观测双端捕获preempt_thread_main→signal_queue→shim_globals原子访问无效地址的PC/FAR/stack。Lead独立红灯`logs/lead-round5/run-k2pfdau5`；明确候选binary f83455b0...双端hello输出+真实exit0，Lead绿灯`run-54af6nhn`。这只是candidate-proven，判空仍有TOCTOU与后台线程未停问题，不当完整生命周期修复。
- [后端显式runtime选择](backend-runtime-selection.md)：增加--elfuse而不改默认原版/plan-only；真实hash匹配来源、40hex commit与patches分列、execution NOT_CHECKED。Lead独立backend41PASS与显式计划验证见`logs/lead-round5/backend-runtime-final.log`和`explicit-derived-plan.json`。
- [teardown独立审查](fex-teardown-review.md)：候选能防当前case但preempt线程无stop/join、cache_base其他caller漏判、unmap TOCTOU等风险需根治。
- [真正Linux Python→原Proton启动链](proton-launcher.md)：原脚本与公开原包cmp一致，完整run minimal-x64实测exit43；runinprefix hello由Lead独立克隆后实测输出X64_FEX_OK且overall/target均0、no timeout，`logs/lead-round7/run-2bxmxfs0`。完整run hello仍150s超时并有explorer桌面建窗错误，不用runinprefix替代该失败结论。
- [生命周期根修复](fex-lifecycle.md)、[独立分支审查](fex-lifecycle-review.md)：最终f2a678dd...版本停止/join preempt后才unmap，补齐fork-child失败状态传播与kill ESRCH后继续join、join必须0的分支。真实生产符号host6项PASS，reviewer最终directWine hello0；较早3ace先版Lead独立hello也0。故障注入未动态覆盖仍UNKNOWN，不称全路径稳定性证明。
- [Proton新旧runtime对照](proton-contrast.md)：保留Lead最终版组合链110s超时`run-rkbehni4`；顺序同snapshot对照old f834/new f2均输出+exit0，new `run-x0q7o2qx`46.05s。并发日志重叠只是候选解释，超时排他根因未定，有限日志差异不证明全部行为等价。
- [离线Steam-shaped真实入口](steam-handoff.md)、[独立双runtime终验](steam-handoff-review.md)：新wrapper从lab外cwd运行、保持Unicode/空格/metachar参数，默认plan-only与显式execute分离，存储runtime hash执行时核对。后端Lead独立50PASS；reviewer独立f834与f2 wrapper链均hello输出+真实0。配置仅lab mock/appliedfalse，未安装到真实Steam。
- [Vulkan底层实测](graphics-probe.md)：真正Linux loader/instance创建成功，设备枚举返回VK_ERROR_INITIALIZATION_FAILED(-3)，Lead独立`logs/lead-round7/run-r_9wfv85`同结果。失败返回时count初值0不代表有效设备数量，Vulkan渲染路径未通过；不将此直接归因为桌面建窗唯一原因。
- [隔离lavapipe软件Vulkan](software-vulkan.md)：取得Arch ARM镜像2包（37.65MiB）到独立目录，无global安装/root覆盖；HTTP下载与本地摘要已记录，PGP与repo-db预期摘要未验证，置信度不夸大。Lead独立`run-3i7xsthu`枚举VkSuccess、validCount1、CPU llvmpipeLLVM23.1.1，不是Apple GPU/Metal。
- [软件Vulkan实际队列读回](vulkan-queue.md)：createDevice/commandBuffer/vkCmdFillBuffer/queueSubmit/fence/map读回均实测，Lead独立`logs/lead-round7/run-ohoyse2p`（2.72s）256B/64字全等0x1234ABCD，7类资源清理，classifier6PASS。仅TRANSFER命令，不声称compute shader、draw或交换链呈现。
- [Windows x64 Vulkan桥实测](windows-vulkan.md)：真实PE经Wine/FEX成功LoadLibrary/解析Vulkan入口并进入vkCreateInstance，读到Linux侧ICD扩展；3次100s实验均未取得实例返回，日志有桌面创建失败。禁explorer的变体与正常基线分列，不当排他根因。原运行PE dc47...与新增CPU后验断言编译件f77...分列，后者未重跑。生产分类器Lead独立8PASS，不把单测当API成功。
- [headless显示隔离可行性](headless-display-feasibility.md)：Unix pathname socket目标映射sysroot，长路径shortening与abstract sockets可能创建host/tmp中继，不能假定全部lab内。
- [Xvfb实验](xvfb-wine.md)：隔离获取Xvfb并完成一次认证X11连接；Wine内部出现Created instance后有SEH invalid-frame/STATUS_INVALID_DISPOSITION，目标PE stdout仍停在Step3、最终超时，不能称Windows侧vkCreateInstance已返回成功。初版controller主动用:97、setsid/killpg清理、auth创建与lstat检查存在审查问题；经2次返工与task38独立审查，已移除colon回退、同组管理直接子进程、原子0600创建、lexists、displayfd编号断言、PID/inode匹配清理。Lead新跑执行员7项与独立8项fake测试均通过（logs/lead-round7/xvfb-{controller,independent}-final.log）。修后未新跑真实server，原“host/tmp零触碰”结论保持未证明，不再用无新目录推断无abstract调用。
- [lab套接字中继](socket-base.md)与[独立审查](socket-base-review.md)：新06a2fceb...派生构建基于f2，仅2处源文件变更，显式native `ELFUSE_ABSOCK_BASE`支持lab私有目录，unset保留旧行为，无效显式值硬失败。reviewer独立实测abstract/长pathname中继真实inode、跨exec继承、getsockname还原与基址0700保留，不以目录计数推断host/tmp全域零写。原f2与上游冻结不变。
- [C++异常观测器](badalloc-trace.md)：v2 6f034d0a...支持global与RTLD_LOCAL已加载libstdc++的NOLOAD解析。Lead独立4次真实ELF原/preload对照均catch42/exit0，见logs/lead-round7/badalloc-local-global.log；初版local-scope127红例保留。真实OOM时观测器内部backtrace/stdio再分配、其它C++runtime仍未知。
- [异常观测](wine-badalloc.md)与[独立审查](wine-badalloc-review.md)：task42实际共3次运行，前2次prefix依赖准备错误126，第3次外controller0但内部Wine85s超时/-15且NO_TRACE，不能把外0当目标成功或无trace当无异常。该阶段未取得所需原生栈，LD_LIBRARY_PATH/启动方式相对task37的漂移为候选解释，不是排他根因。task46以已知fullprefix+完整原LD路径与Linuxsh调用作一次新对照，结果为Wine60.21s后FEX/preloader看门狗124，未到目标Vulkan，NO_TRACE；旧3run原始事实全部保留。task47/49新phase库105aaa...已通过纯C/global/local/helper共4组原/preload ELF对照，初始化与throw首标记先于高层栈观测，后续backtrace与cache多线程边界仍未知。task48裸hello双臂均0.17s/139，B有INIT_DONE；随后task50四个快探针识别新增clear-env环境profile差异：shelltrue两臂0，Wine--version clear139、恢复受控profile0/wine11.0。task52恢复profile后裸hello配对已真实通过：A run-9ku8aeiz 79.282899s、B phase库 run-y6puawlg 63.983342s，均X64_FEX_OK/overall0/target0/无timeout/cleanup[]；Lead逐项读原result与stdout确认，B有9处INIT_DONE。仅确认此console配置，时间差不是性能改进证据，未推广图形；task54以相同profile+phase库作单次Windows Vulkan对照，实际在LoadLibrary Step1未返回，内部90.34s/-15（外controller0），9处INIT_DONE/未见throw marker。task55有限静态审计确认vulkan-1与原bundle字节一致、ARM64X/EC混合DLL，导出vkCreateInstance转发至winevulkan；其ARM64 DllMain在PROCESS_ATTACH调用DisableThreadLibraryCalls再GetDpiForSystem。DPI/session初始化成为下一最小观测候选，不是已证死锁根因；task56转为原生ARM64 kernel32/DPI/LoadLibrary阶段门控探针，不再重复整段x64图形超时。
- [后端参数接入](socket-backend-integration.md)与[独立复审](socket-backend-review.md)：--absock-base已显式接入CLI/Steam-shaped准备器，known06 hash支持、旧/未知拒绝，plan不建目录，执行前重检mode/叶子软链接；开发与独立后端均63PASS，独立负例12PASS。新socket-plan-only与socket-review-plan均未安装/默认计划态。同属主同权限新目录替换inode的身份绑定仍未覆盖，文档如实注明，未声称其通过。
- 真实Steam客户端检测/点击Play、图形游戏和Steamworks仍未验证。原件与已验派生构建保持冻结。

以下保留第一轮历史报告，便于核对当时的证据与结论。

---

# 第一轮执行实验交付（历史快照）

## 结论

本轮调查与已具备条件的实验已交付，核心技术目标尚未达成。原版 Valve ARM64 Proton 包未取得，Wine、wineserver、FEX Windows x64 执行及真实包依赖审计均为 NOT_RUN。隔离 SteamCMD 匿名请求实际返回 No subscription；这是获取阻断，不是 Linux ABI 兼容失败。

## 已验证

- elfuse 固定提交 8612033dab8dc60728f604a4ea0441895fc16d39，源码 clean，构建产物带 Hypervisor entitlement。
- 五项正向执行：ARM64 汇编 hello、独立 C ELF（退出42）、mmap/mprotect/JIT返回77、clone/wait4回收子进程退出10、glibc ld.so --help；两个负向ELF输入检查，共7项通过。不是完整动态glibc应用或Wine兼容证明。
- Steam离线日志探针与候选清单20项测试通过。候选包含-- %verb%，但未安装到Steam；发现/可选/Play实际调用均未测试。
- Proton工具12项：11通过，1项live网络测试跳过；其中ELF/PE审计测试使用合成fixture，不是真实包。
- 集成检查12项通过；真实环境诊断exit20，明确BLOCKED package、NOT_RUN Wine/FEX。
- 审查员另验证假二进制注入使baseline runner准确返回1。

## 独立证据

Lead复跑：logs/lead-validation/run-9yp6x0hn（Steam20通过、baseline7通过；最初audit直接文件调用导入失败保留audit.log，正确unittest discovery重跑见proton-unittest.log：11通过1跳过）。集成12通过与真实exit20见logs/lead-validation/integration-jc22b_y3。

最终独立审查：reports/review.md；原始日志logs/review/final/run_20261015_101011。

包身份见artifacts/proton/identity.json：steam_tool_app_id=4427310、steam_depot_id=4427311；local_package_path与sha256为空。Steam Build及体积信息仅为已记录元数据，不是已下载包身份。源码tag与Steam Experimental包版本分开。

## 复现

在实验根目录执行：

```bash
python3 -m unittest discover -s tests/steam -v
bash scripts/elfuse/run_all_baseline.sh
python3 -m unittest discover -s scripts/proton -p "test_*.py" -v
python3 -m unittest discover -s scripts/integration -p "test_*.py" -v
python3 scripts/integration/check_prerequisites.py --json
```

最后命令当前预期exit20，不是成功运行Proton。检查器仅诊断，不是自动包导入器。

## 下一步

由用户通过自己的Steam账号在支持的安装环境取得完整官方ARM64 Proton目录，复制到artifacts/proton/raw，保留proton脚本、files目录、Wine/wineserver、FEX模块、版本文件及完整符号链接；记录来源与App/Depot/Build/Manifest信息后，再实际计算摘要和审计依赖。请勿发送账号密码、Steam Guard码或登录文件。复制目录不会自动让前置检查器READY，仍需真实身份/完整性/依赖核实。

获取后继续Wine/FEX控制台实验；图形、Steam客户端入口和Steamworks分别验收。当前不声称游戏可运行、Steam已识别Proton或游戏性能已知。

## 边界

本轮没有修改真实Steam配置、安装全局包或commit/push；实验产物保留在独立lab。最后进程检查未见本实验elfuse或SteamCMD残留。局部objcopy只服务shim的Mach-O __text提取，非完整GNU替代，已有字节核验。上游源码保持原样。
