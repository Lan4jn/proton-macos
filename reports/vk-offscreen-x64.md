# Task-137：x86_64 PE 离屏三角形实运行验收

## 结论
真实 AMD64 PE 在现有 ARM64 Wine/FEX 适配器链路下完成离屏绘制与像素读回。先执行真实 `--skip-draw` 负对照，再执行正常绘制；两路结果来自本轮 x64 PE，未使用 ARM64 运行结果替代。

## 构建与架构
- 原始复用源码：`sources/vk-offscreen-probe/vk_offscreen_arm64.c`；对应原 ARM64 PE SHA：`112377ef135b5bb3d240646b665b1747bc21078ec8ee2272208bec2c1ae11e22`。
- 新目录：`sources/vk-offscreen-x64/`。同一绘制、同步、invalidate 和校验逻辑；变更仅架构输出标签及 AMD64 无 CRT 链接所需 `_fltused` 标记。
- 构建：`sh sources/vk-offscreen-x64/build.sh`；命令、shader 校验结果保存在 `logs/vk-offscreen-x64/build.log`。
- 编译：`clang -target x86_64-pc-windows-msvc -c -O2 -fno-builtin`；链接：`lld-link /machine:x64 /entry:main /subsystem:console`；导入库使用 `llvm-dlltool -m i386:x86-64` 重新生成，未复用 ARM64 导入库。
- `file`：PE32+ executable (console) x86-64；`llvm-readobj`：`IMAGE_FILE_MACHINE_AMD64 (0x8664)`，证据 `pe-architecture.txt`。
- AMD64 PE SHA：`aba1c08ccbc7c8f4569c7177cc96032a7baf87c3b255506f1c8f5a452a0a1ae9`。
- 两份 SPIR-V 原样复用且均重新通过 `spirv-val --target-env vulkan1.0`；SHA 收录 receipt。首次链接缺 `_fltused` 的构建失败已定位并以 ABI 标记修正，未修改绘制逻辑。

## 安装与执行身份
- 新脚本 `scripts/runtime/vk_offscreen_x64/run_probe.py` 只读调用已有 steam_plan/steam_handoff，未改 backend。独立目录及 prefix：`logs/vk-offscreen-x64/runs/`。
- 安装目标 `fixture_steam_root/compatibilitytools.d/proton_x64_offscreen/proton-wrapper.sh`；源包移动至 `source_pkg_MOVED_AWAY` 后才运行。
- 命令：`proton-wrapper.sh runinprefix C:\vk_offscreen_x64.exe --skip-draw`，随后去掉 `--skip-draw` 执行正常绘制。完整 elfuse argv、run 结果、配置存于各 run 目录和 receipt。
- 使用已验证 runtime、win32u SHA59a76b05、shipped winevulkan.so SHA2786ca6f 与原 PE 配对；guest LD_LIBRARY_PATH 保留 lavapipe 与 sysroot 路径，default_pfx_arm64/creation_sync_guard 保留。
- 宿主 Darwin arm64，测试 PE 为 AMD64；prefix 的 `libarm64ecfex.dll` 注册项和行号收录 receipt。这些证据支持既有 FEX 链路归属；本轮未额外打开翻译器模块加载 trace，未宣称获得 FEX 内部每个翻译块证据。

## 两路原始结果
| 项目 | skip-draw（先跑） | 正常绘制（后跑） |
|---|---|---|
| run目录 | run-maoj7dnv | run-rncg5vo3 |
| wrapper耗时 | 109.346s | 84.445s |
| target退出码 | 21 | 0 |
| Vulkan实例/物理设备 | 创建成功，count=1，llvmpipe | 创建成功，count=1，llvmpipe |
| 实际绘制 | 显式跳过vkCmdDraw | vkCmdDraw(3) |
| fence | signaled | signaled |
| 像素判定 | 首个内部点(32,38)蓝色，预期判负 | 4内部红+4外部蓝，8点PASS |
| cleanup_errors | [] | [] |

- 负对照输出：`skip_draw_stdout.log` / `skip_draw_stderr.log`。PE 在首个内部点 mismatch 处 ExitProcess(21)，早于保存文件；因此不虚构负对照 framebuffer。
- 正常输出：`normal_stdout.log` / `normal_stderr.log`。实际枚举 count=1 的 stderr 行号分别为负对照11516、正常10579（也收录receipt）。
- 正常 raw：`normal_framebuffer.raw`，64×64 RGBA8，共16,384字节，SHA `2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050`。
- PNG：`normal_framebuffer.png`，由raw无损转换；274字节，SHA `09ae27e9e5282d0276b1e6c0620e53a58b787aed304205335de92c16d207226f`。已核看为蓝背景红三角形。
- 独立校验：`python3 scripts/runtime/vk_offscreen_x64/finalize.py`，复用验收器从raw重新采样，不依赖PE自报PASS。

## 8点读回
| 位置 | RGBA | 期望 |
|---|---|---|
| (32,38) | 255,0,0,255 | 内部红，PASS |
| (32,25) | 255,0,0,255 | 内部红，PASS |
| (22,44) | 255,0,0,255 | 内部红，PASS |
| (42,44) | 255,0,0,255 | 内部红，PASS |
| (5,5) | 0,0,128,255 | 外部蓝，PASS |
| (58,5) | 0,0,128,255 | 外部蓝，PASS |
| (5,58) | 0,0,128,255 | 外部蓝，PASS |
| (58,58) | 0,0,128,255 | 外部蓝，PASS |

## 分层判定与限制
- TRUE：AMD64构建、安装目标wrapper执行、ARM宿主上x64 PE翻译执行、Vulkan实例、count≥1、真实负对照exit21、正常exit0、8点独立校验、回滚指纹一致。
- FALSE（本环境不是该能力）：硬件GPU加速；实际设备为 CPU llvmpipe (LLVM23.1.1,128 bits)。
- UNKNOWN / 未测：gate-off正常COW、交互游戏窗口、Steam游戏兼容性及性能。
- `ELFUSE_DIAG_SESSION_SHARED=1` 仍启用，存在针对匹配私有映射牺牲隔离的诊断caveat；本结果不声称修复COW。
- `rollback.json` status=success/errors=[]；`fingerprint_pre.json` 与 `fingerprint_post.json` 独立比较相等。
- 未改 fixtures、原runtime、backend 或已验收ARM64探针。无全局killall、无commit/push。

## 工件
`receipt.json` 汇总 SHA、精确argv、raw运行结果、错误行、8点数据、FEX配置证据、分层判定和回滚状态；`source-port.diff`、`build.log`、`pe-architecture.txt`、两路stdout/stderr及各run原始result保存在 `logs/vk-offscreen-x64/`。
