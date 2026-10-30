# P0 B 段：Wine 真实启动器最小接缝与映射规格（待 Lead / cow-worker 审核）

## 1. 只读接缝核实与确证事实
经过对工程现有资源与 Wine 源码的严格只读调查，确证以下事实与边界：
1. **Wine 二进制与动态链接器**：
   - 目标 Wine 二进制：`sources/proton-v3-deploy/original/files/bin-arm64/wine`（SHA256 `0eb603be...`）与 `wineserver`（SHA256 `dc6b16a7...`）；
   - 二者均为动态链接的 Linux ARM64 ELF，明确要求动态链接器 `/lib/ld-linux-aarch64.so.1`；
   - 现有 sysroot 模板 `fixtures/runtime/arch-root` 包含完整的 `lib/ld-linux-aarch64.so.1` 与 Linux 动态运行库。
2. **Guest 与 Host 映射及未证明事项（明确不作假定）**：
   - **Socket 路径计算依据**：Wine 源码确证通过其配置目录的 `stat()` dev 与 ino 拼接计算 `/tmp/.wine-<uid>/server-<dev>-<ino>/socket`；
   - **未证明事项（保持限制声明）**：
     - guest 内部看到的 `stat()` dev/ino 是否与宿主 macOS 看到的数值完全一致，当前在未经真实运行前**保持未证明（UNVERIFIED）**；
     - guest 内部 `/tmp` 是否完全等价于 sysroot/tmp，保持未证明；
     - 宿主 uid 与 guest uid 映射保持未证明；
     - **真实探测规则**：探测套接字时，必须在 guest 内部环境的 `/tmp/.wine-<uid>/server-*/socket` 真实存在且连通；若探测超时（5s）即判 `SERVER_NOT_READY` 阻断，不凭 host 假定。
3. **Guest Shim 真实路径与参数保证**：
   - 真实 Wine 在 guest 中通过 `execve` 调用 `$WINESERVER`；
   - 静态编译的 aarch64 Linux ELF `sources/p0-session-round2/wineserver_shim`（SHA256 `3227f361...`）将被安装到专属 sysroot 的 `/usr/bin/wineserver_shim`；
   - 真正的 wineserver 二进制部署在 sysroot 的 `/usr/bin/wineserver`；
   - shim 严格保持原 argv 不变，仅在未检测到 `-f` 或 `--foreground` 时强行追加单个 `-f`，绝不无限重复追加，随后 `execv("/usr/bin/wineserver", new_argv)`。

---

## 2. 真实启动器架构与两阶段流程

### 进程与会话组治理
- P0 runner（SHA `3580ea64...`）派生唯一 worker 作为进程组长（owned PGID）；
- Launcher 脚本 `scripts/runtime/session_v2_round2/wine_launcher.py` 在该 PGID 下以普通 Popen 运行（不 start_new_session）；
- Launcher 分两阶段调用同一个 elfuse（original runtime `81803322...`）：
  1. **阶段 1：启动前台 Wineserver**
     - 执行：`elfuse --sysroot <root> --timeout 20 --workdir /tmp --clear-env /usr/bin/wineserver -f`
     - 注入环境：`WINEPREFIX=/prefix`, `HOME=/home`, `TMPDIR=/tmp`；
     - 启动后进入 socket 探测循环（上限 5.0 秒）：通过非阻塞 Unix 域 socket 握手探测 `/tmp` 下的专属 server socket；
     - 若 5.0 秒内未成功连通，Launcher 记录 `SERVER_NOT_READY` 并安全退出（退出码 1），**严禁启动阶段 2**。
  2. **阶段 2：启动 Wine PE**
     - 仅在阶段 1 成功就绪后触发；
     - 执行：`elfuse --sysroot <root> --timeout 20 --workdir /work --clear-env /bin/wine /prefix/drive_c/minimal-x64.exe`
     - 注入环境：`WINESERVER=/usr/bin/wineserver_shim`, `WINEESYNC=0`, `WINEFSYNC=0`, `PROTON_NO_ESYNC=1`, `PROTON_NO_FSYNC=1`, `PROTON_NO_NTSYNC=1`；
     - PE 执行完毕退出后，Launcher 协调 Wineserver 正常终止，随后自身退出。
- P0 parent 负责整体会话治理，分层记录退出码与清理结果。

---

## 3. 预算与交付顺序

- **预算设定**：
  - elfuse 单次内部执行预算：**20.0 秒**
  - P0 worker 内部超时：**25.0 秒**
  - P0 supervisor 外层 watchdog：**30.0 秒**
- **当前交付范围**：
  - 编写 `wine_launcher.py` 及其对应的 host fake 单元验证（`test_wine_launcher_fake.py`）；
  - 本阶段**绝对不执行真实 Wine，不申请 guest 锁**；
  - 经独立审查通过后，方可向 Lead 申请仅针对 `original` runtime 的首轮真实 Wine 启动锁。
