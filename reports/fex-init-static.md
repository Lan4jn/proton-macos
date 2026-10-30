# 静态定位原版 FEX 初始化观测点报告 (Task-19)

## 1. 目标与二进制基线事实

- **调查对象**:
  1. `libarm64ecfex.so`:
     - 路径: `artifacts/public-proton/extracted/root/.local/share/Steam/steamapps/common/Proton Experimental (ARM64)/files/lib/wine/aarch64-unix/libarm64ecfex.so`
     - 大小: `71,760` bytes
     - SHA-256: `83c88a5dd3065d66cde1c9d653e6dc602eca2fe56227ed2974bf610f70a2b0fd`
     - 类型: ELF 64-bit LSB shared object, ARM aarch64, version 1 (SYSV), dynamically linked, not stripped
  2. `libarm64ecfex.dll`:
     - 路径: `artifacts/public-proton/extracted/root/.local/share/Steam/steamapps/common/Proton Experimental (ARM64)/files/lib/wine/aarch64-windows/libarm64ecfex.dll`
     - 大小: `5,365,760` bytes
     - SHA-256: `ca9b1de29555f27f7c56a161d35b95a1077f233a877765fa7aef610ab6bb8e5e`
     - 类型: PE32+ executable (DLL) (GUI) coff-arm64ec (含 ARM64 指令与 ARM64EC x86_64 entry thunks)

---

## 2. UnixLib 桥接导出与 Handlers 符号审计

`libarm64ecfex.so` 仅导出一个全局函数指针数组 `__wine_unix_call_funcs`：
- 地址: RVA `0x1fd80` (文件偏移 `0xfd80`，位于 `.data.rel.ro` 段)
- 项数: 8 个 unixcall 回调指针：
  - `[0] = 0x0db0`: `_ZL39FEXUnixLib_SetHardwareTSOControlHandlerPv`
  - `[1] = 0x0e60`: `_ZL49FEXUnixLib_SetKernelUnalignedAtomicControlHandlerPv`
  - `[2] = 0x0ea0`: `_ZL25FEXUnixLib_MadviseHandlerPv`
  - `[3] = 0x0ed0`: `_ZL28FEXUnixLib_SetVMANameHandlerPv`
  - `[4] = 0x0f20`: `_ZL32FEXUnixLib_GetSHMStatsVMAHandlerPv`
  - `[5] = 0x16c0`: `_ZL36FEXUnixLib_DeleteSHMStatsFileHandlerPv`
  - `[6] = 0x19f0`: `_ZL25FEXUnixLib_MapFileHandlerPv`
  - `[7] = 0x1a60`: `_ZL24FEXUnixLib_GetPIDHandlerPv`

---

## 3. 核心澄清：硬件 TSO 与 UnalignedAtomic 失败容错验证

### 3.1 Handler 返回值
- `FEXUnixLib_SetHardwareTSOControlHandler` (0x0db0):
  - 调用 `prctl(0x6d4d444c, ...)` (PR_GET_MEM_MODEL) 与 `prctl(0x4d4d444c, ...)` (PR_SET_MEM_MODEL)。
  - 当 `prctl` 返回非 0 时，返回 NTSTATUS `0xC00000BB` (`STATUS_NOT_SUPPORTED`)。
- `FEXUnixLib_SetKernelUnalignedAtomicControlHandler` (0x0e60):
  - 调用 `prctl(0x46455849, ...)` (PR_FEX_UNALIGNED_ATOMIC)。
  - 当 `prctl` 返回非 0 时，同样返回 NTSTATUS `0xC00000BB` (`STATUS_NOT_SUPPORTED`)。

### 3.2 DLL 侧 UnixLib 包装调用
- `FEX::Windows::UnixLib::TryEnableHardwareTSO` (RVA `0x1a1e40`):
  - 通过 `__wine_unix_call(handle, 0, &args)` 调用 handler 0。
  - 指令 `1801a1e88: cmp w0, #0; 1801a1e8c: cset w0, eq; ret`:
    - 成功 (NTSTATUS 0) 返回 `true` (1)。
    - 失败 (如 `0xC00000BB`) 返回 `false` (0)。
- `FEX::Windows::UnixLib::SetKernelUnalignedAtomicControl` (RVA `0x1a1eb0`):
  - 通过 `__wine_unix_call(handle, 1, &args)` 调用 handler 1。
  - 指令 `1801a1ef8: cmp w0, #0; 1801a1efc: cset w0, eq; ret`:
    - 成功返回 `true` (1)，失败返回 `false` (0)。

### 3.3 高层调用者：TSOHandlerConfig::TSOHandlerConfig (RVA `0x6170`)
位于 `ProcessInit` 流程中 (由 RVA `0x2020` 调用)：
```assembly
180006214: cmp   w8, #0x1
180006218: b.ne  0x180006250             ; 若未开启直接跳过
18000621c: bl    TryEnableHardwareTSO   ; 调用 TryEnableHardwareTSO
180006220: tbz   w0, #0x0, 0x180006250  ; 关键：若返回 0 (失败)，优雅分支跳过，继续执行！
180006224: ...                          ; 成功时配置 Context
180006250: ldrb  w9, [x19, #0x3]
180006260: orr   x0, x8, #0x1
180006264: bl    SetKernelUnalignedAtomicControl ; 调用 SetKernelUnalignedAtomicControl
180006268: tbz   w0, #0x0, 0x180006288  ; 关键：若返回 0 (失败)，分支跳转至正常返回退出点！
180006288: ldr   x30, [sp, #0x30]
18000628c: ldp   x19, x20, [sp, #0x20]
180006290: add   sp, sp, #0x40
180006294: ret                          ; 正常 return，不崩溃、不卡死、不 abort！
```
**确定事实结论**：
Task17 怀疑的“TSOEnabled=1 强制硬件 TSO 导致 init 停滞”是**错误的因果推断**。无论是 HardwareTSO 还是 UnalignedAtomic，底层 `prctl` 不支持时返回 `STATUS_NOT_SUPPORTED`，上层通过 `tbz w0, #0` 完全容错并跳过，进入常规软屏障与软件原子回退。

---

## 4. FEX 初始化完整调用链路 (ProcessInit 与 ThreadInit)

ARM64EC 规范的导出 Entry 位于 `.hexpthk` 段：
- `ProcessInit`: Entry thunk RVA `0x20e0b0` -> 真实实现 RVA `0x1780`
- `ThreadInit`: Entry thunk RVA `0x20e0e0` -> 真实实现 RVA `0x4290`
- `DllMain`: Entry thunk RVA `0x20e000` -> `DllMainCRTStartup` RVA `0x1a2630`

### 4.1 ProcessInit 核心阶段时序
1. **系统调用与模块探测** (RVA `0x17a0 - 0x1980`):
   - 解析 ntdll 导出的 Windows 系统调用编号 (`ParseWineSyscallNumbers`)。
   - `NtAllocateVirtualMemoryNative` (RVA `0x19f4`): 分配系统调用重定向表内存。
   - `NtProtectVirtualMemoryNative` (RVA `0x1a98`, `0x1ae4`, `0x1b30`): 设置代码页保护并修补入口。
2. **运行时基础设施就绪** (RVA `0x1b50 - 0x1b60`):
   - `FEX::Windows::InitCRTProcess()` (RVA `0x1a2650`): 初始化进程级 CRT 与堆。
   - `FEX::Windows::SetupThreadHandlers()` (RVA `0x1a13f0`): 注册线程异常和回调处理器。
   - `FEX::Windows::GetExecutableFilePath()` (RVA `0x1b60`): 获取当前宿主 PE 路径。
3. **配置与日志加载** (RVA `0x1cf8 - 0x1d78`):
   - `FEX::Config::LoadConfig(...)` (RVA `0x196a00`): 读取环境变量与配置文件。
   - 包含的配置项: `FEX_TSOENABLED`, `FEX_PORTABLE`, `FEX_SILENTLOG`, `FEX_OUTPUTLOG`, `FEX_DISKCACHE` 等。
   - `FEX::Windows::Logging::Init()` (RVA `0x1a1790`): 初始化 FEX 日志系统。
4. **UnixLib 桥接建立** (RVA `0x1ed4`):
   - `FEX::Windows::UnixLib::Init(HINSTANCE)` (RVA `0x1a1d00`):
     - 调用 `NtQueryVirtualMemory` (MemoryInformationClass 1000/1002) 定位 `libarm64ecfex.so`。
     - 解析 `__wine_unix_call_dispatcher` 与 `wine_server_handle_to_fd`。
     - 若成功，输出日志 `"FEX: Loaded FEXUnixLib"`。
5. **FEXCore 上下文创建** (RVA `0x1f04 - 0x1f10`):
   - `FEX::Windows::CPUFeatures::FetchHostFeatures` (RVA `0x19b9c0`)。
   - `FEXCore::Context::Context::CreateNewContext(HostFeatures)` (RVA `0x80c0`): 分配全局 JIT/AOT 翻译上下文、代码缓存以及内存管理器。
6. **内存追踪与硬件配置** (RVA `0x2020 - 0x20cc`):
   - `TSOHandlerConfig::TSOHandlerConfig` (RVA `0x6170`): 探测硬件 TSO，失败容错。
   - `InvalidationTracker::InvalidationTracker` (RVA `0x19f810`)。
   - `ImageTracker::ImageTracker` (RVA `0x19c380`)。
   - `CPUFeatures::CPUFeatures` (RVA `0x19c010`)。
   - 分配可执行内存并写入 `ret` (0xc3) 桩指令 (RVA `0x20f0 - 0x2124`)。

---

## 5. 建议 Task17 的关键观测点与断点策略

针对 Wine 载入 `libarm64ecfex.dll` 超时的排查，建议在以下 3 个关键函数入口/出口建立观测（GDB RSP 或 elfuse 日志）：

| 序号 | 目标函数 / 观察点 | 二进制偏移 (RVA) | 关键检测指标与预期行为 |
| :--- | :--- | :--- | :--- |
| **BP1** | `FEX::Windows::UnixLib::Init` | `libarm64ecfex.dll + 0x1a1d00` | 观察 `NtQueryVirtualMemory` (0x1a1d74) 是否成功获取 UnixLib 句柄；若返回非 0，则 UnixLib 不可用，后续跳过 Linux 宿主直通。 |
| **BP2** | `FEXCore::Context::Context::CreateNewContext` | `libarm64ecfex.dll + 0x80c0` | 观察 JIT 核心上下文创建期间的大块虚拟内存分配 (`NtAllocateVirtualMemory`)，验证是否触发之前发现的 `guest_range_hits_infra` 映射冲突或 1TB 边界溢出。 |
| **BP3** | `ProcessInit` 退出点 | `libarm64ecfex.dll + 0x2338` (或各正常/异常 `ret`) | 检查 `ProcessInit` 是否实际完成并返回到 Wine ntdll，还是卡在 `CreateNewContext` 内部死锁/futex 等待。 |

**环境配置建议**：
可通过设置环境变量 `FEX_SILENTLOG=0` 和 `FEX_OUTPUTLOG=stderr` 启用 FEX 内置的调试输出（对应 RVA `0x37757d` / `0x37758b`），避免黑盒猜测。
