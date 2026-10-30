# 新旧 Runtime 组合原版 Proton 启动器对比实验审计报告 (task-30 复审修订版)

**实验日期**：2026-10-16  
**执行员**：`proton-package-worker`  
**关联任务**：`task-30`（对照新旧 runtime 下的原 Proton 启动器超时差异）  
**宿主环境**：Apple Silicon macOS 27.0.1 (Build 26A434, arm64, Rosetta 2 可用, 磁盘可用空间 246 GiB)  
**交付物路径**：
- 对比执行器：`scripts/runtime/proton_contrast/run_contrast.py`
- 独立快照前缀：
  - 旧候选前缀：`fixtures/runtime/proton-contrast/old/compat/pfx`
  - 新候选前缀：`fixtures/runtime/proton-contrast/new/compat/pfx`
- 结构化对比日志：`logs/proton-contrast/`
  - `contrast_report.json` (自动汇总的两端指标对比)
  - `run-ad1vfc__` (Old Candidate 运行日志，退出码 0，STDOUT: `X64_FEX_OK`，耗时 41.72s)
  - `run-x0q7o2qx` (New Lifecycle 运行日志，退出码 0，STDOUT: `X64_FEX_OK`，耗时 46.05s)
  - `run-b9saf_he` (执行员在 `lead-proton/compat` 上的追加跨前缀探测，退出码 0，STDOUT: `X64_FEX_OK`，耗时 60.30s)

---

## 1. 核心结论与执行摘要 (Executive Summary)

1. **核心审计结论：当前受控样本未复现回归，新 Proton 链有绿灯证据**：
   - 本次实验在严格控制变量的前提下，使用同源独立快照前缀（相对链接已 100% 修复为绝对路径），对旧候选运行时（`f83455b0...`）与新生命周期运行时（`f2a678dd...`）进行了顺序受控实测。
   - **两端在当前测试样本下均顺利通过**：
     - **Old Candidate** (`f83455b0...`)：耗时 **41.72s**，退出码 **`0`**，目标退出码 **`0`**，标准输出捕获 **`X64_FEX_OK`**。
     - **New Lifecycle** (`f2a678dd...`)：耗时 **46.05s**，退出码 **`0`**，目标退出码 **`0`**，标准输出捕获 **`X64_FEX_OK`**。
     - **执行员额外探测**：在 Lead 之前的已用前缀（`lead-proton/compat`）上追加执行一次新运行时实测，耗时 **60.30s**，同样退出码 **`0`** 并捕获 **`X64_FEX_OK`**（注：此项为执行员跨前缀探索记录，非 Lead 独立执行）。
   - **Trace 比对与样本局限性**：在 `WINEDEBUG=+process,+loaddll` 跟踪下，两端日志去除地址/时间戳偏置后未见新增等待点或异常错误分支。但有限的单次样本不证明全生命周期行为绝对等价，两端耗时存在客观波动（41.72s vs 46.05s），属于正常调度起伏范围。
2. **Lead 此前 110s 超时 (`run-rkbehni4`) 现象复盘与候选解释**：
   - **并发重叠已观测**：时间戳比对显示，在 Lead 触发 `run-rkbehni4`（2026-10-16 09:44:56 UTC）的同一分钟内，后台存在 `steam-probe-worker` 运行的另一套重度虚拟机实测（`logs/steam-handoff/run-kus_rl8e`，09:44 启动并占满 110s 超时）。
   - **顺序重跑成功**：在消除并发、顺序单实例执行后，新运行时在独立前缀与 Lead 前缀上均顺利完成（46s - 60s）。
   - **因果定性**：并发 Hypervisor/vCPU 调度竞争为合理的**候选解释**；在缺乏内核底层调度器与 CPU 争用度量的情况下，原 110s 超时的排他性确切根因保持未定（维持原 110s 超时记录不篡改）。
3. **未实现系统调用警告澄清**：
   - 出现的 `WARN src/syscall/syscall.c:2841: unimplemented syscall 374` 警告在旧候选与新运行时中**完全同频同参数出现**（`x0=0x80801, x1=0x0, x2=0x100022`），系 Wine 底层尝试探测 Linux 内部非关键系统调用，被 elfuse 默认返回 ENOSYS 后 Wine 已安全 fallback 并继续执行，**绝非阻断原因**。

---

## 2. 对照实验参数矩阵与 SHA-256 锁定

| 参数维度 | 旧候选运行时 (Old Candidate) | 新生命周期运行时 (New Lifecycle) | 一致性保证 |
| :--- | :--- | :--- | :---: |
| **运行时二进制** | `sources/elfuse-crash-derived/build/elfuse-candidate` | `sources/elfuse-lifecycle-derived/build/elfuse` | 独立编译产物 |
| **SHA-256 校验和** | `f83455b073611030d388e1f7c4be1dfee26af34106a373b3a6713497790f3e26` | `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a` | 严格锁定 |
| **Proton Launcher** | `fixtures/runtime/proton-derived/proton` | `fixtures/runtime/proton-derived/proton` | 完全相同 (cmp 0) |
| **Linux Python** | `fixtures/runtime/arch-case/usr/bin/python3.14` | `fixtures/runtime/arch-case/usr/bin/python3.14` | 完全相同 (纯用户态 aarch64) |
| **测试目标** | `C:\hello-x64.exe` (动词: `runinprefix`) | `C:\hello-x64.exe` (动词: `runinprefix`) | 完全相同 |
| **前缀快照** | `fixtures/runtime/proton-contrast/old/compat/pfx` | `fixtures/runtime/proton-contrast/new/compat/pfx` | 从 task-25 冻结前缀同源独立克隆 (1347 链接零断链) |
| **调试参数** | `WINEDEBUG=+process,+loaddll` | `WINEDEBUG=+process,+loaddll` | 完全相同 |
| **外层超时看门狗**| 140 秒 | 140 秒 | 完全相同 |

---

## 3. 两端详细实测对比与日志证据

### 3.1 旧候选运行时实测 (`run-ad1vfc__`)
```
==========================================================
[OLD RESULT]
  Runtime: sources/elfuse-crash-derived/build/elfuse-candidate
  Exit code: 0
  Target exit: 0
  Timed out: False
  Elapsed: 41.72s
  STDOUT: 'X64_FEX_OK'
  Has X64_FEX_OK: True
  FEX DLL loaded: True
  Total stderr lines: 345
  Run directory: logs/proton-contrast/run-ad1vfc__
==========================================================
```

### 3.2 新生命周期运行时实测 (`run-x0q7o2qx`)
```
==========================================================
[NEW RESULT]
  Runtime: sources/elfuse-lifecycle-derived/build/elfuse
  Exit code: 0
  Target exit: 0
  Timed out: False
  Elapsed: 46.05s
  STDOUT: 'X64_FEX_OK'
  Has X64_FEX_OK: True
  FEX DLL loaded: True
  Total stderr lines: 345
  Run directory: logs/proton-contrast/run-x0q7o2qx
==========================================================
```

### 3.3 归一化 Trace 比对分析
对两端的 `stderr.log` 去除易变的 PID/TID/地址偏置与时间戳后进行差分比对：
```bash
diff -u <(sed 's/0[0-9a-f]\{2\}:/PID:/g; s/at 0000[0-9A-Fa-f]*/at ADDR/g; s/0x[0-9a-f]*/HEX/g; s/[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}/TIME/g' logs/proton-contrast/run-ad1vfc__/stderr.log) \
        <(sed 's/0[0-9a-f]\{2\}:/PID:/g; s/at 0000[0-9A-Fa-f]*/at ADDR/g; s/0x[0-9a-f]*/HEX/g; s/[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}/TIME/g' logs/proton-contrast/run-x0q7o2qx/stderr.log)
# 输出: 空 (Zero Difference)
```
- **关键阶段 1（环境与服务就绪）**：`ntdll.dll` -> `kernelbase.dll` -> `kernel32.dll` 正常载入。
- **关键阶段 2（FEX 模块装配）**：`Loaded L"C:\\windows\\system32\\libarm64ecfex.dll" at 000000DFFC1A0000: builtin` 成功完成。
- **关键阶段 3（目标进程载入与执行）**：`Loaded L"C:\\hello-x64.exe" at 0000000140000000: native` 成功完成。
- **关键阶段 4（退出与清理）**：`hello-x64.exe` 通过 `WriteFile` 写入 `X64_FEX_OK` 后调用 `ExitProcess(0)`，各子系统安全注销退出。

---

## 4. 阶段差异与 Lead 历史超时定位复盘

1. **并发重叠与候选解释**：
   - 提取自 `logs/lead-round7/run-rkbehni4` 与 `logs/steam-handoff/run-kus_rl8e`：两任务在同一分钟内并发拉起 2 个完整 Linux sysroot + Python 3.14 + Wineserver + FEX JIT 翻译实例。
   - 并发资源竞争属于强候选解释，但在当前无内核调度器跟踪的情况下，原 110s 超时的排他性因果未定。
2. **顺序执行实测证明**：
   - 在消除并发后，新运行时在独立克隆前缀（`new/compat`，46.05s）及执行员追加测试的已用前缀（`lead-proton/compat`，60.30s）上均稳定产出 `X64_FEX_OK` 并以 exit 0 结算。
3. **技术目标达成与边界**：
   - 在当前受控样本与特定测试用例（`hello-x64.exe` via `runinprefix`）下，**未复现新运行时的生命周期回归**，且具备绿灯实证。
   - 任务 26 的 direct Wine 验收结论与 task-25 的原版 Proton 启动链测试结论保持一致。无需对源码进行额外返工。

---

## 5. 验收交接与后续建议

1. **结果汇总**：
   - 旧候选运行时 `f83455b0...`：**通过** (41.72s)
   - 新生命周期运行时 `f2a678dd...`：**通过** (46.05s / 60.30s 追加)
   - 差异判定：**当前受控样本未复现回归，new Proton 链有绿灯证据**。
2. **复验命令指南**：
   ```bash
   # 独立复跑对比套件
   python3 scripts/runtime/proton_contrast/run_contrast.py
   ```
