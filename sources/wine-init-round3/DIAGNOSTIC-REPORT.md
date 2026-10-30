# Wine Init Round 3 单变量运行期诊断物理证据报告 (DIAGNOSTIC-REPORT.md)

## 1. 运行与治理审计概览
- **运行唯一标识**：`wine-init-r3-diag-01`
- **运行收据路径**：[receipt.json](<../../logs/wine-init-round3/wine-init-r3-diag-01/receipt.json>)
- **启动器结果收据**：[wine-launcher-result.json](<../../logs/wine-init-round3/wine-init-r3-diag-01/work/r/work/wine-launcher-result.json>)
- **诊断日志原始路径**：[stderr.log](<../../logs/wine-init-round3/wine-init-r3-diag-01/stderr.log>)
- **运行时与配置**：
  - Runtime: Original (`8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda`)
  - 启动器：`scripts/runtime/wine_init_round3/wine_diagnostics_launcher.py` (SHA256 `6d32ab2c...`)
  - 闭包清单：`sources/p0-session-round2/stage3/CLOSURE_MANIFEST_V2.json` (SHA256 `d262d7be...`, 17 项文件)
  - 唯一单变量注入：`WINEDEBUG=+timestamp,+pid,+module,+seh,+loaddll`
- **核心治理指标**：
  - P0 宿主治理：`runner_exit: 1`, `target_exit: 1`, `inner_timed_out: false`, `outer_timed_out: false`
  - 物理实测耗时：**25.74 秒**（远在 P0 inner 75s / outer 85s 预算内）
  - 日志软阈值监控：实际产生 `55,427` 字节（约 54 KiB），远未超过 32 MiB soft_threshold（`exceeded: false`）
  - 进程组清理：`cleanup.complete: true` (`signals: [SIGTERM, SIGKILL]`, `worker_exit: -9`)，终态 ps 采样零孤儿残留。

---

## 2. 线程解耦与崩溃点精准定位证据 (严格客观日志事实)

### 2.1 线程 0030：`wineboot.exe` 子进程崩溃精准定位 (`c0000005`)
诊断日志证实，`loader_init` 报错并非发生在 wineboot 主体，而是严格定位在 **`kernelbase.dll` 的 `PROCESS_ATTACH` 入口点执行阶段**：
1. **调用前序**：
   ```text
   218709.680:002c:0030:trace:module:process_attach (L"ntdll.dll",000000000011FC70) - START
   218709.680:002c:0030:trace:module:MODULE_InitDLL (000000DFFFE30000 L"ntdll.dll",PROCESS_ATTACH,000000000011FC70) - CALL
   218709.680:002c:0030:trace:module:MODULE_InitDLL (000000DFFFE30000,PROCESS_ATTACH,000000000011FC70) - RETURN 1
   218709.680:002c:0030:trace:module:process_attach (L"ntdll.dll",000000000011FC70) - END
   218709.680:002c:0030:trace:module:process_attach (L"kernel32.dll",000000000011FC70) - START
   218709.680:002c:0030:trace:module:process_attach (L"kernelbase.dll",000000000011FC70) - START
   218709.680:002c:0030:trace:module:MODULE_InitDLL (000000DFFF960000 L"kernelbase.dll",PROCESS_ATTACH,000000000011FC70) - CALL
   ```
   - `ntdll.dll` 初始化成功返回 1；
   - `kernel32.dll` 在递归解析依赖时优先调用 `process_attach(kernelbase.dll)`；
   - loader 正式进入 `kernelbase.dll` 的入口点；
2. **异常捕获与 PC 寄存器**：
   ```text
   218709.682:002c:0030:warn:seh:dispatch_exception backtrace: --- Exception 0xc0000005.
   218709.682:002c:0030:trace:seh:dispatch_exception code=c0000005 (EXCEPTION_ACCESS_VIOLATION) flags=0 addr=000000DFFF99BBE4
   218709.682:002c:0030:trace:seh:dispatch_exception  info[0]=0000000000000000
   218709.682:002c:0030:trace:seh:dispatch_exception  info[1]=000000000016FFF8
   218709.682:002c:0030:trace:seh:dispatch_exception  pc=000000dfff99bbe4  sp=000000000011f400  lr=000000dfff99bb30  fp=000000000011f8c0
   ```
   - 崩溃类型：访问违规 (`EXCEPTION_ACCESS_VIOLATION`)，尝试读取地址 `0x16FFF8`；
   - 故障程序计数器：`pc = 0x000000dfff99bbe4`；
3. **调用栈展开 (Virtual Unwind)**：
   ```text
   218709.682:002c:0030:warn:seh:virtual_unwind backtrace: 000000DFFF99BBE4: L"kernelbase.dll" + 000000000003BBE4.
   218709.682:002c:0030:warn:seh:virtual_unwind backtrace: 000000DFFF9B0AA4: L"kernelbase.dll" + 0000000000050AA4.
   218709.682:002c:0030:warn:seh:virtual_unwind backtrace: 000000DFFFE7405C: L"ntdll.dll" + 000000000004405C.
   ```
4. **终态处理与回滚**：
   `MODULE_InitDLL(kernelbase.dll)` 捕获异常后返回 `0`，loader 随后触发 `PROCESS_DETACH` 清理并打出终态错误：
   ```text
   218709.682:002c:0030:warn:module:process_attach Initialization of L"kernelbase.dll" failed
   218709.682:002c:0030:err:module:loader_init Initializing system dll for L"C:\\windows\\system32\\wineboot.exe" failed, status c0000005
   ```
   **结论**：`wineboot.exe` 的 `c0000005` 崩溃点确凿定位为 **`kernelbase.dll` 内部偏移 `0x3BBE4` 处的内存读取违规**。

---

### 2.2 线程 0028：主 Wine PE 进程崩溃精准定位 (`c000001d`)
诊断日志证实，线程 `0028` 是拉起目标 PE `minimal-x64.exe` 的主 Wine 进程，其崩溃与线程 `0030` 相互独立：
1. **调用前序与映射**：
   ```text
   218709.838:0024:0028:trace:module:map_image_into_view mapping PE file L"\\??\\C:\\minimal-x64.exe" at 0x140000000-0x140003000
   218725.952:0024:0028:trace:module:map_image_into_view relocating L"\\??\\C:\\windows\\system32\\ntdll.dll" dynamic base 180000000 -> dfffe30000
   218725.964:0024:0028:trace:module:load_apiset_dll loaded L"\\??\\C:\\windows\\system32\\apisetschema.dll" apiset at 0x130000
   218726.009:0024:0028:trace:module:map_image_into_view mapping PE file L"\\??\\C:\\windows\\system32\\libarm64ecfex.dll" at 0xdfffa40000-0xdfffe19000
   ```
2. **伴随的 Unix 动态库缺失**：
   ```text
   218726.304:0024:0028:warn:module:load_builtin_unixlib failed to load "/wine/lib/wine/aarch64-unix/libarm64ecfex.so": libstdc++.so.6: cannot open shared object file: No such file or directory
   ```
3. **异常捕获与 PC 寄存器**：
   ```text
   218726.325:0024:0028:warn:seh:dispatch_exception backtrace: --- Exception 0xc000001d.
   218726.325:0024:0028:trace:seh:dispatch_exception code=c000001d (EXCEPTION_ILLEGAL_INSTRUCTION) flags=0 addr=000000DFFFBC6610
   218726.325:0024:0028:trace:seh:dispatch_exception rip=000000dfffbc6610 rsp=000000000011c410 rbp=000000000011eea8 eflags=00000203
   ```
   - 崩溃类型：非法指令 (`EXCEPTION_ILLEGAL_INSTRUCTION`)；
   - 故障指令指针：`rip = 0x000000dfffbc6610`；
4. **调用栈展开 (Virtual Unwind)**：
   ```text
   218726.325:0024:0028:warn:seh:virtual_unwind backtrace: 000000DFFFBC6610: L"libarm64ecfex.dll" + 0000000000186610.
   218726.325:0024:0028:warn:seh:virtual_unwind backtrace: 000000DFFFBDBBA8: L"libarm64ecfex.dll" + 000000000019BBA8.
   ```
   **结论**：主 Wine 进程的终态异常 `c000001d` 确凿发生于 **`libarm64ecfex.dll` 内部偏移 `0x186610` 处的非法指令**，导致未处理异常终止，进程退出码 29。

---

## 3. 门控与阶段结论
1. **目标 PE 入口执行状态**：
   退出码为 29，未产生退出码 43 独有 Marker；失败发生在 `kernelbase.dll`（线程 0030）与 `libarm64ecfex.dll`（线程 0028）的初始化与桥接阶段；
   **严格维持 UNKNOWN 定性（`reason: "PE entry execution unverified; Wine exit 29"`）**。
2. **Wine 运行功能门**：**严格保持 NOT_READY**。
3. **17 项受测源文件防篡改核验**：运行后逐一实测比对，SHA256 全部 100% 吻合，零篡改。
4. **独占锁状态**：真实 guest 执行锁已立即归还，无活跃孤儿残留。
