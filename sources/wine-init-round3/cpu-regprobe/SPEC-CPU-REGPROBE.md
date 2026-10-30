# Task-17: 只读 ARM64 PE CPU 注册表探针与 Wineboot 事件机制规格说明书 (SPEC-CPU-REGPROBE.md)

## 1. 任务背景与核心目标
在 Wine 运行期诊断中，`FEX::Windows::CPUFeatures::FetchHostFeatures`（RVA `0x19B9C0`）在读取注册表项 `HKEY_LOCAL_MACHINE\Hardware\Description\System\CentralProcessor\0` 失败后抛出非法指令异常 `c000001d (ForcedAssert hlt 1)`。
为了在**绝不修改注册表、绝不伪造键值、绝不 patch 二进制**的前提下客观测量该键在客体内部的真实存在性与属性值，本规范设计：
1. **只读 ARM64 PE 探针 (`cpu_regprobe.exe`)**：纯通过 Windows Native API（`NtOpenKey`、`NtQueryValueKey`、`NtWriteFile`）只读查询 `CentralProcessor\0` 的 11 个关键 QWORD 硬件属性，格式化输出至 stdout 并通过退出码区分（0=全部存在，2=键缺失，3=属性缺失）；
2. **源码级 `run_wineboot` 事件机制与 probe 独立运行机制设计**：查证 Wine 在什么条件下等待 `__wineboot_event`，设计既同属一个 Wineserver 会话、又能安全执行探针而不陷入 5 分钟死锁的合法无侵入方案。

---

## 2. 探针设计（TDD & Ponytail 最小完整实现）

### 2.1 探测目标与输出格式
- **目标注册表键**：
  `\Registry\Machine\Hardware\Description\System\CentralProcessor\0`
- **11 个必须核查的硬件属性 (QWORD/DWORD)**：
  1. `~MHz` (DWORD)
  2. `FeatureSet` (DWORD)
  3. `Component Information` (BINARY)
  4. `Configuration Data` (BINARY)
  5. `Identifier` (SZ)
  6. `ProcessorNameString` (SZ)
  7. `VendorIdentifier` (SZ)
  8. `CP 00000001` (QWORD - MIDR_EL1)
  9. `CP 00000002` (QWORD - CTR_EL0)
  10. `CP 00000003` (QWORD - ID_AA64PFR0_EL1)
  11. `CP 00000004` (QWORD - ID_AA64ISAR0_EL1)
- **输出协议 (标准输出 stdout)**：
  ```text
  CPU_REGPROBE_START
  KEY: \Registry\Machine\Hardware\Description\System\CentralProcessor\0 [FOUND|MISSING]
  VAL: ~MHz = 0x...
  ...
  CPU_REGPROBE_END status=0|2|3
  ```
- **退出码严格定义**：
  - `0`: 键与 11 项属性均存在且可读（SUCCESS）；
  - `2`: `CentralProcessor\0` 注册表键本身不存在（KEY_NOT_FOUND）；
  - `3`: 键存在但关键硬件属性缺失（VALUES_INCOMPLETE）；
  - `1`: 探针底层环境初始化或参数异常。

---

## 3. Wine 源码级 `run_wineboot` 事件机制与探针调度设计

### 3.1 源码机制确证 (`dlls/ntdll/unix/env.c:1585-1654`)
1. **事件创建与等待链条**：
   ```c
   // env.c:1606-1609
   init_unicode_string( &nameW, L"\\KernelObjects\\__wineboot_event" );
   status = NtCreateEvent( &handles[0], EVENT_ALL_ACCESS, &attr, NotificationEvent, 0 );
   if (status == STATUS_OBJECT_NAME_EXISTS) goto wait;
   ```
   - 当启动首个进程时，Wine 尝试创建命名的内核事件 `\KernelObjects\__wineboot_event`；
   - 若事件不存在（首个进程），Wine 调用 `NtCreateUserProcess` 派生 `wineboot.exe --init`，并将 `handles[1] = process`，然后进入 `wait` 标签页：
     ```c
     timeout.QuadPart = (ULONGLONG)5 * 60 * 1000 * -10000; // 5分钟!
     NtWaitForMultipleObjects( count, handles, WaitAny, FALSE, &timeout );
     ```
   - 若事件已存在（后续并发进程），跳转至 `wait`，等待先前的 wineboot 完成事件触发（`SetEvent(event)`）或超时。
2. **`wineboot` 何时触发该事件？**（`programs/wineboot/wineboot.c:1988`）：
   ```c
   // wineboot.c:1988
   WINE_TRACE("Operation done\n");
   SetEvent( event );
   return 0;
   ```
   `SetEvent` 位于 `wineboot.c` 的最后一行！
   在 `sort01` 中，`wineboot` 在执行中途遭遇 `SHGetFolderPathW` 死循环，**从未到达 Line 1988**，因此 `__wineboot_event` 从未被触发（处于 unsignaled 状态）。
   若在此状态下拉起新的 Wine 进程，新进程会在 `run_wineboot:1652` 处阻塞等待整整 5 分钟！

### 3.2 源码实证：`build_initial_params` 执行路径限制与无旁路假说
- **关键源码核查（`env.c:1921-1953`）**：
  查阅 `dlls/ntdll/unix/env.c:1926-1953`：对于任何没有 Windows 父进程的新独立进程（包括拉起 probe 的进程），`build_initial_params` 均**无条件调用 `run_wineboot(env, env_pos)`**！
  ```c
  // env.c:1950-1953
  set_env_var( &env, &env_pos, &env_size, bootstrapW, ARRAY_SIZE(bootstrapW), valueW );
  is_prefix_bootstrap = TRUE;
  env[env_pos] = 0;
  run_wineboot( env, env_pos ); // <--- 无条件调用！
  ```
  即使外部预置了 `WINEBOOTSTRAPMODE`，`build_initial_params` 内部依然会无条件执行 `run_wineboot`；而在 `run_wineboot` 内部，若 `__wineboot_event` 已经存在，将直接进入 `wait` 标签页等待事件触发或 5 分钟超时！
- **严肃结论（执行路径未解，拒绝大旁路）**：
  尝试通过环境变量跳过 `wineboot` 等待的假说被源码事实完全推翻；
  在 `wineboot` 因 `shell32` stub 未能触发 `SetEvent` 退出前，拉起任何独立 Windows PE 均不可避免地会被阻塞；
  因此：**不设计任何大型旁路或伪造事件方案，避免引入不合规的技术债；最优雅、最根本的解决路径是等待 task-22 产出最小真实的 `shell32` 闭包，让 `wineboot` 自然正常走完主流程并触发 `SetEvent`**。

---

## 4. 交付文件与当前边界
1. **探针源码产物**：`sources/wine-init-round3/cpu-regprobe/cpu_regprobe.c`（纯 Native API，严格只读）；
2. **规范文件**：`sources/wine-init-round3/cpu-regprobe/SPEC-CPU-REGPROBE.md`；
3. **安全与门禁**：
   - 不编写任何新 launcher，不运行真实 guest，不申请锁；
   - 保持只读规格状态，静候 task-22 最小 `shell32` 闭包结论。
