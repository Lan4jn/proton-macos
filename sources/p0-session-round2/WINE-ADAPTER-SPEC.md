# P0 B 段：Wine Foreground Adapter 修正规格与代码接缝核实（待 Lead / cow-worker 审核）

## 背景与问题改正
根据 Lead 审查指示，针对前版规格中的猜测项与实现接缝进行了逐行源码级核实，纠正以下关键事实：
1. **Socket 实际路径与机制（源码事实纠正）**：
   - **错误前设**：猜测为 `$WINEPREFIX/.wineserver/server-*`。
   - **源码确证**：查阅 Wine 源码 `server/request.c:671-695` 与 `dlls/ntdll/unix/server.c:1315-1325`：
     - Base dir 在非 Android 系统下由 `/tmp/.wine-%u` 构成（其中 `%u` 为 `getuid()`）；
     - Server dir 计算公式为：`/tmp/.wine-<uid>/server-<dev>-<ino>`，其中 `<dev>` 与 `<ino>` 是对配置目录（`config_dir`，即 `$WINEPREFIX` 或 `$HOME/.wine`）进行 `stat()` 所获取的十六进制设备号与 inode 编号；
     - 最终 Unix 域流式套接字文件名固定为 `socket`（`server/request.c:71` 及 `dlls/ntdll/unix/server.c:95`），即路径为：
       `/tmp/.wine-<uid>/server-<dev>-<ino>/socket`。
2. **Socket 归属与真实就绪证明（严防 ps 冒充）**：
   - **/bin/ps 局限性**：`/bin/ps` 只能列举进程 PID/PGID/lstart，不能提供套接字文件描述符（FD）的 owner 或绑定关系，**绝不能声称凭 ps 证明 socket 归属**。
   - **真实就绪判定协议**：
     - 在启动前记录已知 prefix 目录（经 `stat` 获取确切 dev+ino 拼接路径）；
     - 真实就绪必须满足三要素：
       1. 套接字文件 `/tmp/.wine-<uid>/server-<dev>-<ino>/socket` 物理存在且 `S_ISSOCK` 为真；
       2. 通过 Unix 域 socket 执行非阻塞 `connect()` 握手探测（模拟 Wine ntdll 连接逻辑，`dlls/ntdll/unix/server.c:1471`），能成功连接并收到 ACK/握手响应；
       3. 结合宿主端通过已登记 PID 检查该 wineserver 进程处于正常运行状态（而非僵尸），若在 5.0 秒内未完成真实 connect 握手，直接判定 `SERVER_NOT_READY`，立即中止退出并落盘错误，**严禁启动 PE**。
3. **WINESERVER Shim 架构与环境（严防 host/guest 混用）**：
   - **架构事实**：已通过 `file` 命令确证，`sources/proton-v3-deploy/original/files/bin-arm64/wine` 与 `wineserver` 均为 **Linux 64-bit aarch64 ELF**。
   - **调用机制**：Wine `dlls/ntdll/unix/loader.c:669`：
     `if ((path = getenv( "WINESERVER" )) && !build_path_and_exec( pid, "", path, argv )) return 0;`
     确证 Wine 内部启动 server 时完全尊重 `WINESERVER` 环境变量。
   - **Shim 规范**：因为由 guest Wine 在其 Linux ELF 环境下通过 `execve` 调用，**shim 必须是 Linux ARM64 ELF 静态可执行文件**（使用现成的 Zig 编译器交叉编译 `session_probe` 的同一套管线），严禁混入 host macOS Mach-O 或 host Python 脚本。
   - **Shim 功能**：静态 ELF 读取 `argv`，在转发执行真实 `wineserver` 时无条件注入 `-f`（`--foreground`）参数；若未传入 `-f`，自动追加，杜绝守护进程化。

---

## 修正后的完整接入方案

### 1. 单 PGID 治理与 Launcher
- 仍完全复用已冻结 P0 runner (`3580ea64...`)，parent 派生唯一 worker 作为进程组长。
- Launcher 在该 owned PGID 下运行，顺序管理两个 elfuse 调用（均不 start_new_session）：
  1. `elfuse ... wineserver -f`
  2. `elfuse ... wine minimal-x64.exe`
- 两实例 elfuse、wineserver、wine 均处于同一宿主 PGID。

### 2. Prefix 隔离与 4 个 DLL 物化
- 专属隔离目录建立全新 `prefix/`；
- 仅物化 4 个系统核心 DLL 为真实文件副本：`kernel32.dll`、`kernelbase.dll`、`libarm64ecfex.dll`、`ntdll.dll`；
- `dosdevices/c:` 相对重定向至副本 `drive_c`，`dosdevices/z:` 重定向至专属 `work/`，原 1577 个 broken 链接保持不变并出具清单。

### 3. 无 Opt-In 约束与分层预算
- 显式设置环境变量：`WINEESYNC=0`, `WINEFSYNC=0`, `PROTON_NO_ESYNC=1`, `PROTON_NO_FSYNC=1`, `PROTON_NO_NTSYNC=1`。
- 预算：elfuse 20s / P0 内部 25s / 外层 supervisor 30s。

---

## 实施路径

1. **第 1 步：本规格评审**（包含上述源码事实与接缝纠正）。
2. **第 2 步：Host Mock Fixture TDD**：
   - 编写 `scripts/runtime/session_v2_round2/wine_adapter.py`；
   - 编写 `tests/session_v2_round2/test_wine_adapter_mock.py`，使用 host mock 验证：
     - 正确计算 `/tmp/.wine-<uid>/server-<dev>-<ino>/socket` 路径；
     - 显式 socket connect 探测就绪机制（失败时拒绝启动 PE）；
     - prefix 4 DLL 物化与 broken 链接完整性；
     - 注入 `-f` 保证单 PGID 清理。
3. **第 3 步：独立审查后申请真实 Wine 锁**。
