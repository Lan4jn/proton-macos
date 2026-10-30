# 完整原版 Proton Python 启动链实测报告 (task-25 终验版)

**实验日期**：2026-10-16  
**执行员**：`proton-package-worker`  
**关联任务**：`task-25`（经 Linux Python 实测完整原版 Proton 启动链）  
**宿主环境**：Apple Silicon macOS 27.0.1 (Build 26A434, arm64, Rosetta 2 可用, 磁盘可用空间 246 GiB)  
**交付物路径**：
- 执行器脚本：`scripts/runtime/proton_launcher/run_proton.py`
- 自动化集成测试：`scripts/runtime/proton_launcher/test_proton_launcher.py`
- 独立 Compat Prefix：`fixtures/runtime/proton-launcher/compat/pfx` (已修复全部 1,577 处断链，已正式冻结)
- 原始日志与运行目录：`logs/proton-launcher/`
  - `plan.json` (自动生成的完整执行计划)
  - `run-0c2jr5lc` (首次 90s 超时记录，完整记录 wineboot、services、svchost 初始化)
  - `run-wrhrm9td` (minimal-x64 via 完整 `run` 动词 -> **退出码 43**)
  - `run-rdtge0e7` (minimal-x64 via `runinprefix` 动词 -> **退出码 43**)
  - `run-bytboyx5` (hello-x64 via `runinprefix` 动词 -> **退出码 0，STDOUT: `X64_FEX_OK`**)
  - `run-8zt29cac` (hello-x64 via `run` 动词 -> 150s 超时，完整捕获 steam.exe GUI desktop 窗口循环)
- Lead 独立复验记录：`logs/lead-round7/run-2bxmxfs0` 与 `logs/lead-round7/proton-runinprefix-hello.json` (**GREEN / 退出码 0 / X64_FEX_OK**)

---

## 1. 核心结论与执行摘要 (Executive Summary)

1. **真实 Linux Python 执行未经修改的 Proton Launcher**：
   - 本次实验在 macOS ARM64 宿主上，通过 `sources/elfuse-crash-derived/build/elfuse-candidate`，直接调用 Arch Linux rootfs 内的纯 Linux Python 3.14 (`fixtures/runtime/arch-case/usr/bin/python3.14`) 执行未经修改的 Valve 官方原版 Proton Python 启动脚本 (`fixtures/runtime/proton-derived/proton`)。
   - **绝无使用 macOS Host Python 替代 Proton 逻辑，绝无使用 Host Wine 或第三方 Wine 替代原版 Wine**。
   - **字节级原样证明**：经 `cmp` 二进制核验，`fixtures/runtime/proton-derived/proton` 与公开原包解压产物 `artifacts/public-proton/extracted/root/.local/share/Steam/steamapps/common/Proton Experimental (ARM64)/proton` 达到 **100% 字节一致（Byte-for-byte identical）**。
2. **动词分层与实测结果（严格区分 `run` 与 `runinprefix`）**：
   - **完整 `run` 动词路径**：
     - 执行完整 Proton 初始化（`setup_game_dir_drive`, `setup_steam_dir_drive`, 生成 `fex_config_file`，通过 `c:\windows\system32\steam.exe` 包装拉起）。
     - **`minimal-x64.exe` 实测通过**：在 120s 窗口内完成，**真实退出码：`43`**（`Target exit code: 43`，耗时 115.97s，日志 `run-wrhrm9td`）。
     - **`hello-x64.exe` 限制记录**：在外层 supervisor 150s 窗口内超时触发终止（日志 `run-8zt29cac`）。stderr 明确捕获到关键建窗错误：`err:win:get_desktop_window failed to create desktop window` 与 `err:class:NtUserRegisterClassExWOW Failed to get shared session object for window class`，并伴随 `explorer.exe /desktop` 多次尝试启动。此现象系 GUI `steam.exe` 包装层唤起桌面服务时在当前无显示环境下的具体表现，严格作为已观测的现场错误证据记录，不将 X11/Wayland 缺失断言为唯一排他根因。
   - **直接 `runinprefix` 动词路径**：
     - 跳过 `steam.exe` 包装层，保留全量 Proton 兼容环境（`WINEPREFIX`、`FEX_APP_CONFIG`、`STEAM_COMPAT_DATA_PATH` 等），直接由 Wine 执行目标。
     - **`hello-x64.exe` 实测通过**：在 60s 窗口内完成，**真实退出码：`0`**（`Target exit code: 0`，耗时 56.98s，日志 `run-bytboyx5`），**标准输出完整捕获：`X64_FEX_OK`**。
     - **`minimal-x64.exe` 实测通过**：在 60s 窗口内完成，**真实退出码：`43`**（`Target exit code: 43`，耗时 53.86s，日志 `run-rdtge0e7`）。
   - **分层结论声明**：`runinprefix` 虽验证了 FEX + Wine 的完整执行层能力，但跳过了部分 `steam.exe` 包装逻辑，本报告明确分层，绝不拿 `runinprefix` 冒充完整 `run` 路径。
3. **Prefix 深度与相对符号链接纠偏**：
   - 从 `fixtures/runtime/fex-crash/pfx` 独立克隆至 `fixtures/runtime/proton-launcher/compat/pfx` 时，由于目录深度由 5 层变为 6 层，原有的 1,577 个指向 `../../../../../proton-derived/files` 的相对链接被全部就地修复为 lab 内绝对路径，确保 `kernel32.dll`、`ntdll.dll`、`libarm64ecfex.dll` 等关键运行时组件解析 100% 正确，无一断链。
   - 将 `dosdevices/c:` 绑定纠偏为指向本地 `../drive_c`。
   - 该 Prefix 已正式冻结，外部复验克隆至任意深度均可正常运行。

---

## 2. 参与运行的关键组件 SHA-256 审计清单

所有参与执行的二进制与脚本哈希均经过严格锁定，与实验前置规范完全吻合：

| 组件名称 | 本地路径 | SHA-256 校验和 | 角色与性质 |
| :--- | :--- | :--- | :--- |
| **elfuse candidate** | `sources/elfuse-crash-derived/build/elfuse-candidate` | `f83455b073611030d388e1f7c4be1dfee26af34106a373b3a6713497790f3e26` | 具备 teardown NULL guard 的候选 elfuse 运行时 |
| **Linux Python** | `fixtures/runtime/arch-case/usr/bin/python3.14` | `c6bc1ef497b896b7575c546b13f9bafe52e2066f184fdd3fec6af4b5b6349947` | Arch Linux aarch64 纯用户态 Python 3.14 解释器 |
| **Proton Launcher** | `fixtures/runtime/proton-derived/proton` | `077db31dda75c570c1a91014f9a814b785307bc91e5dfb1480b984dc34166a54` | Valve 官方原版未修改 Python 启动器主脚本 (与原包 cmp 100% 相同) |
| **Wine Loader** | `fixtures/runtime/proton-derived/files/bin-arm64/wine` | `0eb603be3624255de6d13740b73c4c5bbb9ee5c1f5f9120abdb3ebc408dab91b` | 原版 ARM64 ELF Wine 加载器 |
| **Wine Server** | `fixtures/runtime/proton-derived/files/bin-arm64/wineserver` | `dc6b16a7428df4beca04620839fc13e231a529270bd40b43c3ae3dd2d990995c` | 原版 ARM64 ELF Wineserver 核心守护进程 |
| **ntdll (Unix)** | `files/lib/wine/aarch64-unix/ntdll.so` | `d2d734b53183750f27bd0c7a4093b6665fc94947a38d1bc444411fe6c85fc296` | Wine 底层 NT 原生适配库 |
| **FEX Unix Bridge** | `files/lib/wine/aarch64-unix/libarm64ecfex.so` | `83c88a5dd3065d66cde1c9d653e6dc602eca2fe56227ed2974bf610f70a2b0fd` | 原版 FEX Unix-side 动态链接库 |
| **FEX PE Module** | `files/lib/wine/aarch64-windows/libarm64ecfex.dll` | `ca9b1de29555f27f7c56a161d35b95a1077f233a877765fa7aef610ab6bb8e5e` | FEX ARM64EC Windows PE 模块 |
| **Target: minimal-x64** | `fixtures/runtime/proton-launcher/compat/pfx/drive_c/minimal-x64.exe` | `87406032e5b7c6546afe5fa0f03847a5e398cb4981c969604417a828ab266bc8` | 最小 x64 测试程序（硬编码 exit 43） |
| **Target: hello-x64** | `fixtures/runtime/proton-launcher/compat/pfx/drive_c/hello-x64.exe` | `26cccc8ced8bb2037b2589f7d7af204ad98a27c4f7919bc7fc0dc21e032be9e7` | 标准 x64 控制台测试程序（输出 X64_FEX_OK 并 exit 0） |

---

## 3. 运行环境、参数与动词分层分析

### 3.1 完整执行命令行 (Generated Argv)
```bash
/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-crash-derived/build/elfuse-candidate \
    --user 501:20 \
    --sysroot /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case \
    --timeout 90 \
    /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/python3.14 \
    /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/proton \
    <VERB> \
    C:\<TARGET.EXE>
```

### 3.2 注入环境变量矩阵
- `STEAM_COMPAT_DATA_PATH`: `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-launcher/compat`
- `STEAM_COMPAT_CLIENT_INSTALL_PATH`: `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/steam-stub` (lab 占位符)
- `WINEPREFIX`: `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-launcher/compat/pfx`
- `WINESERVER`: `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wineserver`
- `WINELOADER`: `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wine`
- 同步约束：`WINEESYNC=0`, `WINEFSYNC=0`, `PROTON_NO_ESYNC=1`, `PROTON_NO_FSYNC=1`, `PROTON_NO_NTSYNC=1`, `PROTON_USE_ARM64=1`。

### 3.3 超时看门狗分层说明
- 执行命令行中虽指定了 `--timeout 90`（作为传递给 elfuse 的参数），但底层看门狗未先行中断进程。
- 整个运行的硬超时完全由外层 `scripts.backend.process.run_isolated` 中的 supervisor 独立看门狗严格掌控（120s / 150s），在超时到达时向进程组发送信号并完成垃圾回收，绝不产生失控长跑。

---

## 4. 关键日志片段与真实证据

### 4.1 首次 90s 超时记录 (`run-0c2jr5lc`)：初始化过程实证
完整记录了由纯 Linux Python 引导的原版 Proton 脚本在干净前缀下的全量初始化：
- `Proton: Upgrading prefix from None to 11.0-100`
- `wineboot.exe --init` 成功运行
- `services.exe` 成功启动，注册表生成
- `svchost.exe -k LocalServiceNetworkRestricted` 成功启动
- `winedevice.exe` 驱动总线服务加载
此阶段耗时约 85 秒，证实前缀建制与服务链路真实走通。

### 4.2 `minimal-x64.exe` 完整 `run` 动词退出码 43 记录 (`run-wrhrm9td`)
```
00dc:trace:loaddll:build_module Loaded L"C:\\minimal-x64.exe" at 0000000140000000: native
00dc:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\ntdll.dll" at 000000DFFFE30000: builtin
00dc:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFC1A0000: builtin
00dc:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\kernelbase.dll" at 000000DFFF960000: builtin
00dc:trace:loaddll:build_module Loaded L"C:\\windows\\system32\\kernel32.dll" at 000000DFFFD10000: builtin
...
00dc:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 43, process_exiting 0.
00dc:trace:process:NtTerminateProcess handle 0xffffffffffffffff, self 1, process_exiting 0.
0024:trace:process:NtQueryInformationProcess (0x88,0x00000000,0x11fb90,0x00000030,(nil))
0024:trace:process:NtTerminateProcess handle (nil), exit_code 43, process_exiting 0.
```
*耗时 115.97s，target exit 43，进程组受控退出，无孤儿残留。*

### 4.3 `hello-x64.exe` 直接 `runinprefix` 退出码 0 与 STDOUT 记录 (`run-bytboyx5`)
```
==========================================================
Launching Unmodified Proton Launcher under Linux Python...
  Target: hello-x64.exe
  Verb: runinprefix
  Elfuse: sources/elfuse-crash-derived/build/elfuse-candidate
  Timeout: 60s
==========================================================
Run completed in 56.98s.
  Exit code: 0
  Target exit code: 0
  Timed out: False
  Run directory: /Users/mewcapoo/Projects/proton-macos-lab/logs/proton-launcher/run-bytboyx5
  Stdout length: 10
  Stderr lines: 345
  STDOUT: X64_FEX_OK
```

---

## 5. Team Lead 独立验收实证 (GREEN)

Team Lead 在其独立隔离前缀 `fixtures/runtime/lead-proton/compat` 下复跑 `hello-x64.exe`，取得了完全一致的独立验收结果：
- **执行日志目录**：`logs/lead-round7/run-2bxmxfs0`
- **结果文件**：`logs/lead-round7/proton-runinprefix-hello.json`
- **运行时 SHA-256**：`f83455b073611030d388e1f7c4be1dfee26af34106a373b3a6713497790f3e26`
- **关键输出**：`X64_FEX_OK\n`
- **执行指标**：`exit: 0`, `target_exit: 0`, `timed_out: false`, `seconds: 68.718535`
- **清理结果**：`cleanup_errors: []` (空，无任何孤儿或残留进程)
- **结论**：**Lead 独立验收全绿（GREEN）通过**。

---

## 6. 自动化测试验证

编写了 `scripts/runtime/proton_launcher/test_proton_launcher.py` 对启动链进行端到端回归断言：
```bash
$ python3 -m unittest scripts/runtime/proton_launcher/test_proton_launcher.py -v
test_hello_x64_exit_0_and_stdout (scripts.runtime.proton_launcher.test_proton_launcher.TestProtonLauncher) ... ok
test_minimal_x64_exit_43 (scripts.runtime.proton_launcher.test_proton_launcher.TestProtonLauncher) ... ok
test_plan_generation (scripts.runtime.proton_launcher.test_proton_launcher.TestProtonLauncher) ... ok

----------------------------------------------------------------------
Ran 3 tests in 100.005s

OK
```

---

## 7. 冻结 Prefix 独立复验指南 (供后续复核)

当前前缀 `fixtures/runtime/proton-launcher/compat/pfx` 已正式冻结，所有内部符号链接均已重写为绝对路径，不受拷贝层级影响。

### 7.1 快速独立复验命令（无需耗时 boot，直接复用已冻结 prefix）
```bash
# 1. 运行最小测试 minimal-x64 (预期直接退出 43，耗时约 50s)
python3 scripts/runtime/proton_launcher/run_proton.py --target minimal-x64.exe --verb runinprefix

# 2. 运行 hello-x64 控制台程序 (预期打印 X64_FEX_OK 并直接退出 0，耗时约 55s)
python3 scripts/runtime/proton_launcher/run_proton.py --target hello-x64.exe --verb runinprefix

# 3. 运行完整自动化回归套件
python3 -m unittest scripts/runtime/proton_launcher/test_proton_launcher.py -v
```

### 7.2 独立 Clone 指引（若审查员需隔离副本）
```bash
# 复制已冻结的 prefix 到审查专属目录（因链接为绝对路径，层级深度无影响）
mkdir -p fixtures/runtime/teardown-review/compat
cp -a fixtures/runtime/proton-launcher/compat/pfx fixtures/runtime/teardown-review/compat/pfx
```

---

## 8. 边界与未验证项声明 (Explicit Exclusions)

1. **本层已通过范围**：
   - 纯 Linux Python 3 引导官方未经修改的原版 Proton Launcher；
   - Wine 64 / Wineserver (ARM64) 原生加载；
   - FEX (libarm64ecfex.dll / .so) JIT 翻译执行 Windows x64 指令；
   - 控制台 x64 PE 标准输入输出与进程正常退出（exit 0 / exit 43）。
2. **严格未声称项 (Not Claimed)**：
   - 不声称完整 `run` 动词下的 GUI `steam.exe` 桌面呈现已通过；
   - 不声称 Vulkan / Metal 图形管线渲染已走通；
   - 不声称 Steamworks / DRM 在线授权已通过。
