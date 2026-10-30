# P1 A-copy 真实 Linux Guest C Producer 规格与评估报告 (定稿版)

## 1. 目标与定位

本规格设计一个运行于 Linux guest (ARM64) 环境的静态 C producer (`guest_producer_arm64`)，通过 AF_UNIX `SOCK_STREAM` 向 macOS host 独立 AppKit 服务发送真实 720p RGBA8 payload (每帧 3,686,400 字节)，完成与现有已验证 host (SHA256: `b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb`) 的跨 runtime 通信闭环。

**核心边界**：
- **仅验证 A 路线 IPC/传输架构可行性**，不声称真实 GDI/Wine 驱动已闭环；
- **绝不进入 P2**；
- **Guest 内存地址绝不裸传给 host**，仅传递标准 length-framed 数据流；
- 继承 P0 单进程组与受控 session 治理模式。

---

## 2. 真实可用工具链与 Runtime 事实确证

### 2.1 交叉编译工具链 (Zig 0.16.0 静态交叉编译)
- **工具绝对路径**：`/opt/homebrew/bin/zig` (已在前期冻结，见 [`initial-freeze-zig.json`](<../../logs/round2-v2/review/initial-freeze-zig.json>))；
- **执行文件 SHA256**：`3567b9094e6ba01ed75b9d80c00b83559b61a3f7408699348c882d3c4f9a7998`；
- **交叉编译能力**：原生内置 `aarch64-linux-musl` 与 `aarch64-linux-gnu` target，无需额外安装外部 Linux SDK/sysroot；
- **前期编译事实确证**：P0 专项中 `sources/p0-session-round2/session_probe` (SHA256: `f2446b87c79d66a283d808d3d68f90621ec9cb0601e97198988721d1ab15fa1b`) 正是通过该工具直接编译为纯 Linux aarch64 静态 ELF；
- **构建命令规范**：
  ```bash
  /opt/homebrew/bin/zig cc -target aarch64-linux-musl -O2 -static \
    sources/p1-a-copy-round2/guest_producer.c -o <isolated-root>/bin/guest_producer_arm64
  ```

### 2.2 真实固定 Runtime 资产
依据 `scripts/runtime/session_v2_round2/guest_bootstrap.py` 精确白名单定义：
1. **Original Runtime (优先推荐)**：
   - 路径：`sources/elfuse-once-panorama2-derived/build/elfuse`
   - SHA256：`8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda`
2. **Derived Runtime**：
   - 路径：`sources/elfuse-inproc-present-derived/build/elfuse`
   - SHA256：`3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926`

---

## 3. AF_UNIX 跨层路径映射机制 (源码事实确证)

依据 `sources/elfuse-once-panorama2-derived/src/syscall/net-absock.c` (Lines 595-648) 与 `net.c` (Lines 245-298)：
1. **Sysroot 路径翻译机制**：
   - 当 guest 执行 `connect(fd, sockaddr_un, len)` 时，`elfuse` 拦截 `sys_connect` 并调用 `path_translate_at(LINUX_AT_FDCWD, guest_path, PATH_TR_NONE, &tx)`；
   - 路径解析并非盲目将 host cwd 视为 guest 根，而是**将 guest 相对路径基于 guest 当前所在工作目录 (`--workdir`) 进行 sysroot 解析，转换为 host 实际绝对路径 `tx.host_path`**；
   - 随后通过 `absock_build_sun` 将 host 路径填入宿主 `struct sockaddr_un` 并向 macOS 内核发起真实的 `connect()` 系统调用；
   - 若 host 绝对路径超过 104 字节，`elfuse` 内部会调用 `absock_shorten_path` 创建临时短符号链接中转。
2. **Socket 路径配置规范**：
   - Host 独立服务启动并绑定在 run-dir 的绝对路径：`<run_root>/work/s`；
   - 在启动 `elfuse` 时，通过 `--sysroot <isolated-root>` 指定 guest 隔离文件树，并将 `--workdir` 设为与 host socket 共享的目录（或指定映射挂载点），传入 guest producer 的 socket 参数即为该目录下的相对路径 `./s` 或相对于 sysroot 的路径；
   - 经 `path_translate_at` 解析后，精准指向 host 监听的实际 socket 节点。

---

## 4. 架构调度、命令行规范与单进程组治理

### 4.1 单进程组统一 Launcher 架构
为严格遵循 P0 单一进程组治理，采用轻量 `guest_launcher.py` 作为统一调度器：
1. `guest_launcher.py` 运行于 P0 worker 内部，继承当前同一 PGID；
2. 首先以普通 `subprocess.Popen` (不调用 `start_new_session`) 启动 macOS host 独立服务 (`presenter`，SHA256: `b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb`)，记录其 PID 并等待其就绪；
3. 接着以普通 `subprocess.Popen` 启动 `elfuse` 加载 guest producer；
4. host 与 guest 同处于 P0 父监督器治理的唯一种进程组中，任何超时均由 P0 父监督器向整组发送 `SIGTERM` / `SIGKILL` 集中回收。

### 4.2 启动命令行规范
```bash
python3 -B scripts/p1_a_copy_round2/runner.py \
  --run-id r2-guest-01 \
  --timeout 40 --outer-timeout 50 \
  --module host=logs/p1-a-copy-v2/run-4e2a63efe2f2/presenter \
  --module runtime=sources/elfuse-once-panorama2-derived/build/elfuse \
  -- /usr/bin/python3 -B scripts/p1_a_copy_round2/guest_launcher.py \
     --host-binary logs/p1-a-copy-v2/run-4e2a63efe2f2/presenter \
     --runtime sources/elfuse-once-panorama2-derived/build/elfuse \
     --sysroot sources/p1-a-copy-round2/guest-root-r2-guest-01 \
     --producer-elf bin/guest_producer_arm64 \
     --sock-name s \
     --scenario smoke
```

---

## 5. 协议阶梯验证门与硬停机条件

### 5.1 阶梯式验证门
- **阶段 1：1 帧连通性与正确性 (`smoke`)**
  - 发送 1 帧 720p 真实 payload (3,686,400 字节)，核验 RECEIVED 与 CONSUMED 终态及 CRC32；若失败立即停机；
- **阶段 2：1000 变化帧正确性 (`correctness`)**
  - 逐帧等待终态，严格校验 1000 帧每帧 CRC32 与 seq 递增；
- **阶段 3：30 秒 720p30 吞吐 (`throughput`)**
  - 维持 30fps 节奏推帧 (900 帧)，统计 RTT、帧龄与吞吐率。

### 5.2 实施工作量预估范围与停机条件
- **实施工作量范围**：
  - C 源码编写：约 150 - 250 行标准 POSIX C99 (socket, framing, IEEE CRC32 查表, select 超时)；
  - `zig cc` 构建与单进程组 launcher 联调：约 0.5 - 1 轮人日。
- **硬停机条件 (Hard Stop Criteria)**：
  1. **跨层 Socket 连通受阻**：若 `elfuse` 内 `sys_connect` 返回 `ENOENT` / `ECONNREFUSED` / `EINVAL` 且无法通过路径解析排查解决，**立即停机上报，终止推进**；
  2. **两轮预算上限**：同假设排障严格限制在两轮内，两轮未通 1 帧连通性即下达 NOT_READY 结论。
  3. **严禁进入 P2**：本项仅作为 A 路线呈现传输的可行性边界验证，未获明确批复绝不展开真实 GDI/Wine 驱动开发。
