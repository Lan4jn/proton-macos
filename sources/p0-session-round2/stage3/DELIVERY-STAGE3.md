# Stage 3 阶段交付记录 (DELIVERY-STAGE3.md)

## 1. 交付定位与状态声明
- **交付范围**：本文件为 Stage 3（Wine 依赖闭包分析、启动器加固与两运行时同 PE 失败基线对照）的阶段交付记录，新文件严格限定于 `sources/p0-session-round2/stage3/` 与 `logs/session-v2-round2/stage3/`，**绝对不覆盖已冻结的前轮成果（round1 RESULTS、round2 P0 REPORT.md、DELIVERY.md 均保持物理只读冻结）**。
- **任务状态**：
  - **task-9**：P0 基线试验已完整执行，保持 `in_progress` 等待审查员与 Lead 终审收口；
  - **task-15**：Stage 3 规格分析、闭包清单、启动器加固与实测对照已全部完成并闭环。
- **阶段核心定性**：
  - **Wine 运行功能门**：**严格保持 NOT_READY**（本任务目标不包括修复 Wine 复杂 Windows 业务层运行功能）；
  - **目标 PE 入口执行**：**严格判定为 UNKNOWN**（退出码为 29，失败发生在加载器与初始化阶段，因无 PE 专有 marker，绝不声称 PE 入口或主函数被执行）；
  - **两运行时对照基线**：**已成功建立受控失败基线比对（Failure Baseline Comparison）**，确证两款 runtime 在完全同等条件下的测得退出与错误类别完全一致。

---

## 2. 真实运行收据与归一化对照数据（原 raw 真实计算）
全部数据直接计算自真实运行物理收据：

| 场景 Run-ID | Runtime 角色 | Runtime SHA256 | 物理耗时 | P0 Runner / Target 退出码 | Wineserver 状态 / 回收码 | Wine PE 退出码 | 语义分类判定 | 宿主治理清理 |
|---|---|---|---|---|---|---|---|---|
| [p0-r2-wine-orig-s3v2](<../../../logs/session-v2-round2/p0-r2-wine-orig-s3v2/receipt.json>) | Original | `81803322...` | **18.11 秒** | 1 / 1 | READY (客体探针握手通过) / `-15` | **29** | `status: "UNKNOWN"` (`PE entry execution unverified; Wine exit 29`) | `complete: true` (ps 采样无活跃孤儿) |
| [p0-r2-wine-derived-s3v2](<../../../logs/session-v2-round2/p0-r2-wine-derived-s3v2/receipt.json>) | Derived | `3b146bbe...` | **18.91 秒** | 1 / 1 | READY (客体探针握手通过) / `-15` | **29** | `status: "UNKNOWN"` (`PE entry execution unverified; Wine exit 29`) | `complete: true` (ps 采样无活跃孤儿) |

- **归一化对照事实核验**（见 [comparison-validated.json](<../../../logs/session-v2-round2/stage3/comparison-validated.json>)）：
  - **测得退出与错误类别一致 (observed_exits_and_categories_match: true)**：
    1. 阶段 1：两款运行时的 Wineserver 均成功建立套接字监听并由静态客体探针通过非阻塞 `connect()` 真实握手就绪（`server_ready: true`）；
    2. 阶段 2：两者的 Wine 启动器均触发拉起 PE 进程并以退出码 **29** 受控终止（`wine_exit: 29`, `wineserver_exit: -15`）；
    3. 物理日志 (`stderr.log`) 表现完全一致：均报 `wineboot.exe` 初始化系统 DLL 失败 (`status c0000005`)、未实现 `syscall 374` 日志及 `c000001d` 异常；
    4. 局限性说明：**仅证明在此特定受测负载下两款 runtime 的观测退出与失败类别一致，绝不宣称两款 runtime 全功能等价，亦不宣称具备完全相同的内部深层根因**。

---

## 3. 依赖闭包分析与加固实物产物
1. **静态传递闭包规格**：
   - 依赖分析报告：[IMPORTS.json](<IMPORTS.json>)（SHA256 `5e16f73b...`）；
   - 闭包清单：[CLOSURE_MANIFEST_V2.json](<CLOSURE_MANIFEST_V2.json>)（SHA256 `d262d7be...`）；
   - 闭包规模：包含 1 PE + 1 wineboot + 12 DLLs + 3 NLS 表，共 17 项文件，总物理大小 **22.76 MB**，完全受控于 30MB 选定闭包预算内；
   - 成功消除项：相较于 Stage 2，物理引入 `cryptbase.dll` 与 `cryptsp.dll` 后，前次出现的 `advapi32.dll` 导出转发器断链错误完全消除。
2. **启动器与测试代码**：
   - Stage 3 v2 启动器：[wine_launcher_stage3_v2.py](<../../../scripts/runtime/session_v2_round2/stage3/wine_launcher_stage3_v2.py>)（SHA256 `5086855c...`）；
   - Stage 3 单元测试套件：[test_wine_launcher_stage3_v2.py](<../../../tests/session_v2_round2/stage3/test_wine_launcher_stage3_v2.py>)（SHA256 `a72f5749...`，4 项测试全绿 Exit 0）；
3. **全量阶段交付文件清单**：
   - 详见结构化清单：[stage3-final-manifest.json](<../../../logs/session-v2-round2/stage3-final-manifest.json>)。

---

## 4. 17 项受测源文件 100% 防篡改核验 (100% MATCH)
执行前后经实测比对，`CLOSURE_MANIFEST_V2.json` 所定义的全部 17 项受测源文件 SHA256 完好无损、零篡改。
