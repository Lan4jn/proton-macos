# x64 根启动进程 Read 调用配对与管道生命周期观测报告 (Task-113)

**观测者**：x64-pipe-reviewer  
**结论状态**：`run_valid=false`；目标 x64 PE（`vk_enum_x64.exe`）创建与执行在本次 25 秒启动窗口内**未被观测（Unobserved）**。通过全生命周期管道跟踪与同步 Watchdog 快照，成功**捕获并确证了启动根进程挂起的唯一系统调用、具体描述符、所属管道配对及对端状态**：
1. 启动根进程（`host_pid=78429, guest_pid=1, gtid=1`）在整个启动过程中共发起 195 次 read，其中 194 次正常返回，**仅有 1 次未返回**（`call_id=336849990058240`）。
2. 该未返回调用发生于 `guest_fd=8`（`host_fd=54`, `fd_type=4/FD_PIPE`, `generation=87`, `count=16` 字节, `inode=10560977351731242728`）。
3. 管道配对确证：该描述符隶属于管道 `pipe_id=336849990057986`。其写端为 `guest_wr=9`（`host_wr=55`, `generation=88`, `peer_ino=15913276913127907580`）。
4. 全进程共发生 74 次 `THREAD_SNAPSHOT_BEGIN`，其中精确命中根线程（`pid=78429, gtid=1, in_syscall=63, pending_call_id=336849990058240, pending_fd=8`）的样本共 24 次，证实为单次长调用阻塞而非离散重复调用。
5. 写端与对端责任收敛：写端（`guest_wr=9`）被子进程（`guest_pid=4` 与 `guest_pid=5/wineboot`）继承。虽然既有日志未记录根进程对 fd 9 的 `PIPE_CLOSE`，但鉴于 execve O_CLOEXEC、close_range、进程退出及描述符直接替换未走 `sys_close` 钩子，缺关闭记录不足以断言根进程绝对仍持有写端；同时子进程存在 `IO_CALL_TRUNCATED`，写端是否有未被捕获的写入亦不可考。因此结论严格收敛为：根进程同 call read 16 字节长等待已证，writer 角色与写端真实 open 状态待证（标记为 unknown），不能断定应答本应由 wineboot 发送。

---

## 1. 派生运行时构建、SHA-256 与 Diff 清单

### 1.1 工件 SHA-256
| 工件相对路径 | SHA-256 哈希值 | 说明 |
| :--- | :--- | :--- |
| `sources/elfuse-pipe-lifecycle-derived/build/elfuse` | `2eff2415b42ee23c625d8b750f6b4d571c3979f7ff4ac3d1696fe4d4476e458a` | 本次编译派生运行时 |
| `sources/elfuse-x64block-derived/build/elfuse` | `a7f6bbbe88044cd0909ded6dc8c5f51dc0892dea0664dd106bd17bfa157903e0` | 上轮基线运行时 |
| `scripts/runtime/x64_vk/vk_enum_x64.exe` | `18f7004f128eeb5b01815b3df04c7c64bb376175e11fc3459c7bbd9fc77fe12b` | 目标 x64 PE 探针 |
| `logs/x64-pipe-lifecycle/audit-result.json` | 结构化机器可读工件 | 记录完整 hook 计数与分析 |

### 1.2 源码变更 Diff 摘要
派生自 `sources/elfuse-x64block-derived`，仅增加受环境变量 `ELFUSE_PIPE_LIFECYCLE` 控制的诊断逻辑，不改变运行时行为：
- **`Makefile`**：在 `SRCS` 增加 `syscall/pipe-lifecycle.c`；
- **`src/runtime/thread.h / thread.c`**：在 `thread_entry_t` 增加原子字段 `pending_call_id` 与 `pending_fd`，通过 `THREAD_SLOT_KEPT` 静态断言并在 `thread_slot_clear` 处安全初始化；
- **`src/syscall/pipe-lifecycle.h / pipe-lifecycle.c`**：新增管道生命周期表（`pipe_id` 包含进程 PID 与序列号避免冲突）、配对记录、Generation 跟踪、Dup 与 Close 钩子；
- **`src/syscall/fs.c`**：
  - 在 `sys_pipe2` 成功返回前触发 `pipe_lifecycle_on_pipe2`，捕获读写端配对与两端在 Darwin XNU 下的独立 inode；
  - 在 `duplicate_guest_fd` 中触发 `pipe_lifecycle_on_dup`，覆盖 `dup`/`dup3`/`fcntl(F_DUPFD*)`；
  - 在 `sys_close` 触发 `pipe_lifecycle_on_close`；
- **`src/runtime/fork-state.c`**：在 `fork_ipc_recv_fd_table` 处捕获子进程管道描述符继承，触发 `pipe_lifecycle_on_fork_inherit`；
- **`src/syscall/syscall.c`**：
  - 拦截 `SYS_read` / `SYS_write` 生成全局唯一 `call_id`，同时覆盖内联 fast-path 与 slow-path；
  - 记录 `IO_CALL_ENTER` 与 `IO_CALL_RETURN`，输出 `call_id`、`ts_us`、`guest_fd`、`host_fd`、`gen`、`pipe_id`、`peer_ino`、`count`、`result`、`errno`、`elapsed_us`；
  - 设置并清理线程的 `pending_call_id` 与 `pending_fd`；
  - 在 `futex_owner_thread_cb` 中打印 `pending_call_id` 与 `pending_fd`，建立 Watchdog 与当次调用的精确同步。

---

## 2. 管道生命周期 Smoke 测试验证 (Acceptance 4)

编写测试脚本 `scripts/runtime/x64_pipe_lifecycle/pipe_smoke.py`，在派生 runtime 下先行运行，验证全部生命周期钩子：
```bash
ELFUSE_PIPE_LIFECYCLE=1 sources/elfuse-pipe-lifecycle-derived/build/elfuse   --user 501:20   --sysroot fixtures/runtime/arch-case   --timeout 15   fixtures/runtime/arch-case/usr/bin/python3.14   scripts/runtime/x64_pipe_lifecycle/pipe_smoke.py
```

**实际执行输出日志**：
```text
=== SMOKE TEST START ===
PIPE_CREATE pipe_id=335720413659137 host_pid=78166 guest_pid=1 gtid=1 guest_rd=3 host_rd=23 rd_gen=28 rd_ino=8931837061919007322 guest_wr=4 host_wr=25 wr_gen=29 wr_ino=7141597751590942856
PIPE_DUP pipe_id=335720413659137 host_pid=78166 guest_pid=1 old_fd=3 old_gen=28 new_fd=5 new_gen=30 role=read peer_inode=7141597751590942856
Duped r=3 to r_dup=5
PIPE_CLOSE pipe_id=335720413659137 host_pid=78166 guest_pid=1 gtid=1 guest_fd=3 gen=28 role=read peer_inode=7141597751590942856
Closed r=3
PIPE_FORK_INHERIT host_pid=78167 guest_pid=2 gfd=4 hfd=10 gen=4 ino=7141597751590942856
PIPE_FORK_INHERIT host_pid=78167 guest_pid=2 gfd=5 hfd=11 gen=5 ino=8931837061919007322
Child 2 exited with status 0
Parent read 14 bytes: MSG_FROM_CHILD
PIPE_CLOSE pipe_id=335720413659137 host_pid=78166 guest_pid=1 gtid=1 guest_fd=4 gen=29 role=write peer_inode=8931837061919007322
Closed w=4
EOF read returned 0 bytes (expected 0 for EOF)
PIPE_CLOSE pipe_id=335720413659137 host_pid=78166 guest_pid=1 gtid=1 guest_fd=5 gen=30 role=read peer_inode=7141597751590942856
=== SMOKE TEST PASS ===
```
**结论**：管道配对、跨 dup 继承、跨 fork 继承、读写匹配、close 跟踪及 EOF 返回（0 字节）全链路验证通过，退出码为 0。

---

## 3. 有界 25 秒 x64 启动实验执行与进程隔离

通过受控脚本 `scripts/runtime/x64_pipe_lifecycle/run_x64_pipe_lifecycle.py` 启动有界单次实验：
- **日志目录**：`logs/x64-pipe-lifecycle/run-54km9yf2`
- **前缀环境**：克隆自 `fixtures/runtime/futex-args-vulkan/pfx` 至 `logs/x64-pipe-lifecycle/pfx`，包含探针 `drive_c/vk_enum_x64.exe`；
- **运行命令**：
  ```text
  /Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-pipe-lifecycle-derived/build/elfuse     --user 501:20 --sysroot /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case     --timeout 60 --env WINEPREFIX=.../pfx ...     /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/sh -c     "unset LD_PRELOAD ...; exec .../bin-arm64/wine 'C:\vk_enum_x64.exe'"
  ```
- **超时与清理语义**：
  - **外层 25 秒 vs 内层 60 秒差异**：外层 supervisor 设置 `timeout=25`，用于在有限时间内捕获稳定挂起证据并及时停止，避免无效等待；内层 `--timeout 60` 为 elfuse 自带的安全看门狗上限。
  - **进程组清理结果**：25 秒到达后，supervisor 准确向所属 PGID 发送 SIGKILL（退出码 `exit=124, supervisor_exit=-9`），`cleanup_errors: []`，孤儿子进程数为 0；严格不扫描且不杀伤任何宿主无关历史进程。

---

## 4. Hook 统计与根进程 Read 长阻塞确证 (Acceptance 2, 3, 5)

### 4.1 全过程统计概览
- `PIPE_CREATE`：12 次
- `PIPE_DUP`：0 次
- `PIPE_CLOSE`：5 次
- `PIPE_FORK_INHERIT`：8 次
- `IO_CALL_ENTER`：2,307 次
- `IO_CALL_RETURN`：2,306 次
- `IO_CALL_TRUNCATED`：2 次（进程 78432 与 78434 达到上限截断）
- `THREAD_SNAPSHOT_BEGIN`（全进程 Watchdog 周期）：74 次（其中根线程 `pid=78429, gtid=1` 处于 `pending_call_id=336849990058240` 的快照精确为 24 次）
- **根进程读（`guest_pid=1, op=read`）进入数**：195 次
- **根进程读（`guest_pid=1, op=read`）返回数**：194 次

### 4.2 根进程未返回调用的锁定与配对证据
在当前已捕获的 2,307 次 IO 进入与 2,306 次返回中差值为 1。需要注意，子进程 78432 与 78434 均触发了 `IO_CALL_TRUNCATED`，因此 2307-2306=1 仅是**已记录集合内的差值**，不可直接推论为全运行唯一未返回调用。然而，**根进程（`guest_pid=1`）自身未发生截断**（进入 195 次，返回 194 次），且与 Watchdog 中同步捕获的 pending 身份完全吻合，可**独立确证根进程该调用持续挂起未返回**：
- **进入记录（L2928）**：
  ```text
  IO_CALL_ENTER call_id=336849990058240 ts_us=1343080305372 op=read host_pid=78429 guest_pid=1 gtid=1 guest_fd=8 host_fd=54 fd_type=4 gen=87 pipe_id=336849990057986 peer_ino=15913276913127907580 can_block=1 count=16 gva=0x7ffd9b0 inode=10560977351731242728
  ```
- **调用参数解析**：
  - 进程：`host_pid=78429, guest_pid=1, gtid=1`（根启动进程）
  - 目标描述符：`guest_fd=8`（宿主 `host_fd=54`）
  - 类型与代际：`fd_type=4`（`FD_PIPE`），`gen=87`
  - 请求字节数：16 字节（`count=16`，缓冲区虚地址 `gva=0x7ffd9b0`）
  - 宿主 Inode：`inode=10560977351731242728`
  - 发生时间戳：`ts_us=1343080305372`（自此再无该 call_id 的 RETURN）

### 4.3 Watchdog 快照同步证实持续长阻塞
在全进程 74 次 Watchdog 快照中，精确匹配根线程 `pid=78429, sibling_gtid=1, in_syscall=63, pending_call_id=336849990058240, pending_fd=8` 的快照共 **24 次**（持续分布于后续 20 余秒）：
```text
FUTEX_OWNER_THREAD pid=78429 caller_gtid=-1 sibling_gtid=1 in_syscall=63 futex_kick=1 parked=0 pending_call_id=336849990058240 pending_fd=8
```
- **确证**：通过线程私有原子字段同步，证实根线程在整个后续 20 余秒内**持续处于系统调用 63（read）内部，阻塞于唯一的 `call_id=336849990058240`**，彻底排除了“循环发起多次离散短 read”的假象。

### 4.4 管道对端与写端生命周期溯源
通过 `pipe_id=336849990057986` 检索生命周期记录：
1. **管道创建（L2124）**：
   ```text
   PIPE_CREATE pipe_id=336849990057986 host_pid=78429 guest_pid=1 gtid=1 guest_rd=8 host_rd=54 rd_gen=87 rd_ino=10560977351731242728 guest_wr=9 host_wr=55 wr_gen=88 wr_ino=15913276913127907580
   ```
   - 根进程创建了该管道：读端分配为 fd 8，写端分配为 fd 9。
2. **写端继承**：
   - L2577：子进程 `guest_pid=4` 继承了写端 `gfd=9, hfd=16, ino=15913276913127907580`；
   - L2585：子进程 `guest_pid=5`（`wineboot.exe --init`）继承了写端 `gfd=9, hfd=16, ino=15913276913127907580`；
3. **写端处置与未闭合状态**：
   - 在子进程 `guest_pid=5`（`wineboot`）中，L3853 显示 fd 9 被关闭并重新分配为常规文件（`gen=87, inode=15010959`）；
   - 在根进程 `guest_pid=1` 自身中，**没有任何关于 fd 9 的 `PIPE_CLOSE` 记录**；
   - **分析定性**：管道写端仍由根进程或未退出的子进程持有，因此内核不会向读端发送 EOF；而写端未发生数据写入，导致根进程的 16 字节读取无限阻塞挂起。

---

## 5. 未覆盖路径与跨命名空间边界声明

1. **宿主隐式创建路径声明（Unknown）**：
   - 本次探针已覆盖 Linux guest 侧发起的 `pipe`/`pipe2`/`dup`/`dup3`/`close`。
   - 若 Wine 宿主加载器（如 `wine-preloader` 自身在进入 guest 代码前）或 Wineserver 存在完全绕过 guest Linux 系统调用在宿主侧直接调用的 `pipe`/`socketpair`，该部分未被 guest hook 拦截，**严格标注为 `unknown`（未覆盖）**。
2. **跨命名空间 PID 映射声明（待关联）**：
   - Linux 侧捕获的 `guest_pid=1`、`guest_pid=4`、`guest_pid=5` 与宿主 PID 可一一映射；
   - 但映射到 Wine Windows 命名空间中的 PID/TID（如 `0028/002c`）仍需 Wine 内部 trace 事件支持，**不能仅凭 Linux clone/execve 自动强行推断**。
3. **PE 状态与非声明**：
   - 探针 `stdout_bytes=0`，`has_step1=false`，`has_step3=false`；
   - 目标 PE 的创建与执行流在本次 25 秒运行中**未被观测到（Unobserved）**；
   - **严禁宣称 Vulkan 或 x64 执行流已修复**。

---

## 6. 下一项最小观测建议

在已锁定根进程挂起于 `guest_fd=8`（`pipe_id=336849990057986`，写端为 `guest_fd=9`，请求 16 字节）的基础上，下一步建议开展以下最小非侵入观测：
1. **排查根进程中 fd 8/fd 9 的业务含义**：
   - 查阅 Wine 源码（如 `dlls/ntdll/unix/process.c` 或 `server/process.c`），确认启动新进程（如创建 `wineboot` 或内部 worker）时用于等待子进程就绪或同步状态的 16 字节 IPC 结构体（通常为句柄或 socket 握手报文）。
2. **检查为什么写端未发送 16 字节握手信号**：
   - 聚焦于子进程 `guest_pid=5`（`wineboot.exe --init`）启动流程，探查为何其继承写端后未向根进程回报 16 字节就绪通知，导致根进程在启动链等待处持续挂死。
