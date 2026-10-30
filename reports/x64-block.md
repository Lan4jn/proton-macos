# x64 Vulkan 探针启动期 Read 采样复审与审计报告 (Task-109)

**审计者**：x64-pipe-reviewer  
**结论状态**：`run_valid=false`；目标 x64 PE（`vk_enum_x64.exe`）的创建与执行在此次采样范围内**未被观测（Unobserved）**。现有存盘日志仅证实 Wine 启动期组件（`wineboot.exe --init`）与启动根进程存在 read 采样；无 Step 1/3 或 NtCreateUserProcess marker 仅证明目标 PE 执行未被捕获，不能简单断言“PE 未启动”，亦不能排除 vDSO 异常（Wine 启动器自身亦可调用 vDSO）或 elfuse 机制问题。  
**审计产物**：
- 机器可读审计摘要：`logs/x64-block/recovery/recovery-audit-summary.json`
- 原采样证据记录：`logs/x64-block/sampling-evidence-verified.json`
- 主分析日志：`logs/x64-block/sampled-peer-trace/run-aizg68sd/stderr.log`
- 基线对比日志：`logs/lead-round7/run-2bxmxfs0/stderr.log`

---

## 1. 原始文件 SHA-256 清单 (Raw SHA-256 Digest)

| 文件相对路径 | 大小 (Bytes) | SHA-256 哈希值 |
| :--- | :--- | :--- |
| `logs/x64-block/sampling-evidence-verified.json` | 4984 | `92b56663b06d3cf4ff5bd36a235e411b5b982467d33121bac76ea53cfa34838c` |
| `logs/x64-block/sampling-evidence.json` | 9058 | `493fbbc7ce7512c31fc2c8001e3919f810b64ad4cced7612ee2a75a3d96de857` |
| `logs/x64-block/sampled-peer-trace/receipt.json` | 96142 | `5046914009fd84ae2252fb43969245275c9fea6c5ebfd60d125f93186f172c38` |
| `logs/x64-block/sampled-peer-trace/run-aizg68sd/stderr.log` | 616033 | `5979549c6abf0de21a8c88c27b23d5a15354c4240d53169afb6acbcbbbcf58a0` |
| `logs/x64-block/sampled-peer-trace/run-aizg68sd/result.json` | 2217 | `cc2e982bf3b463cfbe6c8dd39cf331c701251872b1b873a7471698899da023f1` |
| `logs/x64-block/sampled-read-identity/receipt.json` | 42157 | `912b2a37796be8ee6b40bb6cef4066400cc0cb089e3507fe94ad404e36652d6d` |
| `logs/lead-round7/run-2bxmxfs0/result.json` | 907 | `b9daf21bd0161af78c5222a91d76d1e6eb0d5e6fad35baa493a2c5817280b127` |
| `logs/lead-round7/run-2bxmxfs0/stderr.log` | 37397 | `a4b78976da3cebbafe550bcb391b9f59fc92ba42492fc1778d231f4c3fe09af2` |

---

## 2. 描述符类型、Inode 来源与 Darwin XNU 管道实测核对

### 2.1 API 来源与源码核对
1. **`fd_type=4`**：
   - 源码定义：`sources/elfuse-x64block-derived/src/syscall/linux-wire.h:520`：`#define FD_PIPE 4`。
   - 分配位置：`sources/elfuse-x64block-derived/src/syscall/fs.c:2889/2898`。Guest 发起 Linux `pipe()` 或 `pipe2()` 系统调用时，elfuse 调用宿主 `pipe()` 并分配内部描述符，类型标记为 `FD_PIPE`。
2. **`inode=7364773697224751085` 与 `mode=0x11b0`**：
   - 来源：macOS/Darwin 宿主调用 `fstat(host_fd, &st)` 获取的 `st.st_ino` 与 `st.st_mode`。
   - `mode=0x11b0` 为八进制 `010660`，即 POSIX `S_IFIFO | S_IRUSR | S_IWUSR | S_IRGRP | S_IWGRP`。
   - `path=[no-path]`：macOS `fcntl(host_fd, F_GETPATH)` 对管道失败返回默认占位，符合管道特征。

### 2.2 本机实测：Darwin XNU 管道读写端 Inode 异构性
在 Darwin/macOS XNU 内核（`bsd/kern/sys_pipe.c:pipe_stat`）中，管道的 inode 实际为内核管道结构体指针地址：`sb->st_ino = (ino_t)(uintptr_t)cpipe;`。  
为验证读写端 inode 关系，在宿主运行以下实测探针：
```c
// /tmp/darwin_pipe_test.c
#include <stdio.h>
#include <unistd.h>
#include <sys/stat.h>

int main() {
    int fds[2];
    if (pipe(fds) < 0) return 1;
    struct stat st0 = {0}, st1 = {0};
    fstat(fds[0], &st0);
    fstat(fds[1], &st1);
    printf("read end:  host_fd=%d st_ino=%llu st_mode=0x%x st_dev=%d\n", fds[0], (unsigned long long)st0.st_ino, (unsigned)st0.st_mode, (int)st0.st_dev);
    printf("write end: host_fd=%d st_ino=%llu st_mode=0x%x st_dev=%d\n", fds[1], (unsigned long long)st1.st_ino, (unsigned)st1.st_mode, (int)st1.st_dev);
    close(fds[0]);
    close(fds[1]);
    return 0;
}
```
**本机编译与实测输出**：
```text
read end:  host_fd=3 st_ino=11997090016386472134 st_mode=0x11b0 st_dev=0
write end: host_fd=4 st_ino=9231872438133737634 st_mode=0x11b0 st_dev=0
```
**实测确证**：
- 读端（`fds[0]`）与写端（`fds[1]`）由内核分配不同的 `struct pipe`（`cpipe` vs `cpipe->pipe_peer`），其 `st_ino` **互不相同**。
- 同一端（如读端）经 `fork()` 继承后，父子进程中的 `st_ino` 保持一致；但读写两端从不共享相同的 inode 数值。
- **关键定性**：在既有日志中检索 `inode=7364773697224751085` **在原理上只能命中读端**，不能通过该 inode 数值寻找写端。

### 2.3 重复采样字段含义
- `X64BLOCK_IO_SAMPLE`：
  - `seq`：进程私有原子序列号（`io_sample_seq`，硬编码上限 256）。
  - `ts_us`：CLOCK_MONOTONIC 微秒时间戳。
  - `guest_fd` / `host_fd`：Guest 映射描述符（4）与宿主打开描述符（51）。
  - `can_block=1`：非非阻塞（可阻塞读取）。
  - `count` / `gva`：Guest 请求读取长度（寄存器 `x2`）与目标虚地址（寄存器 `x1`）。
- `X64BLOCK_READ_SAMPLE`：
  - `seq`：进程私有原子序列号（`sample_read_seq`，硬编码上限 64）。
  - 为同一 read 系统调用内联快速路径（fast-path）处的重复诊断记录。

---

## 3. 采样行数去重、调用阶段与时段解构

### 3.1 179 行 grep 结果溯源与去重
在 `run-aizg68sd/stderr.log` 中 grep `7364773697224751085` 得到 179 行，已被精确逐行解构：

| 产生 Hook | 行数 | 原始行号范围 | 序列号范围 | 统计谓词 | 说明 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`X64BLOCK_IO_SAMPLE`** | **147** | L736 – L1009 | `seq=33` – `seq=255` | `line.startsWith("X64BLOCK_IO_SAMPLE") && line.includes("inode=7364773697224751085")` | 到达 255 触顶门限（`seq < 256`）后停止输出 |
| **`X64BLOCK_READ_SAMPLE`** | **32** | L737 – L817 | `seq=32` – `seq=63` | `line.startsWith("X64BLOCK_READ_SAMPLE") && line.includes("inode=7364773697224751085")` | 到达 63 触顶门限（`seq < 64`）后停止输出，与上者重复记录 |
| **总计** | **179** | L736 – L1009 | — | — | **去重后唯一系统调用进入（ENTER）事件为 147 次** |

### 3.2 调用阶段（ENTER vs RETURN）、返回值与时段
- **调用阶段**：179 行全部为系统调用**进入（ENTER）**记录。
- **返回阶段（RETURN）、errno 与读写字节**：**未记录（0 行）**。
  - 原因：原系统的 `IO_TX_RETURN` hook 需门控 `io_fixture_identity_active()`（依赖 `fixture_step3_seen`，源码见 `src/syscall/io.c:66`）；因探针未达 Step 3，该门控始终未开放。诊断 hook 仅挂载于系统调用入口处，不具备退出观测能力。
  - **重要边界**：`read-enter` **不是系统调用返回或长阻塞的实证**，仅记录发起调用的瞬时参数。
- **采样时段**：
  - 147 条进入样本的单调时间戳从 `ts_us=1252916732090`（L736）至 `ts_us=1252916760735`（L1009）。
  - **总持续时间仅 28,645 微秒（约 28.65 毫秒）**。
  - 这是 `wineboot.exe --init` 进程在初始化早期与 wineserver 之间的高频 IPC 交互（同时伴随 70 次向 `guest_fd=3 / host_fd=37` 的写入），并非贯穿 25 秒的挂起现场。

---

## 4. 进程与 Watchdog 快照状态分析

### 4.1 进程身份归属
- 179 行管道 read 采样全部隶属于：
  - `host_pid=45102, guest_pid=5, gtid=5`
  - `elf=.../wine-preloader`
  - `cmdline=.../wine-preloader .../wine C:\windows\system32\wineboot.exe --init`
  - `guest_fd=4, host_fd=51`

### 4.2 Watchdog 快照状态与语义辨析
运行后期有界 Watchdog 记录了 24 次进程线程快照（L1027 至 L1240）：
1. **`wineboot.exe --init` (`host_pid=45102 / guest_pid=5 / gtid=5`)**：
   - 24 次快照中：
     - **16 次处于 `in_syscall=-1`**：表明采样时刻该线程上下文**未处于已标记系统调用**（可能处于 guest 用户态、EL1 异常处理或宿主调度中，不能充分证明 CPU 必然在用户态）。
     - **7 次处于 `in_syscall=73`**：AArch64 `SYS_ppoll`。
     - **1 次处于 `in_syscall=113`**：**AArch64 `SYS_clock_gettime`**（核对本项目 `dispatch.tbl:127`，系统调用 113 为 `clock_gettime`；`clock_nanosleep` 为 115）。
   - **确证**：`wineboot` **并未卡死在该管道描述符的 read 上**。在 28.65 ms 的 IPC 脉冲后，它已脱离 fd 4 的读取。
2. **启动根进程 (`host_pid=45098 / guest_pid=1 / gtid=1`)**：
   - 命令行：`sh -c ... exec .../wine 'C:\vk_enum_x64.exe'`
   - 24 次快照中：**全部处于 `in_syscall=63`（AArch64 `SYS_read`）**。
   - **离散采样边界**：24 次快照均命中 `SYS_read`，仅证明在 24 个离散采样瞬间该根线程处于 `read` 调用上下文中，**不足以断言这是同一个 `read` 调用持续 25 秒未返回**（亦可能处于高频循环读取中）；且既有快照未记录其读取的具体 fd / inode。
3. **PE 身份脱钩**：
   - `wineboot.exe` 是 Wine 前缀初始化工具，不是目标 PE；
   - 启动根进程 `45098` 是 Wine 启动加载器，不是目标 PE；
   - WINEDEBUG 中的 Windows PID `0028/002c` 与 elfuse guest PID/TID 仅能通过可执行文件映像路径关联，无直接跨命名空间 crosswalk。

---

## 5. 写端与生命周期日志线索检索

对 `run-aizg68sd/stderr.log` 检索系统调用生命周期关键字：
- **`pipe` / `pipe2`**：未记录（诊断 hook 未挂载创建系统调用）。
- **`clone`**：12 条（`THREAD_LIFETIME_ENTER` 记录）。
- **`dup` / `dup2` / `dup3`**：0 条。
- **`close`**：0 条。
- **对 `inode=7364773697224751085` 的写操作**：0 条（如前实测，写端持有不同的内核 inode）。
- **客观结论**：
  - 日志中未观测到写端由谁持有、何时写入及何时关闭。
  - **未观测（Unobserved）严格不等于无写端（No Writer）**。写端状态明确标定为 **`unknown`**。

---

## 6. 与基线成功用例 (`run-2bxmxfs0`) 的事实比较

对比已验收的 x64 成功运行（`logs/lead-round7/run-2bxmxfs0`，实现 `C:\hello-x64.exe` 真实 exit 0 并输出 `X64_FEX_OK`）：
1. **成功用例中同样存在 `wineboot.exe --init`**：
   - `run-2bxmxfs0/stderr.log` 第 1-3 行明确出现：
     - `0024:trace:process:NtCreateUserProcess ... wineboot.exe cmdline "wineboot.exe --init"`
     - `0024:trace:process:NtCreateUserProcess ... pid 0028 tid 002c`
     - `002c:trace:loaddll:build_module Loaded L"C:\windows\system32\wineboot.exe"`
   - `wineboot.exe` 初始化成功后，紧接着由 `services.exe` 启动系统服务，最终载入并执行 `hello-x64.exe`。
2. **比较结论**：
   - `wineboot.exe --init` 的出现是 Wine 前缀初始化的**标准必经阶段**。
   - 成功用例使用 `python3.14 proton runinprefix` 执行，而本轮测试使用直接 `wine` 命令；两者在环境初始化与服务编排上存在候选差异，但**不能将 wineboot 的存在作为启动阻断的根因**。

---

## 7. 严格有界结论与禁止推论边界

1. **已证事实**：
   - `run-aizg68sd` 超时（`exit=124`，持续 25.12 秒，`stdout_bytes=0`）。
   - 179 条 inode `7364773697224751085` 样本去重后为 147 次进入，在 28.65 ms 时段内由 `wineboot.exe --init` 产生，无返回/errno/字节记录。
   - `wineboot` 后期处于未标记系统调用状态、ppoll 及 clock_gettime (nr=113)，未卡死在管道 read 上；根进程 `45098` 在 24 次离散快照中处于 read (nr=63)。
2. **未证与禁止推论边界**：
   - **无 PE marker 只证明 PE 创建/执行未被观测**：日志中未观测到 `vk_enum_x64.exe` 的进程创建或 Step 标记，仅代表该观测窗口内未采到该流，不能断言“PE 绝对未启动”；
   - **不能排除 vDSO 异常或 elfuse 机制问题**：Wine 启动器自身在启动流程中也可调用 vDSO（如重定向时间函数），超时未达 Step 3 无法排除底层的 vDSO/翻译交互问题；
   - **禁止宣称“管道无写端”**：写端未被观测，写端状态严格为 `unknown`。

---

## 8. 下一项最小观测建议 (Minimal Next Observation)

不开展重量级盲测，建议在派生代码中加入以下三项最小非侵入观测点：
1. **管道创建对端关联记录**：
   - 文件：`sources/elfuse-x64block-derived/src/syscall/fs.c:2889`
   - 变更：在 `pipe` / `pipe2` 成功分配处，输出配对信息：`PIPE_PAIR guest_rd=%d host_rd=%d rd_ino=%llu guest_wr=%d host_wr=%d wr_ino=%llu`，打通 XNU 下读端 inode 与写端 inode 的映射。
2. **根进程阻塞 FD 探针**：
   - 文件：`sources/elfuse-x64block-derived/src/syscall/syscall.c`
   - 变更：在 Watchdog 快照（`FUTEX_OWNER_THREAD`）或 `SYS_read` 快速路径处，针对 `proc_get_pid() == 1` 记录当前尝试读取的 `guest_fd`、`host_fd` 及 `inode`，查明根进程在 24 次快照中等候的对端。
3. **跨命名空间 PID/TID 映射机制（待关联）**：
   - 架构说明：Linux 侧的 `clone`/`execve` 仅能映射 Linux guest PID 与 host PID，无法自动关联 Windows PID；需要配合 Wine 侧 trace（如 `WINEDEBUG=+process` 或 ntdll 进程创建日志）建立跨命名空间关联，将 Windows PID/TID 与 Linux guest PID/TID 显式打通。
