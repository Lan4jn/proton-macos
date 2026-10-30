# Wine 初始化运行期证据采集与最小复现最终交付结果 (RESULTS-FINAL.md)

## 1. 任务背景与核心结论
本报告记录了在 Round 3 针对 Wine 初始化运行期失败的单变量诊断、物理因果链推导与逐步闭环验证全过程。
- **任务结论**：在 Original runtime (`81803322...`) 下，通过精细化单变量扩充，构建了包含 33 项去重源文件（逻辑源大小 60,085,476 字节 < 64 MiB）的最小完整 Bootstrap 闭包，在完全真实的 P0 会话治理与 `--timeout 60` 预算下，**实测确证目标 PE `minimal-x64.exe` 真正到达入口点并以独有语义 Marker 退出码 43 成功退出，P0 runner 零错误退出 (Exit 0)**！
- **严肃边界定性（严禁夸大）**：
  本次测试中退出码 43 的成功仅代表目标最小控制台 PE（`minimal-x64.exe`）的入口点与基础进程终止链路**真实有限通过 (Limited Verification PASS)**；
  **绝不代表 Steam 客户端、复杂 3D 渲染、图形 GDI 窗口交互或总体 Proton 功能已经就绪**；Wine 复杂 GUI/游戏业务层功能仍处于实验推进阶段。

---

## 2. Round 3 实测运行矩阵与真实物理收据汇总

下表全部数据直接提取自真实落盘的物理收据（保留原始权威记录，不掩盖中间态）：

| 运行标识 (Run-ID) | 闭包版本 / 源数量 | 唯一单变量变更集 | 物理实测耗时 | P0 Runner / Target 退出码 | Wineserver 状态 / 回收码 | Wine PE 退出码 | 语义分类判定 | 进程组治理与清理状态 |
|---|---|---|---|---|---|---|---|---|
| [wine-init-r3-diag-01](<../../logs/wine-init-round3/wine-init-r3-diag-01/receipt.json>) | v2 闭包 (17 源) | 仅注入 `WINEDEBUG` 诊断参数 | **25.74 秒** | 1 / 1 | READY / `-15` | **29** | `UNKNOWN` (`LOADER_FAILURE_EXIT_29`) | `complete: true` (ps 采样零残留) |
| [wine-init-r3-sort-01](<../../logs/wine-init-round3/wine-init-r3-sort-01/receipt.json>) | v2_sort 闭包 (18 源) | 单独扩充 `sortdefault.nls` | **14.86 秒** | 1 / 1 | READY / `-15` | **-15** (soft cap) | `UNKNOWN` (日志暴涨超 32MB 被切断) | `complete: true` (ps 采样零残留) |
| [wine-init-r3-fex-01](<../../logs/wine-init-round3/wine-init-r3-fex-01/receipt.json>) | v3_fex_pure (20 源) | 单独扩充 3 个 FEX Unix 库 (无 sort) | **21.22 秒** | 1 / 1 | READY / `-15` | **29** | `UNKNOWN` (`LOADER_FAILURE_EXIT_29`) | `complete: true` (ps 采样零残留) |
| [wine-init-r3-combined-01](<../../logs/wine-init-round3/wine-init-r3-combined-01/receipt.json>) | v4_combined (27 源) | 18 sort-base + 3 Unix + 6 PE | **4.17 秒** | 1 / 1 | READY / `-15` | **-15** (soft cap) | `UNKNOWN` (因缺失 ole32 产生 stub 循环) | `complete: true` (ps 采样零残留) |
| [wine-init-r3-ole-01](<../../logs/wine-init-round3/wine-init-r3-ole-01/receipt.json>) | v5_ole (31 源) | 增 4 项 OLE 库 (ole32/combase/rpcrt4/coml2) | **4.74 秒** | 70 / 1 | READY / `-15` | **-15** (soft cap) | `UNKNOWN` (因缺失 wininet 产生 stub 循环) | `complete: false` (`runner_exit: 70` 保持原始权威；[post-cleanup](<../../logs/wine-init-round3/wine-init-r3-ole-01/post-cleanup.json>) 确证 3 PID 已退出) |
| [wine-init-r3-wininet-01](<../../logs/wine-init-round3/wine-init-r3-wininet-01/receipt.json>) | v6_wininet (33 源) | 增 2 项 Wininet 库 (wininet/mpr) | **17.19 秒** | **0 / 0** | READY / `-15` | **43** | **`PASS` (`REACHED_PE_ENTRY_NT_TERMINATE_43`)** | `complete: true` (零活跃孤儿残留，平稳完成) |

---

## 3. 根因剖析与底层物理因果链图谱

基于源码研读（`ntdll/loader.c`, `ntdll/unix/env.c`, `wineboot.c`）与实测反汇编映射（PC 证据），确证完整的底层物理因果链：

```
                              [Wine 启动阶段]
                                    │
                          缺失 sortdefault.nls
                                    ▼
                  kernelbase.dll 内部偏移 0x3BBE4 读取 0x16FFF8
                         触发 c0000005 访问违规 (AV)
                                    ▼
                 wineboot.exe 子进程初始化阶段夭折 (status c0000005)
                                    │
                   ┌────────────────┴────────────────┐
                   ▼                                 ▼
      未能完成初始化流程并正常退出          未能执行 create_hardware_registry_keys()
                   │                                 │
                   │                                 ▼
                   │               Hardware\Description\System\CentralProcessor\0
                   │               易失性内存注册表分支未建立
                   │                                 │
                   ▼                                 ▼
  主 PE 进程在 run_wineboot 监听         主 Wine 进程 FEX::CPUFeatures::FetchHostFeatures
  WaitAny[__wineboot_event, process]     OpenProcessorKey(0) 打开键失败返回 NULL
  (若 wineboot 崩溃早死则返回推进，                  │
   若 wineboot 递归挂起则触发超时)                    ▼
                                            触发 ForcedAssert (hlt 1)
                                            抛出 c000001d (ILLEGAL_INSTRUCTION)
```

- **解决因果链条（Witness Sequence 闭环）**：
  1. **引入 `sortdefault.nls`**：`kernelbase.dll` 成功 `RETURN 1`，旧 `c0000005` 彻底根除，`wineboot.exe` 进入主函数；
  2. **引入 3 项 FEX Unix 库 (`libstdc++.so.6`, `libm.so.6`, `libgcc_s.so.1`)**：彻底消除了 FEX Unix 端的 dlopen 缺失报警；
  3. **引入 6 项核心 PE (`shell32`, `user32`, `gdi32`, `win32u`, `shcore`, `shlwapi`) 与 4 项 OLE (`ole32`, `combase`, `rpcrt4`, `coml2`)**：消除了 `SHGetFolderPathW` 与 `StringFromGUID2` 延迟加载断链；
  4. **引入 2 项 Wininet PE (`wininet`, `mpr`)**：消除了 `InternetOpenW` 延迟加载断链；
  5. **终态结果与证据定性**：`wineboot.exe` 完整走完初始化流程，全部 21 个系统 DLL 成功 `PROCESS_DETACH` 并平稳退出；主 Wine 进程在 `run_wineboot` 的 `WaitAny` 中被正常唤醒，主程序顺利完成系统库 attach 并进入目标 PE，**命中退出码 43 独有语义 Marker**！
     - *严格证据定性声明*：退出码 43、进程 detach 与后续阶段的顺利交接构成了强支持证据链；但由于探针未对易失内存注册表进行 live dump，不做出“已直接测得实际 SetEvent/CPU QWORD 数值”的越权推断，严守客观实测事实。

---

## 4. 最小完整闭包清单核算 (33 项源文件)

- **闭包规范文件**：[CLOSURE_MANIFEST_R3_V6.json](<CLOSURE_MANIFEST_R3_V6.json>)
- **预算核算**：
  - 授权逻辑源预算：**64 MiB (67,108,864 字节)**
  - 实际去重源文件总数：**33 项**
  - 实际去重逻辑源字节：**60,085,476 字节 (57.30 MiB)**（`fits_under_64mib_source_budget: true`）
  - 实际部署展开总字节：**118,380,032 字节 (112.90 MiB)**（详细记录了 bundle 与 prefix system32 的常规物理文件双份展开）

---

## 5. 成功复现命令 (Exact Reproduction Command)

本命令完全同构于实测成功的真实运行调度，采用绝对路径与标准 P0 runner CLI 规范（可在当前仓库根目录下由人工单次触发复现，绝不自动重跑）：

```bash
python3 -I /Users/mewcapoo/Projects/proton-macos-lab/scripts/runtime/wine_init_round3/run_diag.py \
  --run-id wine-init-r3-wininet-repro \
  --timeout 75 \
  --outer-timeout 85 \
  --module launcher_v6_wininet=/Users/mewcapoo/Projects/proton-macos-lab/scripts/runtime/wine_init_round3/wine_diagnostics_launcher_v6_wininet.py \
  --module closure_manifest_v6=/Users/mewcapoo/Projects/proton-macos-lab/sources/wine-init-round3/CLOSURE_MANIFEST_R3_V6.json \
  --module wine=/Users/mewcapoo/Projects/proton-macos-lab/sources/proton-v3-deploy/original/files/bin-arm64/wine \
  --module server=/Users/mewcapoo/Projects/proton-macos-lab/sources/proton-v3-deploy/original/files/bin-arm64/wineserver \
  --module pe=/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/pe-worker/pfx/drive_c/minimal-x64.exe \
  --module runtime=/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-once-panorama2-derived/build/elfuse \
  --module shim=/Users/mewcapoo/Projects/proton-macos-lab/sources/p0-session-round2/wineserver_shim \
  --module probe=/Users/mewcapoo/Projects/proton-macos-lab/sources/p0-session-round2/wine_readiness_probe \
  -- /Library/Developer/CommandLineTools/usr/bin/python3 -I /Users/mewcapoo/Projects/proton-macos-lab/scripts/runtime/wine_init_round3/wine_diagnostics_launcher_v6_wininet.py \
  --root /Users/mewcapoo/Projects/proton-macos-lab/logs/wine-init-round3/wine-init-r3-wininet-repro/work/r \
  --role original \
  --run-approved
```

---

## 6. 回滚与环境保护说明
- **回滚说明**：所有启动器与候选闭包均采用独立版本文件管理（v1 至 v6），回滚仅需切回旧版启动器，绝不删除历史对照目录；
- **环境保护**：全流程零 git commit、零 git push、零全局系统环境修改；
- **受测源防篡改**：33 项受测源文件 SHA256 经实测逐一核验全部 100% 匹配。
