# macOS 原版 ARM64 Proton 执行层实验设计

日期：2026-10-15
状态：用户已于后续对话明确批准按此路线执行。补充：并行制作 Steam 日志型适配器及离线测试，不安装至 Steam，也不修改客户端配置。

## 目标与决策

最终目标是原生 macOS Steam 运行 Windows-only 游戏。本轮仅验证执行层：接受 Hypervisor.framework，使用 elfuse 运行原版 Valve ARM64 Linux Proton。排除完整 Linux 系统 VM 和 Darwin Wine 重编译，保持 Steam 原状。

技术成功标准：通过原版 Proton 的 Wine/FEX 路径执行 Windows x64 控制台程序，核实程序架构、实际 FEX 路径、输出、退出状态与进程清理。版本查询和 ARM64 ELF 成功仅是局部通过。

## 已观察环境

宿主 arm64；macOS 27.0.1，Build 26A434；kern.hv_support=1；Xcode 开发目录 /Applications/Xcode.app/Contents/Developer。PATH 有 Git、Clang、Make、codesign、Python、CMake、Homebrew；未找到 objcopy、llvm-objcopy、Ninja。实际 HVF 运行和工具链完整性尚待验证。

## 方案选择

采用固定上游版本、逐级验证。不采用边测边补大量 elfuse 接口，不并行移植 Darwin Wine/FEX，避免扩大范围或改变研究对象。

## 目录与隔离

实验根目录 /Users/mewcapoo/Projects/proton-macos-lab。docs/superpowers/specs 和 plans 保存规格与计划；sources 保存固定源码；artifacts 保存原版包、来源与 SHA-256；sysroots 保存动态依赖；fixtures 保存最小程序及源码；scripts、logs、reports 保存复现入口、原始日志与结果。

原版 Proton 不修改。HOME、prefix、临时目录位于实验根目录，避免使用真实用户 Wine 环境或连接已有 Wine 服务。原始与派生产物分开。

## 阶梯与依赖

1. 核实工具、磁盘空间，固定 elfuse 提交与构建参数。
2. 构建 elfuse，验证静态 ARM64 ELF。
3. 并行取得固定版本原版 ARM64 Proton，审计 ELF、PT_INTERP、DT_NEEDED、glibc 符号版本和 Wine/FEX 模块。
4. 验证动态链接、共享内存、线程同步、信号、mmap/mprotect 与 JIT。
5. 验证原版 Wine、wineserver 通信及最小 Windows 程序。
6. 验证 Windows x64 控制台程序，确认实际经过 FEX。
7. 独立复核命令、日志、架构、输出、退出状态和清理。

下载前评估包大小和剩余空间。执行前记录具体版本、URL、SHA-256 与源码提交，不以移动分支名作最终复现身份。原版包获取若需要账号交互，记录获取阻断；不读取本机 Steam 凭据，不以重编译包冒充原版。

## 团队职责

elfuse 执行员与 Proton 包审计员并行工作，分别负责基线构建测试、原版包和依赖清单。集成执行员在前置通过后执行 Wine/FEX 测试。审查员独立检查并复跑最小命令。Lead 负责规划、任务书、协调、复审和交付，不覆盖执行员模块。派发时细分写入路径。

## 错误与变更边界

阶段状态为 passed、failed、blocked、not-run。失败收集最小复现、错误和接口证据，最多两轮诊断性复验；不展开大型 ABI 补写。依赖后续步骤记 not-run，调查闭环不等于技术通过。

测试设置超时，记录实验进程身份，只清理本实验进程，不使用广泛 pkill。仅修改实验目录，不改 Steam、系统配置或全局包环境，不创建 commit、不 push。缺工具先找已有安装或目录内构建，额外外部变更单独确认。

## 交付与排除项

交付固定版本清单、SHA-256、复现命令、原始日志、阶段结果与下一步建议。成功需完整 x64/FEX 执行证据；阻断报告明确技术目标尚未实现及首个经复验缺项。只报告实测耗时，不推算游戏 FPS。

排除图形、Vulkan/Metal 桥接、游戏性能、Steam Play 修改、Steamworks 桥接、在线功能、完整 Linux VM 和 Darwin Wine 重编译；执行层通过后另行设计。

## 规格自检

已核对范围、隔离、版本锁定、团队边界、进程清理和成功/阻断定义，无实现占位章节。实际版本身份由执行阶段观察得到，不预先伪造。
