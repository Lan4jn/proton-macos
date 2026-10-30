# Task-17: Wine 初始化运行期证据采集与单变量诊断规格说明书 (SPEC.md)

## 1. 任务背景与单变量诊断目标
在第二轮 P0 Stage 3 v2 试验中，Wine 在前台 Wineserver 成功建立 Unix socket 并握手就绪后，启动器正式拉起 Wine 执行 `minimal-x64.exe`，但遭遇崩溃受控退出（`wine_exit: 29`）。物理日志输出：
```text
0030:err:module:loader_init Initializing system dll for L"C:\\windows\\system32\\wineboot.exe" failed, status c0000005
0028:err:seh:NtRaiseException Unhandled exception code c000001d flags 0 addr 0xdfffbc6610
```
本任务目标是在**严格保持所有旧文件、旧收据、基础运行时 (`81803322...`)、Wine 二进制与 prefix 模板完全冻结不变**的前提下，仅通过单变量注入受控诊断参数 `WINEDEBUG=+module,+seh,+loaddll`，精确捕获：
1. `c0000005` 发生时具体正在初始化的 DLL 名称、入口点（PC / EntryPoint）与执行阶段（Phase）；
2. 异常捕获线程与上下文堆栈信息；
3. 将未实现的系统调用日志（`syscall 374`）与特定 DLL 初始化崩溃的时序先后解耦。

---

## 2. 源码级机制与开关真实性核实 (只读证据)

### 2.1 Wine ntdll 源码支持确证
1. **WINEDEBUG 变量解析引擎**（`dlls/ntdll/unix/debug.c:190-259`）：
   - 确证 Wine 内部由 `ntdll.so` 在启动时通过 `init_options()` 读取并解析 `WINEDEBUG` 环境变量；
   - 调试频道定义确证（`dlls/ntdll/misc.c` 等）：
     - `module`: 声明于 `dlls/ntdll/loader.c:41`，覆盖 `process_attach`、`MODULE_InitDLL`、`walk_node_dependencies`；
     - `seh`: 声明于 `dlls/ntdll/exception.c:38` 与 `signal_arm64.c:40`，覆盖所有 SEH 异常分发、异常转译与 `NtRaiseException` 拦截；
     - `loaddll`: 声明于 `dlls/ntdll/loader.c:44`，覆盖 PE 与 Unix `.so` 模块映射与基址加载；
2. **`loader_init` 报错路径与线程解耦追踪**（`dlls/ntdll/loader.c:4771-4777`）：
   ```c
   // dlls/ntdll/loader.c:4771-4777
   if ((status = process_attach( node_ntdll, context ))
        || (status = process_attach( node_kernel32, context )))
   {
       ERR( "Initializing system dll for %s failed, status %lx\n",
            debugstr_w(NtCurrentTeb()->Peb->ProcessParameters->ImagePathName.Buffer), status );
       NtTerminateProcess( GetCurrentProcess(), status );
   }
   ```
   - **关键事实确证（Source-Only 观察与递归机制）**：
     日志 `Initializing system dll for L"C:\\windows\\system32\\wineboot.exe" failed, status c0000005` 发生在系统前置初始化（`process_attach(node_ntdll)` 或 `process_attach(node_kernel32)`）阶段；
     研读 `dlls/ntdll/loader.c:1847-1886`：`process_attach` 在调用自身的 `MODULE_InitDLL` 之前，**首先通过 `walk_node_dependencies(node, lpReserved, process_attach)` 递归初始化其所依赖的全部下游 DLL**！
     因此，报错并不代表致错模块只能是 ntdll 或 kernel32 本身，极可能是其直接依赖项（例如 `kernelbase.dll` 或后续系统模块）在执行 attach 或入口点时触发了异常；
     开启 `module` 频道的 `TRACE("(%s,%p) - START\n", ...)` 与 `TRACE("(%p %s,%s,%p) - CALL\n", ...)` 能够精准记录每个递归节点进入与退出的具体模块名称和入口基址，彻底定位崩溃发生的实际 DLL。
   - **严格多线程解耦（禁止假同线程因果）**：
     - 日志前缀表明：`wineboot.exe` 报告错误发生于线程 **`0030`**（`0030:err:module:loader_init...`）；
     - 未处理异常 `c000001d` 发生于线程 **`0028`**（`0028:err:seh:NtRaiseException...`）；
     - 二者处于完全不同的执行线程，绝不能主观假设二者存在单一致命因果关系，必须分别观察。
3. **真实调试频道与日志格式确证**（`dlls/ntdll/unix/debug.c:403-409`）：
   - `dlls/ntdll/unix/debug.c` 源码显式声明支持 `timestamp`（`NtGetTickCount()` 毫秒前缀）与 `pid`（`GetCurrentProcessId()` 前缀）；
   - 线程 ID 格式化代码（Line 409）为默认内置无条件输出：`pos += snprintf(..., "%04x:", GetCurrentThreadId())`；
   - **32MiB 日志上限保护机制**：
     鉴于 verbose 调试日志输出量较大，启动器内部配备了轻量独立的 `StderrCapMonitor` 守护线程，实时监测运行期 `stderr.log` 大小；若超出 **32 MiB** 上限，立即安全终止目标进程，将状态记录为 `UNKNOWN` 并落盘 `STDERR_CAP_EXCEEDED` 证据，杜绝日志无限膨胀；
   - 因此，选定最精简高效的单变量诊断参数为：
     `WINEDEBUG=+timestamp,+pid,+module,+seh,+loaddll`
     能在捕获 `MODULE_InitDLL` 与 `process_attach` 全调用流的同时，附带高精度时序与进程/线程身份，彻底锁定前置系统 DLL 链上的崩溃断点。

---

## 3. 诊断启动器与单变量配置规格

### 3.1 环境变量变更矩阵（严格单一变量）
除注入 `WINEDEBUG` 之外，其余所有环境参数与 Stage 3 v2 保持 100% 完全等价：

| 环境变量 | 基线值 (Stage 3 v2) | 单变量诊断值 (Round 3) | 变动定性 |
|---|---|---|---|
| `WINEDEBUG` | 无 (未设置) | `+timestamp,+pid,+module,+seh,+loaddll` | **唯一注入诊断开关** |
| `WINEPREFIX` | `/prefix` | `/prefix` | 保持不变 |
| `HOME` / `TMPDIR` | `/home` / `/tmp` | `/home` / `/tmp` | 保持不变 |
| `LD_LIBRARY_PATH` | `/lib:/usr/lib:/wine/lib/wine/aarch64-unix` | `/lib:/usr/lib:/wine/lib/wine/aarch64-unix` | 保持不变 |
| `WINEDLLPATH` | `/wine/lib/wine/aarch64-unix` | `/wine/lib/wine/aarch64-unix` | 保持不变 |
| `WINESERVER` | `/bin/wineserver_shim` | `/bin/wineserver_shim` | 保持不变 |
| `WINEESYNC` / `WINEFSYNC` | `0` / `0` | `0` / `0` | 保持无 opt-in |
| `PROTON_NO_*SYNC` | 全部为 `1` | 全部为 `1` | 保持无 opt-in |

### 3.2 治理预算与调度命令
- 预算严格继承 Stage 3 审定额度：
  - elfuse vCPU 内部超时：`--timeout 60`
  - Python 等待：`wine_proc.wait(timeout=60.0)`
  - P0 worker 内部超时：`--timeout 75`
  - P0 supervisor 外层看门狗：`--outer-timeout 85`
- 角色限定：首跑仅放行原运行时 `--role original`（SHA256 `81803322...`），闭包保持 `CLOSURE_MANIFEST_V2.json`（22.76MB，17 项文件）。

---

## 4. 交付文件与隔离路径规划
- 规格说明书：`sources/wine-init-round3/SPEC.md`
- 诊断启动器：`scripts/runtime/wine_init_round3/wine_diagnostics_launcher.py`
- 单元测试套件：`tests/wine_init_round3/test_wine_diagnostics_mock.py`
- 运行日志与收据归档：`logs/wine-init-round3/`
- **安全与锁状态**：本阶段为纯规格与 host mock fixture，严禁私自启动 guest，真实执行待 Lead 明确发锁。
