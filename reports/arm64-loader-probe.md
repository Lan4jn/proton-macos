# 原生 Windows ARM64 加载阶段探针（task56）

- 成员final-lab-reviewer与接替steam-probe-worker均会话失败无工件；Lead仅对本任务兜底执行构建、自检与有界实测；未取得新的独立成员复核，不能写成双端验收。
- 源码`fixtures/runtime/arm64-loader-probe/probe.c` SHA `540791272421f029794a4151e024f1b26679915f4a2daf577c4e7d05066439db`；运行器`runner.py` SHA `35a2a41b0c27815d94d95e6055b6fb1d9f2902474ba52ea27cbcf86d59acea01`。
- 现有clang/dlltool/lld构建三个无CRT、仅kernel32导入的PE，Machine均为原生ARM64 0xAA64，非ARM64EC/x64；原软件/原DLL未修改。
- `python3 -m unittest scripts.runtime.arm64_loader_probe.test_runner -v`：7测试通过；marker/退出码/timeout/cleanup分开断言，7是测试方法数，部分含子测试。
- hello：`run-35dr_7to`，`ARM64_KERNEL32_OK`，overall/target37，39.540460s，无timeout/cleanup错误。
- user32/DPI：`run-xilv14r3`，LoadLibrary(user32)返回，GetDpiForSystem返回96，overall/target38，40.150981s，无timeout/cleanup错误。
- Vulkan DLL加载：`run-b33o52pt`，`ARM64_VULKAN_LOAD_RETURNED`，overall/target39，39.893819s，无timeout/cleanup错误。
- 三阶段顺序执行、严格前阶段通过才推进；累计三次，无重试。run_isolated的整体耗时含supervisor收尾，不当作API调用耗时。
- 受控no-clear-env profile、06a2fceb...runtime、native ELFUSE_ABSOCK_BASE=lab/.s、无preload/无DISPLAY/Xauthority/无Xvfb；日志未见libarm64ecfex加载，不据此泛化所有内部指令路径。
- 预设37/38/39是各探针成功退出值，不是图形游戏成功码；此轮仅通过ARM64 kernel32/DPI/DLL加载，未调用vkCreateInstance或枚举设备。
- 原始退出与六DLL摘要见`logs/arm64-loader-probe/stage_results.json`；构建件SHA依次为`ee44503b...`、`5315a739...`、`6aaae716...`，完整摘要可从独立原件重新计算。
- 下一步原生ARM64 Vulkan枚举与x64同源加载阶段对照分别验收；现有原Proton x64图形阻断仍保留，不能由原生加载成功归因全部FEX或宣称已解。
