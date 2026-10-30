# Proton macOS Lab 异常观测控制器与证据边界审查报告 (Task-43)

**报告日期**：2026-10-16  
**审查角色**：`lab-reviewer`（独立代码审查员）  
**关联任务**：`task-43`（预审唯一 Wine 异常观测的控制器与证据边界）  
**审查对象**：`task-42` 控制器与宿主运行器实现（`scripts/runtime/wine_badalloc/`）及实测执行证据（`logs/wine-badalloc/`）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**归档目录**：`logs/wine-badalloc-review/`  

---

## 一、 执行摘要与总体验收裁定

### 1. 核心技术事实与实测状态
1. **有限门禁与元数据核验状态**：
   - **ELFUSE_ABSOCK_BASE 隔离门禁**：宿主运行器 `run_wine_badalloc.py` 严格传入 `extra_env={"ELFUSE_ABSOCK_BASE": str(lab_root / ".s")}`；对已存在的 `.s` 执行 `os.path.islink` 拦截、当前 UID 严格核验与 0700 权限校验，排除了符号链接越界；客体控制器 `controller.py:preflight_absock_base()` 在启动 Xvfb 前于 guest 内部执行真实的抽象套接字双向 ping-pong 通信，断言中继正常且杜绝回退宿主 `/tmp`；
   - **Xvfb 监听器安全门禁**：Xvfb 命令行显式携带 `-nolisten tcp -nolisten inet6 -nolisten local`，完全关闭公网 TCP/inet6 监听；客体 X11 客户端通过经由 `lab/.s` 中继的抽象套接字（`DISPLAY=:97`）安全通信；
   - **Xauthority 凭据安全**：私有 Cookie 凭据文件通过 `os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600` 原子独占创建，绝不使用危险的 `-ac` 参数；
   - **DisplayFD 握手与精准资源清理**：Xvfb 通过 `-displayfd` 管道通知就绪并断言 `int(dnum) == 97`；退出清理时，严格比对 `.X97-lock` 文件内记录的 PID 是否与当前持有 `xvfb_proc.pid` 匹配，并核验 `/tmp/.X11-unix/X97` 套接字的 `(st_dev, st_ino, st_uid)` 属性，杜绝广扫宿主 `/tmp` 或误删未持有节点；
   - **进程生命周期与防止误杀**：全套进程树运行在已有 `run_isolated` 会话组内，**严禁 `os.setsid` / `preexec_fn=os.setsid`，严禁控制器直接调用 `os.killpg()`**，所有超时直接通过控制器持有的 Popen 对象直接发信号管理，杜绝 PID 复用误杀；
   - **LD_PRELOAD 传递机制有效**：由 guest 侧 `controller.py` 在拉起 Wine 时直接注入 `wine_env['LD_PRELOAD'] = str(tracer_so)`，成功避开宿主 `process.py` 对 `extra_env` 中 `LD_*` 变量的安全清除限制；
   - **关键资产哈希严格锁定**：
     - `elfuse-socket-derived`: `06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d`
     - 目标 Windows PE (`vk_enum_x64.exe`): `f77f9b8fa427120cc1488625f46f4cc05b0f1d2d2b22032f137cb81462cec412`
     - 拦截诊断库 (`libbadalloc_trace.so`): `6f034d0aaf3ff6796817d0eb947ace3e1aaa9d4fedeab139e6e6dc5efa0348d5`
   - **门禁定性声明**：上述仅核实了控制器静态代码、显式参数约束与有限环境元数据，不等于真实复杂生产运行中的全链路已完全证实。

2. **实测运行次数与执行状态事实（严禁虚报通过）**：
   - **实际运行次数事实**：本次实验实际共进行了 **3 次真实运行**（`run-2hb_cnux`、`run-tkhs_6ra` 与 `run-qgaia7if`），前 2 次因前置准备依赖缺项（缺 `user32.dll` / `ucrtbase.dll`）导致短 run 失败，偏离了“单次受控运行”的最初预设限制；仅第 3 次（`run-qgaia7if`）完整执行了 85s 观察窗口。
   - **分层退出状态独立解耦**：
     - 外层宿主控制器 / Supervisor：`exit: 0`（控制器脚本自身完成流程退出，不代表内部 Wine 执行成功）；
     - 内部 Wine 目标进程：`timed_out: True`，在达到 85.0s 最大观察窗口后被控制器发送 `SIGTERM` 强行终止，内部真实退出码为 `rc: -15`（`target_exit: null`）。
   - **Win32 推进与阻断事实**：
     - `wine_stdout.log` 实测推进至 Step 3：
       ```text
       [WIN_X64_VK] Starting Windows x64 Vulkan Enumeration Test
       [WIN_X64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
       [WIN_X64_VK] SUCCESS: vulkan-1.dll loaded at 0xfc050000
       [WIN_X64_VK] Step 2: Resolving Vulkan function pointers...
       [WIN_X64_VK] SUCCESS: All function pointers resolved.
       [WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
       ```
     - 停滞与终止：在调用 `vkCreateInstance` 后进程发生停滞，未生成 returned marker；
     - **调用栈捕获事实**：在 `wine_stderr.log`（344 行）中，**未观测到 `[BADALLOC_TRACE]`，也未观测到 `std::bad_alloc` 字符（匹配数均为 0）**。
     - **科学定性**：未观测到 trace 仅属实测未捕获，不证明底层 `__cxa_throw` 未发生，亦不证明拦截库已确认完全透明透明。严禁宣称 trace 捕获成功。

### 2. 审查裁定：【CHANGES REQUESTED（需修改）】
- **裁定理由**：控制器隔离门禁合规，但实验发生了 3 次运行偏离预设限制；且因客体控制器配置差异（`LD_LIBRARY_PATH` 遗漏 Wine Unix 驱动路径作为已证差异与候选诱因之一），导致 Wine 在 Step 3 发生停滞超时，实测未能捕获到 bad_alloc 原生调用栈。该缺项必须记录，禁止伪造成功，待后续新任务/修复后再行观测。

---

## 二、 关键缺陷与调用链阻断根本诱因分析

### 1. 实测日志与状态确证
对比 task-37 原有观测运行（`logs/xvfb-wine/run-1792122538/wine_stderr.log`）与当前运行（`run-qgaia7if/wine_stderr.log`）：
- **task-37 历史运行轨迹**：
  在调用 `vkCreateInstance` 后，Wine Unix 端驱动持续输出大量的实例函数探测日志（如 `00e0:trace:vulkan:win32u_vkCreateInstance ...`），直至第 628 行输出了底层 host 实例创建：
  ```text
  00e0:trace:vulkan:win32u_vkCreateInstance Created instance 0x1162460, host_instance 0x1105f20.
  terminate called after throwing an instance of 'std::bad_alloc'
    what():  std::bad_alloc
  ```
- **task-42 当前运行轨迹（`run-qgaia7if`）**：
  `wine_stderr.log` 在第 344 行仅输出了入口参数：
  ```text
  0024:trace:vulkan:vkCreateInstance create_info 0000000140004030, allocator 0000000000000000, instance 000000000011FF48
  ```
  随后完全停滞，85 秒内再无任何日志推进，直至外层控制器因观察窗口超时发送终止信号。

### 2. 差异对比与候选诱因分析（Comparative Analysis & Candidate Hypotheses）
对比两者的客体控制器代码发现：
- **task-37 控制器环境配置**（`scripts/runtime/xvfb_wine/controller.py:246`）：
  ```python
  wine_ld_path = f"{lavapipe_lib}:{wine_unix_lib}:{proton_bundle / 'files' / 'lib'}:{arch_lib}"
  ```
  显式包含了 `wine_unix_lib`（`fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix`）以及 `proton_bundle / 'files' / 'lib'`。在这些路径下存放着 Wine Unix 侧的驱动实现文件 `winevulkan.so`、`win32u.so` 及附属共享库。
- **task-42 控制器环境配置**（`scripts/runtime/wine_badalloc/controller.py:283`）：
  ```python
  wine_env["LD_LIBRARY_PATH"] = f"{lavapipe_lib}:/usr/lib"
  ```
  **遗漏了 `wine_unix_lib` 与 `proton_bundle / 'files' / 'lib'`**。
- **候选因果定性与科学边界**：
  上述 `LD_LIBRARY_PATH` 的缺失是目前**确证的已知配置差异与强候选诱因之一**。然而，必须秉持严密求证原则：
  1. 目前尚无在补齐该路径后能够 100% 成功复现 `bad_alloc` 的对照验证；
  2. 亦未在日志中捕获到 Unix `.so` 动态加载器显式的 `dlopen missing file` 错误行；
  3. 因此，**不能断言该配置缺失是导致进程在 Step 3 发生停滞的排他性根本原因**。它属于最高优先级的候选排查点，确切根因仍有待补全配置后的后续实验闭环证实。

---

## 三、 第一阶段：规格合规审查（Specification Review）

| 审查维度 | 规范约束 | 实测代码与证据溯源 | 判定 |
| :--- | :--- | :--- | :---: |
| **中继路径强隔离** | 必须通过 `ELFUSE_ABSOCK_BASE` 指定 `lab/.s` (0700)；严禁 fallback 到宿主 `/tmp`。 | `run_wine_badalloc.py:65-78` 严格执行 `lstat`、检查 `not islink`、核验 UID 与 0700 权限；`controller.py:preflight_absock_base()` 在 guest 内发起真实抽象 socket 通信断言通过。 | **PASS** |
| **Xvfb 监听器安全** | 严禁监听公网 TCP/inet6；仅限通过中继的抽象 transport 通信。 | `controller.py:214-216` 显式携带 `-nolisten tcp -nolisten inet6 -nolisten local`；`write_xauthority` 采用 `O_CREAT | O_EXCL` 0600 原子创建。 | **PASS** |
| **资源清理与防止抢占** | 启动前检查排他；退出时仅凭持有 PID 与精确 socket inode 清理，不广扫 `/tmp`。 | `controller.py:111-145` 使用 `clean_owned_lock` 校验 PID，使用 `clean_owned_socket` 校验 `(st_dev, st_ino, st_uid)`，精准清理自身节点。 | **PASS** |
| **进程生命周期与防止误杀** | 保持在 supervisor 会话组内；严禁 `setsid`，严禁控制器直接 `killpg`。 | `controller.py` 在 `Popen` 中未设置 `preexec_fn=os.setsid`；超时完全通过持有对象直接 `terminate()` / `kill()`，杜绝 PID 复用误杀。 | **PASS** |
| **诊断库注入通道** | 避免被宿主 `process.py` 清除；确保真实注入到客体 Wine 进程。 | 由 guest 侧 `controller.py:285` 直接在客体 Wine 环境中设置 `wine_env['LD_PRELOAD'] = str(tracer_so)`，有效绕过宿主 scrub 机制。 | **PASS** |
| **受控运行次数限制** | 最多唯一 1 次受控运行，严禁暗中反复重跑。 | 实际记录 3 次运行（前 2 次因依赖缺项短 run，第 3 次完整 85s 超时），偏离单次运行预设。 | **FAIL (偏离单次限制)** |
| **事实定性诚实度** | 未捕获到真实 trace 必须实事求是记录，严禁将内部状态伪称成功。 | 真实记录未捕获到 `[BADALLOC_TRACE]`，未到达底层异常点，严禁宣称 trace 成功。 | **PASS** |

---

## 四、 第二阶段：独立测试执行与证据矩阵（Test Matrix）

审查员对落盘的全部执行日志进行了只读审查与哈希断言核查：

| 运行编号 / 资产 | 核心配置与环境变量 | 退出状态与实测耗时 | 观测日志与关键特征 | 审计结论 |
| :--- | :--- | :---: | :--- | :---: |
| **`elfuse-socket-derived`** | 二进制哈希核验 | - | `06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d` | **PASS (哈希吻合)** |
| **`vk_enum_x64.exe`** | 目标 PE 哈希核验 | - | `f77f9b8fa427120cc1488625f46f4cc05b0f1d2d2b22032f137cb81462cec412` | **PASS (哈希吻合)** |
| **`libbadalloc_trace.so`** | 拦截诊断库哈希核验 | - | `6f034d0aaf3ff6796817d0eb947ace3e1aaa9d4fedeab139e6e6dc5efa0348d5` | **PASS (哈希吻合)** |
| **`run-2hb_cnux`** | 早期运行 1 | Exit 0 (目标 10)<br>耗时 52.86s | `wine_stdout.log`: LoadLibraryA("vulkan-1.dll") failed 126<br>`wine_stderr.log`: user32.dll not found | **PASS (前置缺项失败)** |
| **`run-tkhs_6ra`** | 早期运行 2 | Exit 0 (目标 10)<br>耗时 72.46s | `wine_stdout.log`: LoadLibraryA("vulkan-1.dll") failed 126<br>`wine_stderr.log`: ucrtbase.dll not found | **PASS (前置缺项失败)** |
| **`run-qgaia7if`** | **受控单次观测运行** | **Exit 0 (目标 None)**<br>**耗时 89.09s** | **`wine_stdout.log`**: Step 1/2 成功，Step 3 调用 `vkCreateInstance`<br>**`wine_stderr.log`**: 344 行，停在 `vkCreateInstance`<br>**`[BADALLOC_TRACE]`**: **0 匹配（未捕获到调用栈）** | **BLOCKED (路径遗漏导致调用停滞)** |

---

## 五、 审查结论与交付签字

1. **测试与证据总结**：
   - 控制器与宿主运行器的隔离防护、Preflight 门禁、原子凭据创建、子进程无 setsid/killpg 约束均已完全合规；
   - 依赖补齐后，Windows x64 PE 成功推进至 Step 3（`vulkan-1.dll` 成功载入，函数指针成功解析）；
   - 但因客体控制器遗漏了 Wine Unix 端核心驱动库路径（`wine_unix_lib` 与 `proton_bundle / 'files' / 'lib'`），导致在 Step 3 `vkCreateInstance` 发生阻塞停滞，最终在 85s 超时终止，未能触发底层的 `std::bad_alloc` 异常，**因此全程未产生 `[BADALLOC_TRACE]`**。
2. **最终审查判定**：**待修改 (CHANGES REQUESTED)**
   - 代码与门禁逻辑合格，但本轮实验**未能达成捕获 bad_alloc 原生调用栈的目标**。
   - 严禁宣布 trace 成功；该调用库路径缺项需在后续独立任务或修复轮次中补全后再行观测。
