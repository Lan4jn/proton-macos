# Wineboot 硬件注册表键生成机制与 FEX HLT 因果链分析 (WINEBOOT-HARDWARE-REG-ANALYSIS.md)

## 1. 核心因果链确证（依据源码与实测日志）
1. **FEX `0x186610` HLT 停滞根因**：
   - 审查员已反汇编证实：`libarm64ecfex.dll + 0x186610` 是一处 `ForcedAssert(hlt 1)` 断言；
   - 触发原因：`FEX::Windows::CPUFeatures::FetchHostFeatures`（RVA `0x19B9C0`）调用内部 `OpenProcessorKey(0)` 尝试打开注册表项：
     `HKEY_LOCAL_MACHINE\Hardware\Description\System\CentralProcessor\0`
   - 因该键不存在，`OpenProcessorKey(0)` 返回 `NULL`，触发强制断言 `hlt 1`，向系统抛出非法指令异常 `c000001d`。
2. **硬件注册表键由谁创建？**
   - 研读 `programs/wineboot/wineboot.c`（L1956 与 L803-830）：
     该分支由 `wineboot.exe` 进程在初始化阶段调用 `create_hardware_registry_keys()` 显式创建：
     ```c
     RegCreateKeyExW( HKEY_LOCAL_MACHINE, L"Hardware\\Description\\System", 0, NULL,
                      REG_OPTION_VOLATILE, KEY_ALL_ACCESS, NULL, &system_key, NULL );
     ...
     RegCreateKeyExW( system_key, L"CentralProcessor", 0, NULL, REG_OPTION_VOLATILE,
                      KEY_ALL_ACCESS, NULL, &cpu_key, NULL );
     ...
     RegCreateKeyExW( cpu_key, L"0", 0, NULL, REG_OPTION_VOLATILE, KEY_ALL_ACCESS, NULL, &hkey, NULL );
     ```

---

## 2. 纯 Host 资料与实物核验结果

### 2.1 物理 `.reg` 文件核验（100% 证实为 VOLATILE 易失键）
- 检索目标：
  - 基础模板：`fixtures/runtime/pe-worker/pfx/*.reg`（`system.reg`, `user.reg`, `userdef.reg`）
  - 实测运行目录：
    - `logs/wine-init-round3/wine-init-r3-diag-01/work/r/prefix/*.reg`
    - `logs/wine-init-round3/wine-init-r3-sort-01/work/r/prefix/*.reg`
    - `logs/wine-init-round3/wine-init-r3-fex-01/work/r/prefix/*.reg`
- **实测结果**：在上述所有静态落盘的 `.reg` 文件中，**完全不存在 `CentralProcessor` 或 `Hardware\Description\System` 字段**！
- **机制解释**：`wineboot.c:813` 创建时显式传递了 **`REG_OPTION_VOLATILE`** 标志。
  根据 Windows / Wine 规范，VOLATILE 注册表项纯保存在当前 Wineserver 进程的内存会话树中，**绝不会被持久化刷入磁盘上的 `system.reg` 文件**。
  因此：**每次 Wineserver 启动新会话时，内存中的 `Hardware\Description\System` 分支必然为空，必须由该会话内首次启动的 `wineboot.exe` 动态创建！**

### 2.2 `wineboot` 主流程时序分析：`create_hardware_registry_keys` vs `SHGetFolderPathW`
在 `programs/wineboot/wineboot.c:1955-1975` 中，执行时序严格如下：
1. **时序 1 (Line 1955)**：`create_user_shared_data();`
2. **时序 2 (Line 1956)**：**`create_hardware_registry_keys();`**（在此处已经创建了 `CentralProcessor\0`！）
3. **时序 3 (Line 1957)**：`create_dynamic_registry_keys();`
4. **时序 4 (Line 1958)**：`create_computer_name_keys();`
5. **时序 5 (Line 1970)**：`update_wineprefix( update );`
6. **时序 6 (Line 1973)**：`create_volatile_environment_registry_key();`
   - **`SHGetFolderPathW` 调用的具体位置**：
     查阅发现，`wineboot.c` 内部的 `SHGetFolderPathW` 严格处于 Line 903 / 910 / 924（即函数 `create_volatile_environment_registry_key()` 内部）！
- **关键时序与运行时边界说明**：
  **`create_hardware_registry_keys()` 严格位于 `SHGetFolderPathW` 之前（仅代表源码调用顺序）**：
  - 在 `wine-init-r3-sort-01` 中，`kernelbase.dll` 成功返回 1 后，`wineboot.exe` 的 `main()` 确实开始执行，末尾日志出现 seh/stub 调用也证明流程已进入后续阶段；
  - **边界严格定性（禁止假定键已生成）**：源码调用顺序不等于运行时已成功生成键值！
    `create_hardware_registry_keys()` 内部依赖 `GetSystemFirmwareTable(RSMB)`、`malloc`、`RegCreateKeyExW` 等多步系统调用，而 `create_bios_processor_values` 更强依赖 SMBIOS processor 表项与 `thread_count`。若任何一步失败均会提前返回；
    在当前实测收据中，**尚未通过直接运行时探针观测到 `CentralProcessor\0` 的实际存在与键值内容**，因此绝不能断言该键在 `sort01` 中已必然生成，仅能证明执行路径已推进至该时序之后；
  - 随后在执行 `create_volatile_environment_registry_key` 时，调用 `SHGetFolderPathW` 遭遇 `shell32.dll` stub 缺失或高频 trace，导致在短短 14 秒内日志暴涨至 35MB 触发了 soft_threshold 守护终止！

---

## 3. 阶段结论与下一步策略
1. **因果与观察边界**：
   `diag01` / `fex01` 发生 `hlt 1` 与 `wineboot` 在 `kernelbase` 崩溃夭折、未能进入 `create_hardware_registry_keys` 时序存在高度时序相关性；但 `CentralProcessor\0` 键是否真实由 `wineboot` 在 guest 内生成仍需独立的只读探针（如 ARM64 `NtOpenKey` + `NtQueryValueKey`）进行实物测量；
2. **行动准则**：
   严格遵守 Lead 指示，**当前不修改任何 `.reg` 文件，不伪造 CPU 注册表，不执行任何 guest 试验**；
   等待审查员确立 `CentralProcessor\0` 必须的最小 CPU value contract（如 `Identifier`, `~MHz`, `FeatureSet` 等），后续通过纯只读探测建立客观基线。
