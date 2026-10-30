# Windows Vulkan 加载器有限静态审计（task55 / round8）

- 团队执行在两位成员间多次失败、无工件；Lead只对本任务作只读兜底，不延伸为后续任务的默认执行模式。本轮未启动Wine/HVF/Xvfb。
- 原始证据：`logs/windows-vulkan-loader-audit/`，工具为已有LLVM22 `llvm-readobj`/`llvm-objdump`；REA已检索到open_binary，但本任务头/导入/已知入口由现成CLI即可覆盖，未启动全量反编译。
- 54前缀的六DLL（vulkan-1、winevulkan、user32、win32u、ntdll、libarm64ecfex）均与Proton派生目录对应原文件SHA一致，详见`identity.json`；不是用替代DLL修复所得。
- vulkan-1 SHA `8c1748972d70333974f063312e1e9f0a084929b38f5141f9a9d397bcc0367222`，COFF-ARM64X（0xA64E），有ARM64EC混合视图；不是单纯x64或单纯ARM64 DLL。
- user32/win32u/ntdll为ARM64X；libarm64ecfex为ARM64EC。每个精确Machine/入口见各自headers-imports记录，不由目录名推断运行架构。
- vulkan-1 ARM64入口RVA0x10360跳转至DllMain0x102e0；PROCESS_ATTACH分支依次调用IAT0x30010的DisableThreadLibraryCalls、IAT0x30000的GetDpiForSystem，再返回TRUE；TLS目录RVA/size均0。
- 混合视图入口RVA0x20000位于.hexpthk，呈x64跳板至__arm64x_native_entrypoint；该静态事实不证明54运行时究竟停在哪个入口或调用。
- `vkCreateInstance`导出为`winevulkan.vkCreateInstance`转发（两个视图皆如此）。54只输出LoadLibrary Step1，末条loaddll不是DllMain返回证据；GetDpi/session初始化是新的具体观测候选，不是已定位死锁根因。
- 52→54差异已有`fixtures/runtime/windows-vk-phase/env_delta.json`：目标/前缀、DISPLAY/XAUTHORITY、ICD、vulkan诊断不同；完整LD路径与no-clear-env相同。没有逐行时间戳，不估算90s各阶段耗时。
- 原生ARM64 PE对照在工具层可行：现有clang支持Windows目标，llvm-dlltool列出arm64/arm64ec，已有lld-link；原测试源无x64汇编且手写64位ABI。尚未编译或执行，现有ntdll-only ARM64 exit37不替代kernel32/user32/Vulkan验证。
- 下一步最小交付是独立ARM64 kernel32控制台/LoadLibrary阶段探针：先hello与GetDpi阶段，再Vulkan；保持原DLL、原x64样本及旧失败不动，避免再以相同x64整图形负载反复超时。
