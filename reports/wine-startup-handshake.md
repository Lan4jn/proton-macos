# Wine 启动握手协议与 Root Read16 写端生命周期追溯报告 (v2 严格分级复核版)

- **任务编号**：task-115
- **执行角色**：wine-recovery-reviewer (Team Teammate)
- **审查目标**：从 task-113 已证 root pending read16 反向定位 Wine 业务协议及责任写端，核查 CLOEXEC/内部 close 等生命周期盲区，严格区分 `observed`、`derived_candidate` 与 `unknown` 证据层级，给出最小针对性观测建议；不盲改 fd 逻辑，不重跑 Wine。
- **关联工件**：
  - 机器可读综合数据：`logs/wine-startup-handshake/handshake_analysis.json` (所有 64 位数字严格采用十进制字符串，杜绝 Number 转换失真)
  - 上游候选源码固化：`sources/wine-startup-handshake-analysis/` (5 份 Valve Wine 文件，标记为 candidate_upstream_alignment)
  - 关联运行现场：`logs/x64-pipe-lifecycle/run-54km9yf2/stderr.log`
  - 关联测试报告：`reports/x64-pipe-lifecycle.md`

---

## 1. 证据层级定性总览 (Evidence Tiering)

根据严格调试规范，本报告将全部事实与推断划分为三个互斥层级：

| 证据层级 | 认定范围与具体事项 |
| :--- | :--- |
| **OBSERVED**<br>*(原始日志直接记录的物理事实)* | 1. **管道创建 (Line 2124)**：Root 进程 (`host_pid=78429, guest_pid=1, gtid=1`) 创建管道 `pipe_id="336849990057986"`，读端 `guest_rd=8, host_rd=54, rd_ino="10560977351731242728"`，写端 `guest_wr=9, host_wr=55, wr_ino="15913276913127907580"`。<br>2. **Fork 继承 (Line 2358, 2361)**：`guest_pid=4` 与 `guest_pid=5`（`wineboot` 进程）继承了写端 inode `"15913276913127907580"`。<br>3. **首次 read16 成功返回 (Line 2841~2915)**：Root 进程对 `guest_fd=8` 发起首次 `read(count=16, gva=0x7ffd6c0)`，耗时 0.224 秒后成功返回 16 字节。<br>4. **二次 read16 陷入未返回等待 (Line 2928)**：Root 进程对 `guest_fd=8` 发起二次 `read(count=16, gva=0x7ffd9b0)`，产生 24 次相同的看门狗 pending 快照（`pid=78429, in_syscall=63, pending_fd=8, pending_call_id=336849990058240`）。<br>5. **子进程 fd 9 映射被替换 (Line 3852)**：`guest_pid=5` 使用 `guest_fd=9` 读取普通文件（`host_fd=151, inode="15010959"`），证明 `guest_pid=5` 的 `guest_fd=9` 已不再指向原管道。 |
| **DERIVED_CANDIDATE**<br>*(基于候选源码与静态反汇编的推导假设)* | 1. **调用点候选匹配**：`ntdll.so` 静态扫描发现 `wait_select_reply` 内部（PC `0x3dbd8`）存在 `mov w2, #0x10; bl <read@plt>`，入参 `w0` 取自 TEB 偏移 `0x38c`（对应候选源码 `thread_data->wait_fd[0]`）。<br>2. **协议结构候选**：候选 Valve Wine dc26e618（非认证精确构建）在 `server_protocol.h:195` 定义 16 字节的 `struct wake_up_reply`（cookie 8B, signaled 4B, pad 4B）。<br>3. **写端责任候选**：候选 `server/thread.c:1230` 的 `send_thread_wakeup` 负责向 `thread->wait_fd` 写入该 16 字节结构。 |
| **UNKNOWN**<br>*(现有证据无法证实、不可外推的未知项)* | 1. **实际运行时寄存器未知**：原始日志 Line 2928 的 IO hook 未记录 LR、ELR、SP 或 TEB 指针，`gva=0x7ffd9b0` 仅从地址形态上推测为栈区，不能断言其动态精确命中 `0x3dbd8`。<br>2. **SCM_RIGHTS 交付状态未知**：写端 `wait_fd[1]` 是否成功通过 SCM_RIGHTS 交付给 `wineserver` 进程，无日志证据。<br>3. **wineserver 侧内部状态未知**：wineserver 是否尝试写入、Root 正在等待的具体 Windows Handle 对象是哪一个、为何未触发唤醒，属于完全未知。<br>4. **子进程写端释放路径未知**：`guest_pid=5` 的 `guest_fd=9` 是经 `close_range`、`CLOEXEC` 还是 `dup2` 隐式替换，缺乏针对性 trace 证据。<br>5. **其他代码路径未排他排除**：read@plt 扫描仅覆盖字面量 `mov w2, #16`，不能排除动态计算长度、函数指针间接调用、raw syscall 或其他动态库的读操作。 |

---

## 2. read@plt 扫描方法、完整性与局限性说明

针对 `fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/ntdll.so` 开展的静态指令扫描，具体方法与边界如下：

### 1. 扫描方法与检出结果
- 对 `ntdll.so` 代码段进行反汇编，检索所有指向 `0xc740 <read@plt>` 的 `bl` 指令；
- 统计并在附近 5 条指令中检查第三参数寄存器 `w2` / `x2` 的字面量设置；
- **检出情况**：在所有字面量常数调用中，仅在 `wait_select_reply`（PC `0x3dbd8`）处观察到 `mov w2, #0x10`（16 字节）。其余字面量调用为 4 字节（`__wine_unix_spawnvp` / `NtCreateUserProcess` 管道错误传输）、32 字节（`get_firmware_info`）或从结构体字段动态加载的长度（如 `NtReadFileScatter`）。

### 2. 扫描局限性 (Limitations)
该静态扫描**不能构成排他性证明**，存在以下已知局限：
1. **动态长度未覆盖**：若某处代码通过计算或变量读取得到 `len`，且运行时恰好等于 16（例如 `read(fd, buf, dyn_len)`），静态检索无法识别；
2. **间接跳转未覆盖**：通过函数指针（`blr xN`）发起的 read 调用未被 `bl read@plt` 捕获；
3. **内联汇编 / 裸 Syscall 未覆盖**：若存在绕过 libc 的直接系统调用（`svc #0`，AArch64 nr=63），不经过 PLT；
4. **其他模块未覆盖**：调用可能发生在 `libc.so.6` 内部（如 stdio 缓冲读）或其他 Unix 伴生库中；
5. **构建身份差异**：上游 Valve Wine dc26e618 属于**候选对齐源码**，非发布者重分发包的精确源码。因此，`0x3dbd8` 处的 `wait_select_reply` 是**高置信度的候选解释（Derived Candidate）**，不可当作已动态闭环确证的事实。

---

## 3. 候选协议与写端责任分析 (Candidate Protocol)

在上述候选约束下，推导出的协议结构如下：

### 1. 候选数据结构 (`include/wine/server_protocol.h:195`)
```c
struct wake_up_reply
{
    client_ptr_t cookie;    /* 8 字节：等待标记指针 */
    int          signaled;  /* 4 字节：唤醒状态码 / NTSTATUS */
    int          __pad;     /* 4 字节：64位对齐填充 */
};
```
结构体严格占用 16 字节。

### 2. 候选写端与传递逻辑
- 候选源码显示：客户端主线程在 `init_thread_pipe` 中创建读写管道，将写端 `wait_fd[1]` 发送给 `wineserver`；
- 当服务端检测到被等待对象处于已发信号状态时，通过 `server/thread.c!send_thread_wakeup` 向该管道写入 16 字节唤醒数据包；
- **推断结论**：若此模型成立，Root 并非等待常规子进程的标准 IO 管道，而是在执行 `server_wait`，等待服务端因某项异步事件被满足而发回唤醒通知。

---

## 4. elfuse 管道生命周期审计与插桩副作用评估

在 `sources/elfuse-pipe-lifecycle-derived/` 中，对管道生命周期追踪机制进行深度代码核对：

### 1. 管道关闭事件覆盖盲区
| 路径 / 系统调用 | 所在位置 | 是否发射 `PIPE_CLOSE` | 影响定性 |
| :--- | :--- | :---: | :--- |
| **`sys_close`** | `src/syscall/fs.c:1189` | **YES** | 仅单 fd 显式关闭被记录。 |
| **`sys_close_range`** | `src/syscall/fs.c:1410` | **NO** | 批量清理直接调用 `fd_cleanup_entry`，漏钩 `pipe_lifecycle_on_close`。 |
| **`exec_close_cloexec_fds`** | `src/syscall/exec.c:64` | **NO** | execve 前对带 `O_CLOEXEC` 的所有 fd 批量清理，漏钩 `pipe_lifecycle_on_close`。 |
| **进程退出清理** | `src/runtime/thread.c` | **NO** | 进程销毁时回收 fd 表，漏钩 `pipe_lifecycle_on_close`。 |

**客观定性**：日志中未出现针对写端 fd=9 的 `PIPE_CLOSE` 记录，**不能作为写端依然打开的证据**。子进程 `guest_pid=5`（`wineboot`）在 Line 3852 已经将 `guest_fd=9` 复用为普通文件（`inode="15010959"`），证明旧映射已被替换；具体是通过 close、close_range 还是 dup2 覆盖，需进一步针对性 trace。

### 2. 插桩副作用收敛定性
- `pipe_meta_table` 为独立静态副表数组（`FD_TABLE_SIZE` 大小）；
- **收敛声明**：经比对源码 diff，未见改变 `fd_table_t` 结构体内存布局、未见修改 `linux_flags`、未见篡改 fork/exec 的继承标志；但并发竞争或其他未预料的边界副作用在当前证据下**未完全证伪**，不可声称“绝对未引入任何 bug”。

---

## 5. 64 位数字十进制字符串修复 (No Precision Loss)

在此前生成的 JSON 中，64 位 uint64 标识因未经字符串化处理，在 JavaScript 运行环境中遭遇 IEEE-754 浮点数精度截断（高于 2^53 - 1 的低位被舍入为 0）。本次已在 `logs/wine-startup-handshake/handshake_analysis.json` 中全量修复为**十进制纯字符串**：

| 标识字段 | 原始 raw 现场字符串 | 前次失真错误数值 (已废除) | 本次修复后标准十进制字符串 |
| :--- | :--- | :--- | :--- |
| `pipe_id` | `336849990057986` | 336849990057986 | `"336849990057986"` |
| `rd_ino` | `10560977351731242728` | 10560977351731243000 | `"10560977351731242728"` |
| `wr_ino` | `15913276913127907580` | 15913276913127907000 | `"15913276913127907580"` |
| `p5_reused_inode` | `15010959` | 15010959 | `"15010959"` |

---

## 6. 下一步最小针对性观测建议 (不预设排他性因果)

1. **下沉 `pipe_lifecycle_on_close` 补齐关闭记录**：
   将关闭挂钩置于 `src/syscall/fdtable.c:1428` 的 `fd_cleanup_entry` 入口处，覆盖所有 fd 回收路径，以消除生命周期观测盲区。
2. **验证 `WINEDEBUG=+server` 候选方案的可用性**：
   在环境允许的情况下测试开启 `+server`，需验证其日志输出通道在当前 harness 下是否可用，以及能否将服务端请求明确关联至具体的 Windows PID，不可预先假设必然能排他判定 Root 等待的目标对象。

---

### 交付物索引
- 分析报告：`reports/wine-startup-handshake.md`
- 机器可读综合数据：`logs/wine-startup-handshake/handshake_analysis.json`
- 上游候选源码固化：`sources/wine-startup-handshake-analysis/`
