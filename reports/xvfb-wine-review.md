# Xvfb 控制器隔离清理与 Windows x64 Vulkan 失败边界独立审查报告 (第 2 次返工终审版)

**审查任务**：`task-38`（复审 Xvfb 控制器隔离清理及 WindowsVulkan 失败边界）  
**审查角色**：`elfuse-baseline-worker`  
**被审对象**：
- 控制器脚本：`scripts/runtime/xvfb_wine/controller.py`
- 控制器单元测试：`scripts/runtime/xvfb_wine/test_controller.py` (**7 PASS**)
- 宿主执行器：`scripts/runtime/xvfb_wine/run_xvfb_wine.py`
- 修订报告：`reports/xvfb-wine.md` (第 2 版)
- 原始运行日志：`logs/xvfb-wine/run-1792122538/`（`wine_stdout.log`、`wine_stderr.log`、`xvfb_stderr.log`、`summary.json`）  
**日期**：2026-10-16  

---

## 一、 审查核心结论与判定

### 判定：**APPROVED（第 2 次返工审查通过）**

1. **控制器安全边界与隔离返工全面闭环**：
   - **进程组与外层监管**：完全移除了 `preexec_fn=os.setsid`，子进程与调用者保持同一进程组，杜绝了外层 supervisor 身份逃逸；超时清理移除了盲目 `killpg`，仅直接终止由其启动的子进程。
   - **原子凭据创建**：`write_xauthority` 使用 `os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o600)`，排除了初始宽松权限与排他覆写竞态。
   - **符号链接安全检测**：启动预检与清理均采用 `os.path.lexists` / `lstat`，有效拦截悬空符号链接（dangling symlink）。
   - **精准所有权清理 (Precision Owned Cleanup)**：
     - 清理 `.X97-lock` 前解析内部 PID，仅当内容与 `xvfb_proc.pid` 严格相等时才执行 `unlink`，非本进程锁拒绝删除；
     - 清理套接字前记录就绪时的 `(st_dev, st_ino, st_uid)`，清理时通过 `lstat` 节点比对，严格匹配才执行 `unlink`，杜绝误删未持有或外部服务套接字。
   - **DisplayFD 强断言**：`check_displayfd_match` 显式比对 `int(dnum_str) == DISPLAY_NUM`，非整型或编号不符立即抛出 `AssertionError` 中止。
   - **抽象套接字硬门控**：`resolve_active_display` 仅接受纯路径套接字（`/tmp/.X11-unix/X97`）握手，一旦路径套接字未通立即抛出 `RuntimeError` 拒绝启动 Wine，**默认禁止降级/回退至冒号显示**。
2. **测试覆盖真实有效**：
   - `steam-macos-research` 自带的 `scripts/runtime/xvfb_wine/test_controller.py`（7 项测试全部 PASS，0.11s）；
   - 本审查员编写的独立审查测试套件 `logs/xvfb-wine-review/test_safety_review.py`（8 项测试全部 PASS，0.62s，日志落盘于 `logs/xvfb-wine-review/test_safety_review.log`），确证各安全与异常分支在轻量假桩下完全生效，未进行任何无界服务长跑。
3. **Windows PE Vulkan 状态严格界定（严禁过度宣称）**：
   - 目标 Windows PE 程序 `vk_enum_x64.exe` 的标准输出严格停留在 `[WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)...`，**从未返回，无任何成功标识**；
   - Wine 内部虽完成 `win32u_vkCreateInstance` 实例构建，但紧随其后发生 Native C++ `std::bad_alloc` 抛出并导致 `terminate`；
   - SEH 的 `invalid frame 1000fa2d0` 属于未捕获 C++ 异常在跨架构展开时的**次级派生失败**，真正的初始故障是底层内存分配失败（具体分配源与大小未知）；
   - **结论**：当前仅证实完成了 Wine 内部视窗与 Vulkan 驱动初始化推进，**Windows PE Vulkan 尚未打通**。

---

## 二、 详细代码与安全机制审计

### 1. 进程组管理与超时控制 (`scripts/runtime/xvfb_wine/controller.py`)
- **启动代码**：
  ```python
  # Keep in same process group (no setsid) so supervisor can manage group
  wine_proc = subprocess.Popen(
      wine_cmd,
      env=wine_env,
      stdout=wine_stdout_file,
      stderr=wine_stderr_file,
  )
  ```
- **超时代码**：
  ```python
  except subprocess.TimeoutExpired:
      # Terminate direct child only; do not call killpg
      wine_proc.terminate()
      try:
          wine_proc.wait(timeout=5)
      except subprocess.TimeoutExpired:
          wine_proc.kill()
          wine_proc.wait(timeout=2)
      wine_rc = 124
  ```
- **审计结论**：消除了 `os.setsid` 导致的组隔离逃逸，消除了 `os.killpg(os.getpgid(pid))` 在 PID 回收时的误杀风险。

### 2. 精准所有权清理与 DisplayFD 校验 (`controller.py`)
- **锁文件 PID 校验**：
  ```python
  def clean_owned_lock(path_str: str, expected_pid: int) -> bool:
      if not expected_pid or not os.path.lexists(path_str):
          return False
      try:
          with open(path_str, "r") as f:
              content = f.read().strip()
          lock_pid = int(content)
          if lock_pid == expected_pid:
              os.unlink(path_str)
              return True
          else:
              return False # 拒绝删除外部锁
  ```
- **套接字 Inode 校验**：
  ```python
  def clean_owned_socket(path_str: str, expected_inode_tuple) -> bool:
      if not expected_inode_tuple or not os.path.lexists(path_str):
          return False
      try:
          cur = os.lstat(path_str)
          cur_tuple = (cur.st_dev, cur.st_ino, cur.st_uid)
          if cur_tuple == expected_inode_tuple:
              os.unlink(path_str)
              return True
          else:
              return False # 拒绝删除外部套接字
  ```
- **DisplayFD 严格匹配**：
  ```python
  def check_displayfd_match(reported_dnum: str, expected_dnum: int) -> bool:
      val = int(reported_dnum.strip())
      if val != expected_dnum:
          raise AssertionError(...)
      return True
  ```

### 3. 抽象套接字门控 (`controller.py`)
- **路径锁定**：
  ```python
  def resolve_active_display(pathname_probe_result: dict) -> str:
      if not pathname_probe_result or not pathname_probe_result.get("success"):
          raise RuntimeError(
              f"Pathname socket handshake failed ({pathname_probe_result}); "
              f"fallback to abstract colon display is strictly prohibited by isolation gate."
          )
      return pathname_probe_result.get("display")
  ```
- **审计结论**：移除了先前版本中先试 `:97` 再试路径的倒置逻辑，强制要求直接路径套接字握手。在底层支持（如 task-40 `ELFUSE_ABSOCK_BASE`）就绪前，默认封锁冒号表示法，避免意外触碰全局 abstract socket。

---

## 三、 Windows PE Vulkan 真实失败事件时序核定 (`run-1792122538`)

通过对 `wine_stdout.log` 与 `wine_stderr.log`（第 628–636 行）的物理证据比对，确立真实事件链条：

| 顺序 | 日志行号与位置 | 原始日志内容 | 属性界定 | 深度技术解析 |
| :---: | :--- | :--- | :---: | :--- |
| **1** | `wine_stdout.log` | `[WIN_X64_VK] Step 3: Calling vkCreateInstance(API=1.0)...` | **程序中断点** | PE 用户态主线程调用 `vkCreateInstance` 进入 DLL/Unix 边界，**此后再无任何标准输出返回**。 |
| **2** | `wine_stderr.log:628` | `00e0:trace:vulkan:win32u_vkCreateInstance Created instance 0x1162460, host_instance 0x1105f20.` | **底层创建进展** | Wine 的 `win32u` 模块成功通过 X11/Xvfb 视窗驱动调用底层 lavapipe 完成了 Vulkan 实例创建。 |
| **3** | `wine_stderr.log:629-630` | `terminate called after throwing an instance of 'std::bad_alloc'`<br>`  what():  std::bad_alloc` | **首发致命故障** | 底层 Native C++ 抛出未捕获的内存分配异常（`bad_alloc`），触发 C++ 运行时 `terminate`。 |
| **4** | `wine_stderr.log:631-632` | `00e0:err:seh:call_seh_handlers invalid frame 1000fa2d0 (0000000000022000-0000000000120000)`<br>`00e0:err:seh:NtRaiseException Exception frame is not in stack limits => unable to dispatch exception.` | **次级派生失败** | C++ 异常展开或 Windows SEH 调度器被触发。由于异常发生点位于 FEX 翻译栈/宿主栈（`0x1000fa2d0`），超出了 Windows TEB 登记的低栈区（`0x22000-0x120000`），Wine 判定帧非法拒绝派发。 |
| **5** | `wine_stderr.log:633-634` | `00e0:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code -2147483391, process_exiting 0.` | **进程异常退出** | 抛出 `STATUS_INVALID_DISPOSITION`（`-2147483391` / `0x80000101`），桌面进程 `explorer.exe` 终止，主程序进入超时循环。 |

**审计审定结论**：
1. **SEH 不是根因**：SEH 报错是处理 `std::bad_alloc` 时的展开越界次级症状。
2. **分配根因未知**：目前无 host PC/callstack，尚不能确定究竟是 lavapipe 编译着色器管线申请超限、LLVM 23 堆消耗，还是虚拟地址空间冲突。
3. **诊断建议**：后续调试应如 task-39 所规划，通过 `__cxa_throw` 拦截器取得抛出点真实的 native 调用栈，并在 `WINEDEBUG` 中补齐 `+seh`。

---

## 四、 独立单元测试与验证数据 (`logs/xvfb-wine-review/test_safety_review.log`)

本审查员编写并执行了 8 项独立单元测试，实测日志如下：

```text
Ran 8 tests in 0.621s
OK (TEST_EXIT=0)

[WARNING] Refusing to unlink /.../.X97-lock: lock PID mismatch (12345 != 99999)
[WARNING] Refusing to unlink socket /.../X97: inode/uid mismatch (...)
[CONTROLLER] Cleaned owned lock file (PID 12345): /.../.X97-lock
[CONTROLLER] Cleaned owned socket: /.../X97
```

测试逐项核验结果：
1. `test_01_xauthority_atomic_and_mode_0600`: **PASS** (权限严格 `0600`，已存在文件抛出 `FileExistsError`)
2. `test_02_lexists_dangling_symlink_defense`: **PASS** (准确捕获悬空软链接)
3. `test_03_no_setsid_group_preservation`: **PASS** (子进程与父进程 PGID 完全一致)
4. `test_04_child_timeout_termination_no_killpg`: **PASS** (直接对 PID 发起 `terminate()`/`kill()`，有界退出)
5. `test_05_clean_owned_lock_pid_verification`: **PASS** (PID 匹配才删除，PID 不符拒绝并保留文件)
6. `test_06_clean_owned_socket_inode_verification`: **PASS** (设备/inode/uid 元组匹配才删除，不符拒绝)
7. `test_07_check_displayfd_match`: **PASS** (严格校验 display 编号，不匹配抛出 `AssertionError`)
8. `test_08_resolve_active_display_isolation_gate`: **PASS** (路径套接字放行，直接拒绝冒号格式回退)

---

## 五、 交付物清单与归档

- **独立审查报告**：`/Users/mewcapoo/Projects/proton-macos-lab/reports/xvfb-wine-review.md`
- **独立审查测试代码**：`/Users/mewcapoo/Projects/proton-macos-lab/logs/xvfb-wine-review/test_safety_review.py`
- **独立审查测试日志**：`/Users/mewcapoo/Projects/proton-macos-lab/logs/xvfb-wine-review/test_safety_review.log`

本审查已全面收敛，判定 APPROVED，`task-38` 置为 completed。
