# Stage 3: Wine 成功配置对照、PE 语义 Marker 与最小资源闭包规格

## 1. 历史成功环境与 Round-2 三轮失败对比分析

### 1.1 历史成功环境事实分析
查阅工程中历史通过脚本（如 `scripts/runtime/fex_lifecycle/run_lifecycle_verification.py` 与 `scripts/runtime/proton_launcher/run_proton.py`）：
1. **成功环境特征**：
   - 历史成功环境直接使用完整的 `fixtures/runtime/proton-derived` 作为运行 bundle；
   - 依赖其自带完整的 `share/wine/nls/`（全套 Windows 代码页与区域表，如 `c_20127.nls`, `locale.nls`）以及预置完整的 prefix 环境（包含 `wineboot.exe`、`apisetschema.dll` 及完整注册表结构）；
   - 执行 `minimal-x64.exe` 历史确证退出码为 **43**（`minimal-arm64.exe` 为 **37**）。
2. **Round-2 三轮实测失败物理受阻对比**：
   - **第 1 轮 (`p0-r2-wine-orig`)**：受阻于所有权检查 `st_uid (501) != getuid() (1000)`，wineserver 输出 `/prefix is not owned by you` 崩溃，未生成套接字，PE 未启动；
   - **第 2 轮 (`p0-r2-wine-orig-u`)**：引入原生 `--user 501:20`，所有权冲突彻底排除；推进到服务初始化，受阻于缺失 5.4KB 单文件 `l_intl.nls`，wineserver 受控退出，未生成套接字，PE 未启动；
   - **第 3 轮 (`p0-r2-wine-orig-nls`)**：物理物化单文件 `l_intl.nls`，wineserver 成功就绪（`server_ready: true`），首次真正拉起 Wine 执行 `minimal-x64.exe`；随后在加载器阶段受阻退出（退出码 `29`），捕获到系统调用未实现日志 `syscall 374`、扩展 NLS 缺失（`c_20127.nls`, `locale.nls`）、`wineboot.exe` 缺失（`c0000135`）及 `apiset` 缺失（`c000000f`），未进入 PE 主函数。

---

## 2. 目标 PE 独有语义 Marker 证据与静态确证

### 2.1 源码与机器码绑定证据
1. **源码确证**：
   查阅 `fixtures/runtime/pe-worker/src/minimal.c`（SHA256 `b7d6267c...`）：
   ```c
   __declspec(dllimport) long __stdcall NtTerminateProcess(void *handle, long status);

   void mainCRTStartup(void) {
   #ifdef __aarch64__
       NtTerminateProcess((void *)-1, 37);
   #else
       NtTerminateProcess((void *)-1, 43);
   #endif
   }
   ```
2. **二进制 PE 入口点反汇编确证**：
   静态解析目标文件 `fixtures/runtime/pe-worker/pfx/drive_c/minimal-x64.exe`（SHA256 `87406032...`）：
   - 入口点 RVA 为 `0x1000`（文件偏移 `0x400`）；
   - 入口点 19 字节真实机器码为：`48 c7 c1 ff ff ff ff ba 2b 00 00 00 48 ff 25 25 10 00 00`；
   - **反汇编解析**：
     - `mov rcx, -1`（伪句柄 `GetCurrentProcess()`）；
     - `mov edx, 0x2b`（十进制 **43**！）；
     - `jmp QWORD PTR [rip+0x1025]`（直接跳转导入表 `NtTerminateProcess`）；
3. **Marker 判定标准**：
   - 目标 PE 入口点唯一且必然的行为就是直接在 `mainCRTStartup` 调用 `NtTerminateProcess` 终止进程并返回退出码 **43**（源码中无 `WinMain`，由 CRT 启动点直通）；
   - **判定准则**：在 Wine 执行中，当且仅当进程退出码为 **43**（且无 Wine 加载器异常日志）时，方可严格确证本 PE 按预期执行完成；若退出码非 43（如 29、c000001d 等），一律判定为 **UNKNOWN**（未能确证到达入口）。
   - **历史证据引用（物理收据）**：
     查阅历史真实运行收据 `logs/fex-lifecycle/run-yt1pcwrd/result.json`：
     - `argv`: `[...elfuse-lifecycle-derived, "--user", "501:20", "--sysroot", ".../arch-case", "--timeout", "60", ".../wine", "C:\\minimal-x64.exe"]`
     - `exit`: **43**, `target_exit`: **43**
     - `timed_out`: false
     - `seconds`: **48.828282**
     - **事实分析与冷启动预算差异**：
       历史确证 `minimal-x64.exe` 真实执行确实退出 **43**。但该历史收据同时表明：Wine 在首次对全新 prefix 进行冷初始化引导（包括注册表构建与基础设施初始化）时，实际总耗时高达 **48.8 秒**。当前 Stage 2 采用的 `20s/25s/30s` 预算不足以支撑全新 prefix 的完整冷启动过程。
       因此，Stage 3 规格必须基于该真实收据明确预算建议：若开展全新 prefix 的完整冷启动，需要将两款受测 runtime 统一调整为经审定的新预算（例如 elfuse 60s / P0 内部 65s / 外层 supervisor 75s），严禁在缺乏预算的前提下盲目断言超时为死锁。

---

## 3. 真实资源依赖差异与候选最小子集规格（无盲目扩展）

### 3.1 为何原“4 核心 DLL”约束在真实 Wine 加载器下不足
- 原先仅物化 `kernel32.dll`、`kernelbase.dll`、`libarm64ecfex.dll`、`ntdll.dll` 4 个核心系统库；
- 但 Wine 在启动 64-bit Windows PE 时，加载器（`wine` 与 `ntdll.so`）必须经历 Windows 子系统与环境引导：
  1. 需要基础字符集编码表（`c_20127.nls` US-ASCII 与 `locale.nls`）；
  2. 需要 Windows ApiSet 重定向支持（`apisetschema.dll`）；
  3. Wine 默认在首次初始化新 prefix 时尝试调用 `wineboot.exe` 完成注册表与环境同步；
- 缺少上述最少基础设施导致 Wine 加载器在派生主线程前抛出 `c0000135` / `c000000f` 并异常终止（退出码 29）。

### 3.2 候选最小子集（Candidate Subset）与闭包清单准绳
为使 Wine 加载器平稳走完引导流程，所需扩充的依赖与基础库以 [CLOSURE_MANIFEST.json](<CLOSURE_MANIFEST.json>) 为唯一事实准绳。
**清单明确定性**：
- 闭包清单包含全部 15 项文件，总物理大小为 **22,683,904 字节 (21.63 MiB)**，该数字**包含既有的 4 核心 DLL 及扩充库**，完全受限于 30MB 选定闭包预算；
- 严禁盲目枚举或拷贝 615 MiB 的完整 share 树或 706 MiB 的全量 windows dll 库；
- 强约束：`apisetschema.dll` 与 `wineboot.exe` 不仅要在 bundle 内物化，还必须同步在 `prefix/drive_c/windows/system32/` 目标位置物化为真实实体文件或有效 guest 内部相对链接，严禁在 system32 内保持 broken 状态；
- 精确源路径、SHA256、目标路径与字节预算详见结构化清单 [CLOSURE_MANIFEST.json](<CLOSURE_MANIFEST.json>) 与直接依赖报告 [IMPORTS.json](<IMPORTS.json>)。

---

## 4. 架构布局与可写隔离保证
1. **APFS Copy-on-Write 物理隔离**：
   - 所有的部署（动态库、Proton bundle、闭包文件）统一通过 `ditto --clone` 在专属 `target_root` 内部建立独立副本；
   - 杜绝向外部源目录建立任何符号链接或硬链接；
2. **Manifest 审计规范**：
   - 生成完整 `root_manifest.json`，多维度记录 `literal_target`、`resolution_context`、`actual_resolved` 与 `classification`；
   - 强断言整个 `target_root` 内指向宿主外部仓库的有效符号链接数为 0；
3. **P0 会话组与治理约束**：
   - Launcher 必须在前置阶段完成 samegroup 强校验与 root 合法性检查（处于会话工作目录下专属子目录）；
   - Wineserver、探针、Wine PE 均在同一宿主 PGID 内前台运行，继承统一 `--user 501:20` 原生凭据；
   - 预算设为 elfuse 20s / P0 内部 25s / 外层 supervisor 30s。

---

## 5. 阶段门与停止准则
- **本阶段**：仅提交此规格文件供 Lead 与 cow-worker 独立审查，不执行任何 guest 或 Wine 命令，不修改任何旧版本产物。
- **下一阶段准入**：规格经独立审查通过后，方可在 `scripts/runtime/session_v2_round2/stage3/` 下编写实现与单元测试。
