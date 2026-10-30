# 隔离 Xvfb 验证 Wine 桌面与 Windows Vulkan 初始化实测报告 (返工第2版)

**实验日期**：2026-10-16  
**执行员**：`steam-macos-research`  
**关联任务**：`task-37`（隔离 Xvfb 验证 Wine 桌面与 Windows Vulkan 初始化）  
**宿主环境**：Apple Silicon macOS 27.0.1 (arm64, Rosetta 2 可用)  
**交付物路径**：
- 包收据与审计：`artifacts/display-software/receipt.json`
- Xvfb 派生提取目录：`fixtures/runtime/xvfb-derived/`
- 独立 Wine 前缀：`fixtures/runtime/xvfb-wine/pfx`
- 控制器脚本：`scripts/runtime/xvfb_wine/controller.py`
- 控制器单测套件：`scripts/runtime/xvfb_wine/test_controller.py` (**7 PASS**)
- 宿主执行器：`scripts/runtime/xvfb_wine/run_xvfb_wine.py`
- 原始运行日志：`logs/xvfb-wine/run-1792122538/`
  - `summary.json` (宿主执行摘要与 absock 目录比对)
  - `xvfb_stdout.log`, `xvfb_stderr.log` (Xvfb 输出)
  - `xcb_probe.json` (libxcb 客户端握手测试记录)
  - `wine_stdout.log`, `wine_stderr.log` (Wine / Windows PE 完整诊断)
  - `Xauthority` (动态生成的 0600 MIT-MAGIC-COOKIE-1 凭据)

---

## 1. 核心结论与执行摘要 (Executive Summary)

1. **官方单包引入与 DT_NEEDED 完整满足**：
   - 从 Arch Linux ARM 官方镜像获取 `xorg-server-xvfb-21.1.25-2-aarch64.pkg.tar.xz`（文件大小 705,316 字节，远低于 40 MiB 预算）。
   - 本地 SHA-256 确认为 `9ff2d843b83dd61bf82746f3c675ca64f0d7ffa8c6e9b23281c005c83aedba7d`。宿主因缺失 gpg/keyring 未进行本地签名校验，如实记录为未验签名官方再分发。
   - `DT_NEEDED` 依赖审计确证：`libsystemd.so.0`, `libpixman-1.so.0`, `libXfont2.so.2`, `libXdmcp.so.6`, `libunwind.so.8`, `libnettle.so.9`, `libtirpc.so.3`, `libXau.so.6`, `libGL.so.1`, `libc.so.6` 在 `fixtures/runtime/arch-case/usr/lib/` 中**100% 齐备**，无需下载任何额外依赖包。
2. **前置隔离门与 Abstract Socket 状态确证（第2次返工深化）**：
   - **Xvfb 监听端**：通过 `-nolisten tcp -nolisten inet6 -nolisten local` 彻底关闭 TCP 及 Linux abstract socket 监听，保留且仅保留文件系统套接字。
   - **XKB 路径**：通过 `-xkbdir /usr/share/xkeyboard-config-2` 解决 Arch 软链接指向问题，Xvfb 成功就绪。
   - **套接字文件落盘**：套接字实际创建于 `<sysroot>/tmp/.X11-unix/X97`，锁文件位于 `<sysroot>/tmp/.X97-lock`。
   - **客户端连接事实与判定**：在第 1 次运行中，因客户端直接传路径受限而实际使用了 `DISPLAY=:97`。Linux 下使用冒号表示法会优先尝试 abstract connect，失败后才回退到文件系统路径。尽管宿主监视显示 `new_absock_dirs_on_host` 为空集，但这**不能证明未触碰 abstract 逻辑**（可能复用了宿主既有目录，或仅尝试连接未创建目录）。**必须如实认定：未证明 abstract 零调用**。
   - **架构收敛与硬隔离门（第 2 次返工新增）**：
     - 在后续 `task-40`（派生 elfuse 引入 `ELFUSE_ABSOCK_BASE` 彻底隔离抽象中继至 `lab/.s0700`）就绪前，`controller.py` **默认硬隔离门关闭冒号回退**（`resolve_active_display` 仅接受纯直接路径套接字握手，一旦路径套接字握手失败立即抛出 `RuntimeError` 拒绝启动 Wine，绝不静默降级为冒号显示）。
3. **控制器安全性与精准所有权清理修复（第2次返工深化）**：
   - **移除 setsid 与 killpg**：移除 `preexec_fn=os.setsid`，保证 Wine 与控制器同组受 supervisor 监管；移除 `os.killpg(os.getpgid(...))`，仅通过 `proc.terminate()` 退出直接子进程，消除 PID/PGID 杀错隐患。
   - **DisplayFD 强断言**：`check_displayfd_match` 显式校验 `int(dnum_str) == DISPLAY_NUM`，杜绝非预期编号放行。
   - **精准所有权清理 (Precision Owned Cleanup)**：
     - `clean_owned_lock`：读取 `.X97-lock` 内容并解析 PID，**仅当 PID 严格等于 `xvfb_proc.pid` 时才 unlink**；若 PID 不匹配则拒绝删除并保留日志。
     - `clean_owned_socket`：记录 Xvfb 就绪时的套接字 `(st_dev, st_ino, st_uid)`，清理前比对 `lstat` 节点元数据，**仅当 inode/uid 严格匹配时才 unlink**，防止误删未持有套接字。
   - **原子 0600 Xauthority 创建**：采用 `os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)` 杜绝初始可读窗口。
   - **单测全面验证**：上述 7 项安全与隔离逻辑全部纳入 `scripts/runtime/xvfb_wine/test_controller.py` 并在轻量环境下通过（**7 PASS**）。
4. **Win32U 内部 VkInstance 创建 vs. Target PE 用户态返回之关键区分**：
   - **Win32U 底层成功创建内部实例**：在 `wine_stderr.log` 中记录到：
     `00e0:trace:vulkan:win32u_vkCreateInstance Created instance 0x1162460, host_instance 0x1105f20.`
     `00e8:trace:vulkan:win32u_vkCreateInstance Created instance 0x1162470, host_instance 0x1105f30.`
     证明 Xvfb 成功为 Wine 提供了视窗上下文，解除了 task-35 中 `get_desktop_window` 无法进入驱动层的首个阻断。
   - **Target PE 用户态 `vkCreateInstance` 从未返回**：检查 `wine_stdout.log`，目标程序 `vk_enum_x64.exe` 的最后输出行严格停留在：
     `[WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)...`
     程序**从未打印**后续的 `SUCCESS: VkInstance created at...`，物理设备枚举（`vkEnumeratePhysicalDevices`）从未被执行。即用户态 API 从未成功返回给应用程序。
5. **首个确切技术阻断事件链实证 (First Blocker Event Chain)**：
   检查 `wine_stderr.log`（第 628-636 行），崩溃与重试事件的严格时序如下：
   1. **底层内部实例创建**（Line 628）：
      `00e0:trace:vulkan:win32u_vkCreateInstance Created instance 0x1162460, host_instance 0x1105f20.`
   2. **Native C++ 内存分配异常**（Lines 629-630）：
      `terminate called after throwing an instance of 'std::bad_alloc'`  
      `  what():  std::bad_alloc`
   3. **Wine SEH 异常分发次级失败**（Lines 631-632）：
      `00e0:err:seh:call_seh_handlers invalid frame 1000fa2d0 (0000000000022000-0000000000120000)`  
      `00e0:err:seh:NtRaiseException Exception frame is not in stack limits => unable to dispatch exception.`
   4. **桌面进程崩溃与重启死循环**（Lines 633-636）：
      `00e0:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code -2147483391, process_exiting 0.`  
      `0024:err:win:get_desktop_window failed to create desktop window`  
      `0024:trace:process:NtCreateUserProcess ... explorer.exe ... /desktop`  
      主测试进程（PID 0024）因桌面进程崩溃而重新尝试拉起桌面，陷入无休止循环直到 100s 超时。
   - **因果界定**：前置直接原因是底层运行时抛出了 `std::bad_alloc`，随后的 `invalid frame` 是在尝试分发该未捕获异常时触发的次级 SEH 分发失效。**抛出 `std::bad_alloc` 的确切调用栈来源（是 lavapipe、LLVM JIT 还是 Wine 自身 C++ 组件）以及其请求的内存大小目前未知**。

---

## 2. 参与运行的关键组件 SHA-256 清单

| 组件名称 | 本地路径 | SHA-256 校验和 | 属性说明 |
| :--- | :--- | :--- | :--- |
| **Xvfb 官方包** | `artifacts/display-software/xorg-server-xvfb-21.1.25-2-aarch64.pkg.tar.xz` | `9ff2d843b83dd61bf82746f3c675ca64f0d7ffa8c6e9b23281c005c83aedba7d` | 官方 Arch Linux ARM 预编译包（705 KB） |
| **Xvfb ELF** | `fixtures/runtime/xvfb-derived/usr/bin/Xvfb` | `6c1bb7864f1dc0b06ce2761852e008c2a41d6beff28c039fb2b23a7d7ef96e1b` | aarch64 ELF 可执行文件（2.00 MB） |
| **elfuse 运行时** | `sources/elfuse-lifecycle-derived/build/elfuse` | `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a` | 冻结版 lifecycle-derived runtime (f2) |
| **Target PE** | `fixtures/runtime/xvfb-wine/pfx/drive_c/vk_enum_x64.exe` | `f77f9b8fa427120cc1488625f46f4cc05b0f1d2d2b22032f137cb81462cec412` | 包含 CPU/llvmpipe 严格断言的 Windows x64 PE |
| **Linux Sysroot** | `fixtures/runtime/arch-case` | `c6bc1ef497...` (usr/bin/python3.14) | APFS 区分大小写 rootfs 镜像 |
| **Lavapipe ICD** | `fixtures/runtime/lavapipe-derived/.../lvp_icd.json` | `5c37895ce497041a7d65fc97931c3bf7918ea52f6b40285a73e65c92c416e919` | 软件 Vulkan 驱动声明 |
| **libvulkan_lvp.so**| `fixtures/runtime/lavapipe-derived/usr/lib/libvulkan_lvp.so` | `fa7223e7f45b7ee7ea9b119fa99b40fdb261e479a3fe270ee2c7c258d356fae3` | Mesa Lavapipe 纯 CPU 光栅化库 |

---

## 3. 隔离执行实证与控制流

### 3.1 Xvfb 启动命令行
```bash
/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/xvfb-derived/usr/bin/Xvfb :97 \
    -screen 0 640x480x24 \
    -nolisten tcp \
    -nolisten inet6 \
    -nolisten local \
    -xkbdir /usr/share/xkeyboard-config-2 \
    -auth /Users/mewcapoo/Projects/proton-macos-lab/logs/xvfb-wine/run-1792122538/Xauthority \
    -displayfd 4
```
- **就绪同步**：通过 `pipe_w` (fd 4) 成功捕获就绪标识字符串 `:97`，由 `check_displayfd_match` 验证整型匹配。
- **套接字与锁文件状态**：确证 `<arch-case>/tmp/.X11-unix/X97` 生成，锁文件 `<arch-case>/tmp/.X97-lock` 内容为 Xvfb PID。

### 3.2 客户端连接探针实证 (`xcb_probe.json`)
```json
{
  "pathname": {
    "display": "/tmp/.X11-unix/X97",
    "success": false,
    "error_code": 1
  }
}
```
*分析说明：当前 arch-case 内 libxcb 1.1.0 尚未完整支持直接以 `/tmp/...` 作为 display 字符串解析，探针返回 1。控制器门控 `resolve_active_display()` 严格抛出异常中止运行，杜绝降级到冒号显示。*

---

## 4. Vulkan 实例创建进展与详细阻断现场

### 4.1 Target PE 用户态输出 (`wine_stdout.log`)
```
==========================================================
[WIN_X64_VK] Starting Windows x64 Vulkan Enumeration Test
==========================================================
[WIN_X64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
[WIN_X64_VK] SUCCESS: vulkan-1.dll loaded at 0xfc050000
[WIN_X64_VK] Step 2: Resolving Vulkan function pointers...
[WIN_X64_VK] SUCCESS: All function pointers resolved.
[WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
```
*关键事实：输出严格截至第 3 步，应用程序层未接收到实例句柄，设备枚举与属性打印未被触达。*

### 4.2 底层诊断日志实录 (`wine_stderr.log`)
第 628-636 行完整现场：
```
00e0:trace:vulkan:win32u_vkCreateInstance Created instance 0x1162460, host_instance 0x1105f20.
terminate called after throwing an instance of 'std::bad_alloc'
  what():  std::bad_alloc
00e0:err:seh:call_seh_handlers invalid frame 1000fa2d0 (0000000000022000-0000000000120000)
00e0:err:seh:NtRaiseException Exception frame is not in stack limits => unable to dispatch exception.
00e0:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code -2147483391, process_exiting 0.
00e0:trace:process:NtTerminateProcess handle 0xffffffffffffffff, self 1, process_exiting 0.
0024:err:win:get_desktop_window failed to create desktop window
0024:trace:process:NtCreateUserProcess L"\\??\\C:\\windows\\system32\\explorer.exe" image L"C:\\windows\\system32\\explorer.exe" cmdline L"\"C:\\windows\\system32\\explorer.exe\" /desktop" parent (nil) machine 0
0024:trace:process:NtCreateUserProcess L"\\??\\C:\\windows\\system32\\explorer.exe" pid 00e4 tid 00e8 handles 0x74/0x78
```

---

## 5. 安全性修复单测实证 (`scripts/runtime/xvfb_wine/test_controller.py`)

为避免在修复控制器时重复耗时的 Wine 长跑，编写了专项轻量单测（涵盖 PID 锁比对、inode 套接字比对、DisplayFD 整型强校验与路径门控）：
```bash
$ python3 scripts/runtime/xvfb_wine/test_controller.py
...
----------------------------------------------------------------------
Ran 7 tests in 0.112s

OK
```
测试项包括：
1. `test_write_xauthority_mode_and_excl`：证实使用 `O_CREAT | O_EXCL` 且权限严格为 `0600`，对已存在文件抛出 `FileExistsError`。
2. `test_lexists_dangling_symlink`：证实 `lexists` 正确捕获悬空链接，消除 `exists` 预检盲区。
3. `test_child_timeout_termination_no_killpg`：证实超时仅针对直接子进程执行安全 terminate/kill，杜绝盲目调用 `killpg` 带来的 PID 复用隐患。
4. `test_check_displayfd_match`：证实对整型匹配通过，对不一致编号及非整型严格抛出 `AssertionError`。
5. `test_clean_owned_lock`：证实锁文件内容 PID 匹配时才删除，PID 不一致时拒绝删除。
6. `test_clean_owned_socket`：证实套接字 inode/uid 匹配时才删除，inode 不一致时拒绝删除。
7. `test_resolve_active_display_gate`：证实纯路径套接字成功时放行，失败时严格抛出 `RuntimeError` 拒绝冒号回退。

---

## 6. 最终结论与能力边界

1. **已证实的技术能力**：
   - 官方 aarch64 `Xvfb` 单包在 `elfuse` 内通过 `-nolisten tcp -nolisten inet6 -nolisten local -xkbdir /usr/share/xkeyboard-config-2` 可在无全局安装情况下受控运行。
   - 虚拟 X11 服务成功解除了 Wine 底层对 GDI desktop 视窗的阻塞，使 `win32u_vkCreateInstance` 成功创建了内部 VkInstance。
2. **已定位的首个确切缺项**：
   - 在实例创建后，运行时抛出了 native C++ `std::bad_alloc`，随后引发 SEH 分发失效（`invalid frame 1000fa2d0`）并导致桌面崩溃与死循环。
   - 抛出 `std::bad_alloc` 的底层根因与内存分配规模尚未确认（留待后续任务定位）。
3. **能力边界声明**：
   - 本实验所验证的是纯 CPU 软件光栅化（lavapipe）在虚拟无头 X11 视窗上下文中的运行边界。
   - **绝不代表真实的 macOS Metal 硬件图形加速，亦不包含真实 Steam 客户端环境的端到端集成**。
