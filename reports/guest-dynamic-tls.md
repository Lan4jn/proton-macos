# AArch64 Linux Guest Glibc 动态 TLS (TLSDESC) 运行时并发探针验证报告 (修订版)

- **任务编号**：task-116
- **执行角色**：wine-guard-verifier (Team Teammate)
- **审查与验证目标**：
  1. 在 elfuse HVF 隔离虚拟化环境中，实际动态执行 AArch64 Linux ELF 运行时探针；
  2. 验证真实 guest glibc + dlopen / dlsym + `__thread` PIC TLS / TLSDESC 延迟加载（Late-load TLS）可用性；
  3. 严格落实“工作线程创建后再 dlopen”，覆盖启动后延迟加载场景（`late_dlopen_tls_verified=true`）；
  4. 客观界定底层分配机制：glibc 动态链接器可能复用预留 static TLS surplus 空间，DTV 动态堆分配定性为未直接观测（`dtv_dynamic_allocation_covered=not_directly_observed`）；
  5. 验证主线程与两个 worker pthread 条件变量同步、独立的 guest 虚拟地址空间与深度初值/写入隔离；
  6. 验证实际 callback 内部 `pthread_cleanup_push/pop` 在取消发生（`PTHREAD_CANCELED`）时的展开契约；
  7. 严格恪守分层定性：不泛称全 Wine 修复，GDI 缓存恢复与全链路死锁维持 UNKNOWN。
- **实验工件根目录**：/Users/mewcapoo/Projects/proton-macos-lab
- **关联工件与物理哈希**：
  - 机器可读综合收据：`logs/guest-dynamic-tls/receipt.json`
  - 完整执行原始日志：`logs/guest-dynamic-tls/runner.log`
  - Guest ELF 动态 Runner：`sources/guest-dynamic-tls/guest_dynamic_tls_runner` (SHA256: `05413263b00f27e754c0fa87af4b01544c3c4db0e2f17e17aeaa666b9417b2b1`)
  - Guest ELF 动态共享库：`sources/guest-dynamic-tls/libv3_guard.so` (SHA256: `3582e0d4f140ca3b1bb58b3293c95cca20215ce637b04824502b32f0f98f10a8`)
  - 自动提取脚本：`scripts/runtime/guest_dynamic_tls/extract_guard_guest.py`
  - 自动化回归套件：`scripts/runtime/guest_dynamic_tls/run_guest_dynamic_tls.py`

---

## 1. 核心裁定矩阵与多层状态界定 (Verdict Matrix)

| 检验层次 / 维度 | 裁定结果 | 详细依据与机器证据 |
| :--- | :---: | :--- |
| **交叉编译与动态链接** | **PASS** | 使用宿主 clang + Homebrew LLD 21.1.8 成功生成 AArch64 Linux ELF 共享库 `libv3_guard.so` 与可执行文件 `guest_dynamic_tls_runner`；interp 指向 `/lib/ld-linux-aarch64.so.1`。 |
| **线程创建后 Late-load dlopen** | **PASS** | 显式在主线程创建 Worker 1 与 Worker 2 之后执行 `dlopen(".../libv3_guard.so", RTLD_NOW | RTLD_LOCAL)`，句柄返回 `0x1002550`，确证 `late_dlopen_tls_verified=true`。 |
| **DTV 动态堆分配直接观测** | **NOT_DIRECTLY_OBSERVED** | 尽管采用了标准 PIC TLSDESC 并在线程创建后加载，但 glibc 动态链接器内部可能优先使用预留的 static TLS surplus 空间（如 `dl_tls_static_surplus`）满足较小的 TLS 需求；在没有 loader resolver 内部断点或 DTV 分配日志直接证据前，客观定性为 `not_directly_observed`。 |
| **Guest 虚拟地址隔离** | **PASS** | 实测三线程深度变量在 guest 虚拟内存中地址严格相异：<br>Main Thread: `0x200064c20`<br>Worker 1: `0x200a3f980`<br>Worker 2: `0x20124f980`<br>三者两两不等（`assert(addr1 != addr2 && addr1 != addr_main)`）。注意：此处均为 **guest 虚拟地址**，非主机物理地址。 |
| **数值隔离与嵌套深度平衡** | **PASS** | Worker 1 深度为 1，Worker 2 深度为 2，Main 深度为 0，数值互不干扰；Worker 2 嵌套退出 2→1→0，深度为 1 时外层临界区保持保护。 |
| **取消发生与 Callback 清理展开** | **PASS (QUALIFIED)** | Worker 3 在真实 callback 内部临界区阻塞时被 `pthread_cancel`，经 `pthread_join` 返回 `PTHREAD_CANCELED`，确证取消事件已发生且清理处理程序由 unwinder 执行。需明确：线程终止后其线程存储空间随线程消亡释放，退出后不可跨线程直接读取其已释放的私有 TLS 指针。 |
| **零睡眠条件变量同步 (0 Sleep)** | **PASS** | 全流程采用 `pthread_cond_t/mutex` 严格事件握手，无任何 `usleep`。 |
| **Wine 完整动态库构建 (Full Build)** | **NOT_RUN** | 隔离实验环境中无完整 Wine 构建依赖与 configure 配置，恪守规则标记 `full_build=not_run`。 |
| **GDI Display Cache 自然恢复** | **UNKNOWN** | GDI 缓存恢复仍取决于外部显示事件（WM_DISPLAYCHANGE），状态维持 `UNKNOWN`。 |
| **Wine 全链路调用与死锁解决** | **UNKNOWN** | 本实验确证了 Linux AArch64 guest glibc 下动态 TLS 的运行时可靠性，但不妄称 Wine 全链路死锁已被修复。 |

---

## 2. ELF 与动态重定位验证 (Acceptance 4 & 7)

### 2.1 文件类型核查 (非 Mach-O 误跑)
- `guest_dynamic_tls_runner`:
  `ELF 64-bit LSB executable, ARM aarch64, version 1 (GNU/Linux), dynamically linked, interpreter /lib/ld-linux-aarch64.so.1, not stripped`
- `libv3_guard.so`:
  `ELF 64-bit LSB shared object, ARM aarch64, version 1 (GNU/Linux), dynamically linked, not stripped`

### 2.2 动态 TLS 重定位类型检验 (objdump -R libv3_guard.so)
共享库采用标准 `-fPIC` 编译，保留了默认的 AArch64 TLS 描述符动态重定位项：
```text
DYNAMIC RELOCATION RECORDS
OFFSET           TYPE                     VALUE
0000000000021208 R_AARCH64_TLSDESC        *ABS*
0000000000021218 R_AARCH64_TLSDESC        *ABS*+0x4
```
证实未采用退化的 initial-exec 静态模型，完整覆盖了动态共享库加载时的 TLSDESC 运行时解析路径。

---

## 3. elfuse 实际运行时执行日志与阶段标记

执行命令：
```bash
./sources/elfuse-derived/build/elfuse --timeout 15 --sysroot fixtures/runtime/sysroot \
  sources/guest-dynamic-tls/guest_dynamic_tls_runner \
  sources/guest-dynamic-tls/libv3_guard.so
```

实际标准输出（退出码：0，完整收录于 `logs/guest-dynamic-tls/runner.log`）：
```text
[GUEST_TLS: PHASE 1 START] ARM64 Linux dynamic TLS runner starting...
  Runner executable: /Users/mewcapoo/Projects/proton-macos-lab/sources/guest-dynamic-tls/guest_dynamic_tls_runner
[GUEST_TLS: PHASE 2] Spawning Worker 1 and Worker 2 BEFORE dlopen...
  Calling dlopen("/Users/mewcapoo/Projects/proton-macos-lab/sources/guest-dynamic-tls/libv3_guard.so", RTLD_NOW | RTLD_LOCAL)...
  Loaded library handle: 0x1002550
[GUEST_TLS: PHASE 2 DLOPEN_AFTER_THREAD_CREATION_OK] Symbols resolved successfully.
  [ISOLATION CHECK] Main Thread TLS depth addr: 0x200064c20, val: 0
  [ISOLATION CHECK] Worker 1    TLS depth addr: 0x200a3f980, val: 1
  [ISOLATION CHECK] Worker 2    TLS depth addr: 0x20124f980, val: 2
[GUEST_TLS: PHASE 3 DYNAMIC_TLS_ADDRESS_AND_VALUE_ISOLATION_OK] Thread isolation confirmed!
[GUEST_TLS: PHASE 3 NESTED_DEPTH_BALANCING_OK] Nested depth 2->1->0 verified.
[GUEST_TLS: PHASE 4] Testing cancellation cleanup inside callback pthread_cleanup_push...
  Worker 3 blocked in callback critical section. Cancelling...
  Worker 3 joined with PTHREAD_CANCELED (cancellation unwinder completed).
[GUEST_TLS: PHASE 4 REAL_CALLBACK_CANCELLATION_CLEANUP_OK] Callback cleanup verified!
[GUEST_TLS: PHASE 5] Testing early exit cleanup in main thread...
[GUEST_TLS: PHASE 5 EARLY_EXIT_CLEANUP_OK] Early exit balance verified.
[GUEST_TLS: ALL_PHASES_PASS] Guest Linux glibc dynamic TLS verification completely successful.
```

---

## 4. 交付工件与指纹清册

```text
├── sources/guest-dynamic-tls/
│   ├── libv3_guard.c                   (自动提取的 v3 guard 源码与导出)
│   ├── libv3_guard.so                  (SHA256: 3582e0d4f140ca3b1bb58b3293c95cca20215ce637b04824502b32f0f98f10a8)
│   ├── guest_dynamic_tls_runner.c      (并发动态探针源码)
│   └── guest_dynamic_tls_runner        (SHA256: 05413263b00f27e754c0fa87af4b01544c3c4db0e2f17e17aeaa666b9417b2b1)
├── scripts/runtime/guest_dynamic_tls/
│   ├── extract_guard_guest.py          (物理提取脚本)
│   └── run_guest_dynamic_tls.py        (自动化执行与收据生成套件)
├── logs/guest-dynamic-tls/
│   ├── runner.log                      (运行时完整 stdout/stderr 现场记录)
│   └── receipt.json                    (机器可读综合收据，已修订 dtv/late_dlopen 状态)
└── reports/guest-dynamic-tls.md        (本报告)
```

---

## 5. 结论与技术边界总结

本次实验将 Guard v3 推进至 **AArch64 Linux Guest glibc 动态运行时验证**，并经严格复核达成以下确定性结论：
1. **Late-load TLS 可用性确证**：在多线程已运行后执行 `dlopen`，动态链接器成功解析 `R_AARCH64_TLSDESC` 并在多线程并发下提供独立的线程局部访问能力；
2. **底层分配机制客观定性**：由于 glibc 内部实现机制，较小体积的 late-load TLS 变量可能直接使用 static TLS surplus 空间，并未在本次实验中直接观测到 DTV 动态堆分配（标记为 `not_directly_observed`），不盲目下绝对定论；
3. **虚拟地址与隔离边界**：确证了各线程在 guest 虚拟内存中持有相互独立的 TLS 存储（`0x200064c20` vs `0x200a3f980` vs `0x20124f980`），嵌套深度平衡展开；
4. **取消与资源生命周期**：确证了 `PTHREAD_CANCELED` 能够触发 `pthread_cleanup_push` 注册例程的展开清理；同时明确线程终止后其 TLS 存储空间即被回收，不可跨生命周期访问终止线程的私有存储。
5. 全程未改动旧版 patch，未改动 Wine 二进制，只读 upstream 源码哈希绝对未变。
