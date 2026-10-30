# Headless 显示服务的 Lab 隔离可行性核查报告

## 1. 核心结论与关键修正

1. **现有二进制现状**：`arch-case/usr/bin` 中 **仅存在 `Xwayland`**（大小 2,586,976 字节），`Xvfb`、`Xorg`、`weston` 均**不存在**；但基础 X11 客户端库（`libX11`, `libXext`, `libXfixes`, `libXrender`, `libXrandr`, `libpixman-1`, `libxkbcommon` 等）完整齐备。宿主 macOS 亦无全局 `Xvfb`/`Xorg`。
2. **Unix Domain Socket 真实映射与宿主短链接副作用分界（关键修正）**：
   - **套接字目标实体（Target Inode）**：在 `elfuse` 内通过 `net_sockaddr_to_mac()`（`sources/elfuse/src/syscall/net-absock.c:515-538`）走 `path_translate_at()`。`is_sysroot_backed_temp_path()`（`sources/elfuse/src/syscall/proc-state.c:812-826`）强制将 `/tmp` 与 `/var/tmp` 导向 `<sysroot>/tmp/`，**实际套接字文件与锁文件节点本身保存在 lab 内**。
   - **宿主短链接中继（Host Shortening Symlink）副作用**：
     - Darwin 内核的 `sockaddr_un.sun_path` 上限仅为 104 字节。当 lab 根目录较深或路径较长时，翻译后的宿主绝对路径若 `>= 104` 字节（`net-absock.c:558`），将无条件触发 `absock_shorten_path()`（`net-absock.c:360-400`）。
     - `net-absock.c:90-94`（`absock_dir_format`）**硬编码**格式化路径为 `/tmp/elfuse-absock-%llu`，**完全不读取宿主 `TMPDIR` 环境变量**。
     - **因此不能宣称“绝对 100% 不碰宿主 /tmp”**：虽然真实套接字在 sysroot，但 `elfuse` 会在宿主 `/tmp/` 创建 `0700` 私有目录 `/tmp/elfuse-absock-<namespace_id>/` 并在其中创建指向 sysroot 的短符号链接 `p<pid>-<hash>`。
     - **清理风险与副作用范围**：清理机制严格依赖 `atexit(absock_cleanup)`（`net-absock.c:130, 664-690`）。若进程因 SIGKILL、断电或异常崩溃退出，宿主 `/tmp/elfuse-absock-*` 目录及符号链接将会**孤立残留**。实验前后的清理机制必须纳入显式的宿主 `/tmp/elfuse-absock-*` 扫描与回收。
3. **Wine 用户驱动真实 Headless 能力与 Vulkan Desktop 停滞候选归因**：
   - 公开原版 ARM64 Proton 的 `files/lib/wine/aarch64-unix/` 下**仅有 `winex11.so`**，无 `winewayland.so`，无 `winemac.so`。
   - `win32u.so` 的降级驱动 `nodrv`（`nodrv_CreateWindow`）硬编码拒绝创建窗口（打印 `"Application tried to create a window, but no driver could be loaded."`）。
   - **停滞原因的静态候选分析**：`winevulkan.so` 在 `vkCreateInstance` 时调用 `d3dkmt_init_vulkan()` / `get_vulkan_gpus()` 枚举 GDI 显示适配器，静态调用链显示其会触发 `get_desktop_window()` 并拉起 `explorer.exe /desktop`。**需强调这属于强静态候选解释，非排他性已证实根因**；wineserver 会话初始化或特定线程上下文同步异常亦可能作为并发因素。
4. **验证范围定位与设计性质**：
   - Headless X11 服务（如 Xvfb）的作用仅限于向 `winex11.drv` 提供虚拟 X11 视窗上下文；
   - **Wine 与 Xvfb 的 DISPLAY 握手当前仅属于实验设计，尚未实际运行验证**，不能预设为“必然无缝”，须保留协议握手失败、权限或扩展缺失等风险预期。
   - 明确限制：Xvfb 仅用于探索 CPU 软件桌面连通性，**绝不代表真实 Metal 硬件渲染或 macOS 上的原生图形加速**。

---

## 2. 详细证据与代码行号核实

### 2.1 `arch-case` 及宿主 X11/Wayland 二进制清单

通过直接文件系统遍历比对：
- **`fixtures/runtime/arch-case/usr/bin/`**：
  - `Xwayland`: **存在**（`fixtures/runtime/arch-case/usr/bin/Xwayland`，2,586,976 字节）
  - `Xvfb`: **缺失**
  - `Xorg`: **缺失**
  - `weston`: **缺失**
- **宿主 macOS 环境**：
  - `which Xvfb`, `which Xorg`, `which weston`: 返回码 1，无宿主系统 X 服务。
  - `/opt/homebrew`: 无 `Xvfb`。
- **`fixtures/runtime/arch-case/usr/lib/` 依赖库状态**：
  - `libX11.so.6`, `libXext.so.6`, `libXfixes.so.3`, `libXrandr.so.2`, `libXrender.so.1`: **均已就绪**。
  - `libpixman-1.so.0`, `libxkbcommon.so.0`, `libxkbfile.so.1`: **均已就绪**。
  - `libwayland-client.so.0`, `libwayland-server.so.0`: **均已就绪**。

### 2.2 `elfuse` 的 `AF_UNIX` 与 `/tmp` 路径重映射机理及宿主副作用

在 `sources/elfuse`（以及 derived 各副本中一致）：

1. **套接字地址转换入口**：
   - 文件：`sources/elfuse/src/syscall/net-absock.c:506-576`
   - 函数：`net_sockaddr_to_mac(const uint8_t *linux_sa, uint32_t addrlen, bool create, struct sockaddr_storage *mac_sa)`
   - 逻辑：对于 `fam == LINUX_AF_UNIX` 且 `sun_path[0] != '\0'`（文件系统路径套接字），直接将 Linux `sun_path` 传入 `path_translate_at(LINUX_AT_FDCWD, guest_path, create ? PATH_TR_CREATE : PATH_TR_NONE, &tx)`。

2. **`/tmp` 路径强绑定 Sysroot 机制**：
   - 文件：`sources/elfuse/src/syscall/proc-state.c`
   - 函数：`is_sysroot_backed_temp_path(const char *path)`（行 812-826）：
     ```c
     static bool is_sysroot_backed_temp_path(const char *path)
     {
         if (path_prefix_match(path, "/tmp", 4) ||
             path_prefix_match(path, "/var/tmp", 8))
             return true;
         ...
     ```
   - 路径解析控制：`proc_resolve_sysroot_path_flags()`（行 1072-1074, 1215-1217）与 `proc_resolve_sysroot_create_path()`（行 1394-1402）：
     对于临时目录（`/tmp` 及 `/var/tmp`），`elfuse` 强制将其定位在 `<sysroot>/tmp/` 内部，禁用宿主回退（fallback）。
   - **结论（实体节点）**：`/tmp/.X11-unix/X<N>` 绑定的实际套接字 inode 以及 `/tmp/.X<N>-lock` 实际落在 `<sysroot>/tmp/`。

3. **长路径截断与宿主 `/tmp` 副作用（近端 92 / 354-400 分析）**：
   - 文件：`sources/elfuse/src/syscall/net-absock.c`
   - **触发条件（行 558）**：
     ```c
     if (strlen(host_path) >= sizeof(short_path)) { /* Darwin sun_path 为 104 字节 */
         if (absock_shorten_path(host_path, short_path, sizeof(short_path)) < 0)
             return absock_errno();
         host_path = short_path;
     }
     ```
     当前 lab 绝对路径较深（如 `/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/tmp/.X11-unix/X97` 为 88 字节；若前缀或子目录稍作扩展即很容易 `>= 104` 字节）。
   - **目录命名与硬编码（行 90-94）**：
     ```c
     static int absock_dir_format(char *out, size_t out_sz, uint64_t namespace_id)
     {
         return snprintf(out, out_sz, "/tmp/elfuse-absock-%llu",
                         (unsigned long long) namespace_id);
     }
     ```
     **关键事实**：此处为字面硬编码 `/tmp/elfuse-absock-%llu`，未读取 `getenv("TMPDIR")`。即便用户在宿主导出 `TMPDIR`，短链接目录依然落在宿主 `/tmp`。
   - **符号链接创建（行 360-400）**：
     `absock_shorten_path()` 在宿主 `/tmp/elfuse-absock-<namespace_id>/` 目录下创建短符号链接 `p<pid>-<hash>`，指向目标 `host_path`。`bind(2)` 穿透符号链接将真实套接字创建在 sysroot，但该符号链接驻留在宿主 `/tmp`。
   - **运行身份与权限**：由运行 `elfuse` 的当前用户身份创建，权限为 `0700`（`create_private_dir`）。
   - **清理与孤立风险**：由 `atexit(absock_cleanup)`（行 130，实现于行 664-690）负责 `unlink` 自身 mint 的符号链接并在空时 `rmdir` 目录。**若子进程被外部 SIGKILL、宿主超时杀进程或发生 crash，`atexit` 不会被执行，宿主 `/tmp` 将遗留未清理的 `elfuse-absock-*`**。

### 2.3 Wine 用户驱动分析与 Vulkan Desktop 停滞候选归因

1. **驱动库存目**：
   - 检查 `artifacts/public-proton/.../files/lib/wine/aarch64-unix/`：
     仅提供 `winex11.so`。
     不存在 `winewayland.so`，亦无 `winemac.so` 或专用 `null.so`。
2. **`win32u.so` 与 `nodrv` 行为**：
   - `win32u.so` 内导出了 `nodrv_CreateWindow`。
   - 当没有可用图形驱动（如 `DISPLAY` 缺失导致 `winex11.so` 的 `XOpenDisplay()` 返回 NULL）时，窗口创建直接硬拒绝：
     `Application tried to create a window, but no driver could be loaded.`
3. **`get_desktop_window()` 循环与 Vulkan 停滞候选因果**：
   - 在 task-35（`logs/windows-vulkan/run-w8dv4wns`）实测中，Windows x64 进程调用 `vkCreateInstance`。
   - 静态符号与调用链分析显示，`winevulkan.so` 初始化时通过 GDI/win32u 枚举适配器并触发 `get_desktop_window()`。
   - Wine 发现当前线程桌面未建立，遂调用 `NtCreateUserProcess` 启动 `explorer.exe /desktop`。
   - 由于缺失 X 服务或桌面环境异常，`explorer.exe` 失败退出，触发 `err:win:get_desktop_window failed to create desktop window`，并不断重试导致 100 秒超时。
   - **审慎判定**：GDI 枚举触碰桌面是目前的强静态候选解释，但在缺乏真实动态调试覆盖前，不能排除 wineserver 其它同步死锁或未知扩展协商失败等并存原因。

---

## 3. 隔离方案与下一阶段最小实验设计（纯只读规划）

### 3.1 方案选型评估

| 方案 | 外部依赖 | 对 host / tmp 影响 | elfuse 兼容性 | 评估结论 |
|---|---|---|---|---|
| **方案 A：引入独立 aarch64 `Xvfb` 单包至 lab** | 仅需官方 aarch64 `xorg-server-xvfb` 包解包到 lab（如 `fixtures/runtime/xvfb-derived`） | **有限影响**：套接字实体在 lab 内；若路径超长则在宿主 `/tmp` 产生受控短链接目录，可前置/后置显式清理 | 架构一致，直接对应 `winex11.so` | **首选候选** |
| **方案 B：利用现有 `Xwayland` + 极简 headless Wayland 合成器** | 现已有 `Xwayland`，但缺 `weston`/`cage`/`sway` | 需额外引入 Wayland 合成器 | 复杂，需管理双层套接字（Wayland + X11） | 不推荐（链路过长） |
| **方案 C：宿主 macOS 运行 XQuartz** | 需安装全局 XQuartz，监听宿主 `/tmp` | **有污染**：宿主套接字在 host `/tmp`，而 guest `elfuse` 不读 host `/tmp`，需反向链接 | 违反隔离规则与安全边界 | **坚决否决** |
| **方案 D：TCP 监听模式** | 开启 `-listen tcp` | **违反安全约束**（暴露未授权端口，违反无界监听禁令） | 无必要 | **坚决否决** |

### 3.2 最小动态探针实验设计与前置/后置清理规程

为了在后续获得批准的任务中安全验证桌面停滞问题，设计最小探针规程如下：

1. **组件获取原则**：
   - 遵照 task-33（lavapipe）规范，仅从官方发行源获取包含 `Xvfb` 独立可执行文件的官方二进制包（如 `xorg-server-xvfb`）。
   - 仅解包到 `fixtures/runtime/xvfb-isolated/`，**不安装全局包，不修改 `arch-case` 原始镜像**。
2. **完全隔离的启动命令行设计**：
   ```bash
   # 在 elfuse 监控下启动 Xvfb（受控后台进程，配置短超时）
   elfuse --sysroot <arch-case> \
     /fixtures/runtime/xvfb-isolated/usr/bin/Xvfb :97 \
     -screen 0 640x480x24 \
     -nolisten tcp \
     -nolisten inet6 \
     -displayfd 2
   ```
   - 参数关键点：
     - `:97`：选择非 0 显示号，避免命名冲突。
     - `-nolisten tcp -nolisten inet6`：**完全禁用网络监听，纯粹仅开放 Unix Domain Socket**。
3. **宿主 `/tmp` 短链接副作用防御与清理规程**：
   - **实验前**：检查宿主是否存在残留的 `/tmp/elfuse-absock-*`，并执行归属权校验后清理。
   - **实验中**：记录当前运行的 PID，监控 `/tmp/elfuse-absock-<namespace_id>/` 的创建与释放状态。
   - **实验后**：在测试 runner 的 `finally` 块中加入兜底回收逻辑，若进程非正常退出导致 `atexit` 未执行，显式移除当前进程所遗留的 `/tmp/elfuse-absock-*`。
4. **Wine 客户端环境配置与预期边界**：
   - 运行 Windows PE 或 Wine 时注入：`DISPLAY=:97`。
   - **保留未验证预期**：`DISPLAY=:97` 握手能否顺利消除 `explorer.exe /desktop` 挂起属于**待验证的候选方案**，实际执行中需观察 `XOpenDisplay` 结果与 `NtCreateUserProcess` 日志。
   - **明确非声明**：此项仅用于验证 Windows x64 PE 在 Wine 软件环境中的无头上下文生命周期，**不包含窗口上屏显示、不包含 Apple Metal 图形加速，亦不包含 Steam 客户端集成**。
