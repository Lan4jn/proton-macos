# SIGCHLD 修复独立复验与 si_code / 数据结构规范性核定报告 (Task-91)

**独立复验员**：futex-owner-r36 (执行方独立复验)  
**复验对象**：
- 修复前二进制：`sources/elfuse-once-count-derived/build/elfuse` (SHA256: `24b488983f4c1be058657355c4ce894e446451e2dfa902a1fd5b618b81fe9b16`)
- 修复后二进制：`sources/elfuse-sigchld-status-derived/build/elfuse` (SHA256: `459e44b0850797bbf0fd5777e34fcdb697da27a2dbb22ecab823b699fbef55ab`)
- 审查员交付补丁：`logs/sigchld-status/sigchld_status.patch`
- 审查员报告与收据：`reports/sigchld-status.md`、`logs/sigchld-status/receipt.json`
**验证测试产物**：
- 完整信号回归收据：`logs/sigchld-verify/suite_rerun.json`
- AArch64 布局与字段现场探针：`logs/sigchld-verify/probe_sigchld`

---

## 一、 信号套件亲自重跑与红绿比对 (Suite Re-run Evidence)

复验员使用同一测试程序 `scripts/runtime/signals/test_signals` (SHA256: `a670634ab3e9ebb09fea1db6c89c9ff187b6e1b8fbed986da94515570d732f90`) 分别在修复前与修复后二进制下执行完整跑测，结果保存在 `logs/sigchld-verify/suite_rerun.json`：

| 子测试项 | 期望行为 | 修复前 (24b48898...) | 修复后 (459e44b0...) | 状态转移 |
| :--- | :--- | :---: | :---: | :---: |
| **Test 1: 基本投递 & errno / sa_mask** | 捕获 SIGUSR1，保持外部 errno 与 sa_mask | ✅ **PASS** | ✅ **PASS** | 无回归 |
| **Test 2a: 阻塞读无 RESTART** | SIGALRM 打断管道读，返回 -1 / EINTR | ✅ **PASS** | ✅ **PASS** | 无回归 |
| **Test 2b: 阻塞读带 SA_RESTART** | SIGALRM 自动重启，读回子进程 2 字节 "OK" | ✅ **PASS** | ✅ **PASS** | 无回归 |
| **Test 3: SA_SIGINFO siginfo_t** | 接收 si_signo=10, si_pid=1, si_code=0 | ✅ **PASS** | ✅ **PASS** | 无回归 |
| **Test 4: sigaltstack 备用栈** | handler 栈指针落在备用栈区间 | ✅ **PASS** | ✅ **PASS** | 无回归 |
| **Test 5: sigprocmask 阻塞与解阻** | 阻塞期置位 pending，解阻瞬间立即派发 | ✅ **PASS** | ✅ **PASS** | 无回归 |
| **Test 6: SIGCHLD & waitpid** | waitpid 回收 42，handler 读到 si_status=42 | ❌ **FAIL** (got 0) | ✅ **PASS** (got 42) | 🔴 → 🟢 **红转绿** |
| **Test 7: setitimer 定时器** | 周期性收到 3 次 SIGALRM 滴答 | ✅ **PASS** | ✅ **PASS** | 无回归 |
| **最终退出码与掩码** | - | **`exit=32` (mask 0x20)** | **`exit=0` (ALL PASS)** | **全绿闭环** |

**复验定论**：确凿证实仅有第 6 项由红转绿，其余 6 项稳定保持 GREEN，**无任何功能退化或时序回归**。

---

## 二、 si_code 规范性核查与实测判定 (si_code Normative Audit)

### 1. 静态补丁逻辑审计
Lead 提到审查补丁时怀疑“si_code 被传成 0 (SI_USER)”。复验员深入比对 `logs/sigchld-status/sigchld_status.patch` 源码行：
- **默认通用发送接口** (`proc.c:64-69`)：
  `proc_send_guest_signal` 确实默认填入 `LINUX_SI_USER (0)`，主要用于通用 kill/killpg 模拟；
- **子进程退出专属路径** (`proc.c:76-98` 及 `proc.c:1642-1655`)：
  `proc_process_exit` 在子进程退出时**显式根据 wait_status 进行状态解析**：
  ```c
  int32_t exit_si_code = CLD_EXITED;
  int32_t exit_si_status = 0;
  if (WIFEXITED(wait_status)) {
      exit_si_code = CLD_EXITED;              // = 1
      exit_si_status = WEXITSTATUS(wait_status);
  } else if (WIFSIGNALED(wait_status)) {
      exit_si_code = WCOREDUMP(wait_status) ? CLD_DUMPED : CLD_KILLED; // = 3 或 2
      exit_si_status = WTERMSIG(wait_status);
  }
  // 通过 proc_send_guest_signal_info 把 exit_si_code (1) 与 exit_si_status 发送给父进程
  ```
- **接收端反序列化** (`proc.c:3387-3430`)：
  父进程在 `sig_drain_cb` 中从管道行解析出 `si_code=1` 并调用 `signal_queue_chld_status`，存入 `std_info[LINUX_SIGCHLD - 1].si_code`。

### 2. 运行时现场探针实测 (`probe_sigchld`)
为消除任何静态推测争议，复验员在 `logs/sigchld-verify/probe_sigchld.c` 编写现场探针并在 `459e44b0...` 下实测，原始输出如下：
```text
sizeof(siginfo_t) = 128
offsetof(siginfo_t, si_signo)  = 0
offsetof(siginfo_t, si_errno)  = 4
offsetof(siginfo_t, si_code)   = 8
offsetof(siginfo_t, si_pid)    = 16
offsetof(siginfo_t, si_uid)    = 20
offsetof(siginfo_t, si_status) = 24
=== RUNTIME CAPTURED SIGCHLD SIGINFO ===
si_signo  = 17 (expected SIGCHLD=17)
si_code   = 1 (CLD_EXITED=1, SI_USER=0)
si_pid    = 2 (child_pid=2)
si_status = 42 (expected 42)
```

**裁决结论**：
1. 实测运行时捕获的 `si_code` **严格为 `1 (CLD_EXITED)`**，而非 0；
2. 子进程 PID `si_pid` 严格对应真实子进程 PID；
3. `reports/sigchld-status.md` 中的描述完全属实，**不存在 si_code 留零或降级为 SI_USER 的残留缺陷**。

---

## 三、 AArch64 Linux 数据结构布局与偏移断言核对

依据 AArch64 Linux ABI 规范（见内核头文件 `<asm/siginfo.h>` 与 glibc `<bits/siginfo-consts.h>`）：
在 64 位 ARM 上，`siginfo_t` 大小为 128 字节，`si_signo` (4B), `si_errno` (4B), `si_code` (4B), 随后为 4 字节填充对齐（padding），接下来是联合体。对于 `SIGCHLD`：
- `si_pid` (4B，偏移 16)；
- `si_uid` (4B，偏移 20)；
- `si_status` (4B，偏移 24)；
- 随后包含 `_pad` 对齐至 128 字节。

### 源码结构体与静态断言对比
在 `sources/elfuse-sigchld-status-derived/src/syscall/signal.h` 中：
```c
typedef struct {
    int32_t si_signo, si_errno, si_code;
    int32_t _pad_code;
    int32_t si_pid, si_uid;
    union {
        uint64_t si_value;
        struct {
            int32_t si_status;
            int32_t _pad_status;
            uint64_t si_utime;
            uint64_t si_stime;
        } _sigchld;
    };
    uint8_t _pad[128 - 48]; /* Pad to 128 bytes total */
} linux_siginfo_t;

_Static_assert(sizeof(linux_siginfo_t) == 128, "linux_siginfo_t size mismatch");
_Static_assert(offsetof(linux_siginfo_t, _sigchld.si_status) == 24, "si_status offset mismatch");
```
现场探针实测打印的 guest glibc 原生布局：
- `sizeof(siginfo_t) = 128`
- `offsetof(siginfo_t, si_status) = 24`

**复验定论**：修补的结构体大小、成员偏移与内核静态断言与 AArch64 Linux 原生规范**100% 精确吻合**。

---

## 四、 跨路径无副作用评估 (Cross-Path Side-Effect Audit)

1. **非 SIGCHLD 信号路径**：
   - 普通信号（如 `SIGUSR1`, `SIGALRM`）在 `signal.c:2507` 赋值 `si_value = rt_info.si_ptr`，该联合体占用前 8 字节；
   - 赋值仅在 `if (signum == LINUX_SIGCHLD)` 时覆盖 `_sigchld.si_status`，对普通信号完全不执行，普通信号的 `si_value` 与 `si_ptr` **无任何污染**；
2. **同步等待路径 (`sigtimedwait`)**：
   - `sigtimedwait` 内部同样同步更新了 `if (signum == LINUX_SIGCHLD) si._sigchld.si_status = info.si_status;`，使得通过同步系统调用获取 `SIGCHLD` 的进程同样能获得子进程退出码；
3. **故障信号 (`SIGSEGV`, `SIGBUS`, `SIGTRAP`)**：
   - 故障信号走 `pending_fault.valid` 专属分支（`memcpy(&frame.info.si_pid, &pending_fault.addr, 8)`），与普通信号及 `SIGCHLD` 完全解耦。

---

## 五、 reports/sigchld-status.md 措辞与事实一致性审查

对 `reports/sigchld-status.md` 进行逐条审阅：
1. **基线赤字记录**：真实完整引用了 `Test 6 FAIL` 事实；
2. **转绿实测记录**：与复验员亲自重跑的 `logs/sigchld-verify/suite_rerun.json` 完全吻合；
3. **措辞严谨性**：报告未将信号全绿夸大为“图形已通”或“Wine 整体完成”，明确限定为“Linux ARM64 信号子系统元数据贯通修复”；
4. **审核结论**：报告中不存在任何夸大或虚假修饰，**判定通过验收**。
