# 第二轮 P0 阶段交付报告 (REPORT.md)

## 1. 阶段结论与状态判定
- **整体状态**：**A 段已测 PASS；B 段前台 Server 就绪已测，Wine 启动尝试受阻 (Exit 29)，同 PE 原/派生对照 NOT_RUN，整体处于 NOT_READY 阶段收口**。
- **任务状态**：task-9 保持 `in_progress`，本报告作为第二轮客观实测事实与收据的阶段交付，不以中间受阻冒充完成。
- **核心定性校准（严禁夸大）**：
  1. **A 段**：仅断言在 PRE 与 POST 两个屏障采样瞬间，已关联的 4 个宿主进程处于 P0 owned PGID 内，不外推为整个生命周期全局零逃逸；`cleanup.complete: true` 仅指对已登记 owned 进程组的终态 ps 采样清理完成；
  2. **B 段**：实测确证前台 Wineserver 成功建立套接字监听并由独立客体探针握手连通；但在阶段 2 中，**仅证明 Wine 启动器进程以 `minimal-x64.exe` 为参数被执行并以退出码 29 退出，绝不证明目标 PE 的入口点或 WinMain 主函数真正被执行**（日志反映失败发生在 Wine 加载器与 Windows 子系统初始化阶段）；
  3. **对照状态**：派生运行时（Derived Runtime）对照因触发停止条件**严格保持 NOT_RUN**。

---

## 2. A 段实测事实确证（6 场景全量 PASS）
在独立会话组与 P0 runner（SHA256 `3580ea64...`）治理下，原运行时 (`81803322...`) 与派生运行时 (`3b146bbe...`) 的 6 个真实 Linux guest 场景全部通过独立复核：
1. **Linux Guest 内部真实行为**：静态 ARM64 Linux 探针（[sources/p0-session-round2/session_probe](<session_probe>)，SHA256 `f2446b87...`）在 elfuse guest 内部成功 `fork()` 并 `setsid()` 切换到新会话（`sid=2, pgid=2`），返回值返回新 SID `2`；
2. **宿主进程组约束**：PRE 与 POST 阶段实时 `/bin/ps` 快照均严格观测到完整的 4 节点父子进程链（`worker -> observer -> elfuse -> guest_helper`），两快照中的 4 个关联进程同组；
3. **受控故障注入事实**：
   - **Inner Timeout 场景**（[p0-r2-orig-timeout](<../../logs/session-v2-round2/p0-r2-orig-timeout/receipt.json>), [p0-r2-derived-timeout](<../../logs/session-v2-round2/p0-r2-derived-timeout/receipt.json>)）：探针在约 0.68s 到达 PRE，扣留 ACK 后 P0 worker 精确在 2.0s 内部超时退出（`runner_exit: 124`, `target_exit: null`），无探针 5s 自退冒充；
   - **Worker Crash 场景**（[p0-r2-orig-crash](<../../logs/session-v2-round2/p0-r2-orig-crash/receipt.json>), [p0-r2-derived-crash](<../../logs/session-v2-round2/p0-r2-derived-crash/receipt.json>)）：控制器单次向核验过的 worker 发送 `SIGKILL`，P0 parent 捕获异常（`runner_exit: 70`）并完成进程组清理；预存的四节点链 PID+identity 在终态全量 ps 中复核无一残留；
   - **Sentinel 保护**：独立会话组的 `sentinel` 进程在 4 轮受控 fault 测试中实测全程存活并安全显式回收。

---

## 3. B 段真实 Wine 启动尝试实测事实与收据
在 `wine_launcher.py` 严格治理下，真实运行收据与物理阻断如下：
1. **真实物理副本隔离与 Manifest**：
   - 部署路径：`logs/session-v2-round2/wine-setup-audit-root`（总占用仅 87MB，APFS clonefile 快速隔离，拒绝外部软链穿透，跨 root 有效外链为 0）；
   - 审计清单：`root_manifest.json` 结构化审计 1580 条符号链接，记录 4 个核心系统 DLL（`kernel32`, `kernelbase`, `libarm64ecfex`, `ntdll`）直接从本地 `wine/lib/wine/aarch64-windows` 取实体；
   - `dosdevices/z:` 严格绑定 guest 内部视角 `/work`。
2. **三轮独立假设实测推进事实**：
   - **首跑 (`p0-r2-wine-orig`)**：wineserver 在 5.0s 内未产生 socket，阻断 PE 启动。深层原因定位为 Wine `server/request.c` 检查所有权，宿主文件透传 UID (501) 与 guest 默认 UID (1000) 不符，输出 `wineserver: /prefix is not owned by you`；
   - **第二轮重试 (`p0-r2-wine-orig-u`)**：针对所有权假设，引入 elfuse 原生配置 `--user 501:20`。实测确证所有权冲突彻底排除（该错误日志消失），推进到服务同步初始化阶段，随后捕获到新阻断：缺失 `l_intl.nls` 导致受控受阻退出；
   - **第三轮重试 (`p0-r2-wine-orig-nls`)**：
     - **阶段 1 突破**：单文件物理物化 `wine/share/wine/nls/l_intl.nls`（5.4KB，SHA256 `ad190cb8...`）。实测确证 wineserver 成功创建套接字，静态 aarch64 探针动态连接成功，判定 `server_ready: true`！
     - **阶段 2 真实启动与深层退出**：解除阻断后，启动器真正派生并以 `minimal-x64.exe` 为参数拉起 Wine 二进制；随后 Wine 加载器在 Windows 运行环境初始化阶段遭遇异常退出，返回码为 `29`（`wine_exit: 29`，`wineserver_exit: -15`，P0 清理完成）。
3. **深层失败日志事实 (stderr.log 物理证据)**：
   ```
   15:40:17 WARN  src/syscall/syscall.c:3505: unimplemented syscall 374 (x0=0x80801, ...)
   err:environ:read_nls_file failed to load /wine/lib/wine/../../share/wine/nls/c_20127.nls
   err:environ:read_nls_file failed to load /wine/lib/wine/../../share/wine/nls/locale.nls
   wine: failed to start L"C:\\windows\\system32\\wineboot.exe": c0000135
   0028:err:module:load_apiset_dll failed to load apiset: c000000f
   0028:err:seh:NtRaiseException Unhandled exception code c000001d flags 0 addr 0xdfffbc6610
   ```
4. **触发停止条件**：
   单次重试若发现新依赖缺失即坚决止步，不无限链式追加资源，不运行 derived 对照，保留确凿物理受阻点。

---

## 4. 下一门规划 (NEXT-GATE)
1. **底层系统调用支持**：
   elfuse 运行时报告未实现系统调用 `syscall 374`（仅作为运行时日志行号记录，不作具体系统调用名称推断，不假设致命因果）。下一门需专项评估该系统调用在 elfuse 中的出现背景与处理边界，当前仅列为观测事实。
2. **Wine 加载器基础设施资源完善**：
   - NLS 扩展编码表：`c_20127.nls` 与 `locale.nls`；
   - 基础用户态组件：`wineboot.exe`（状态码 `c0000135` 提示 DLL/可执行文件缺失）与 `apiset` 模块（状态码 `c000000f` 找不到指定文件）；
3. **同 PE 原 / 派生两 Runtime 对照**：
   在加载器环境与系统调用支持确立后，再严格按同配置（`--user`、prefix、无 opt-in）放行 `original` 与 `derived` 的首轮同 PE 完整执行比对。

---

## 5. 5 项具体受测源文件防篡改核验 (100% MATCH)
运行前后及终态，5 项受测源文件 SHA256 完好无损：
- `sources/proton-v3-deploy/original/files/bin-arm64/wine`: `0eb603be3624255de6d13740b73c4c5bbb9ee5c1f5f9120abdb3ebc408dab91b`
- `sources/proton-v3-deploy/original/files/bin-arm64/wineserver`: `dc6b16a7428df4beca04620839fc13e231a529270bd40b43c3ae3dd2d990995c`
- `fixtures/runtime/pe-worker/pfx/drive_c/minimal-x64.exe`: `87406032e5b7c6546afe5fa0f03847a5e398cb4981c969604417a828ab266bc8`
- `sources/elfuse-once-panorama2-derived/build/elfuse`: `8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda`
- `sources/elfuse-inproc-present-derived/build/elfuse`: `3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926`
