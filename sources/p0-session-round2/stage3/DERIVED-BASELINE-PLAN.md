# P0 Stage 3 v2: 原运行时与派生运行时同 PE 失败基线对照配置方案 (待 Lead 批准)

## 1. 架构决策与对照目标
- **架构决策变更（Lead 批准）**：
  P0 核心目标是建立原运行时 (`81803322...`) 与派生运行时 (`3b146bbe...`) 在**相同 PE、相同负载、相同预算、无任何 opt-in** 条件下的客观受控对照基线；
  对照的有效性建立在“输入、环境、命令、预算完全等价且失败受控可审计”的基础上，而非必须要求 Wine 业务层成功才允许比较。
- **本轮目标**：
  保持 Stage 3 v2 启动器（`wine_launcher_stage3_v2.py`, SHA256 `5086855c...`）与闭包清单（`CLOSURE_MANIFEST_V2.json`, SHA256 `d262d7be...`）**完全不改、不新增任何资源**；
  在完全相同的环境下执行派生运行时的单次真实 Wine 对照试验（`p0-r2-wine-derived-s3v2`），对比两款 runtime 在相同 Wine/PE 负载下的底层表现与受控退出情况。
- **严肃定性**：
  本对照属于**受控失败基线比对（Failure Baseline Comparison）**；
  目标 PE 入口执行状态保持 **UNKNOWN**，Wine 功能状态保持 **NOT_READY**。

---

## 2. 派生运行时对照精确配置 (Exact Configuration)

### 2.1 基础元数据与路径
- **Run-ID**：`p0-r2-wine-derived-s3v2`
- **运行路径**：`logs/session-v2-round2/p0-r2-wine-derived-s3v2/`
- **Sysroot 路径**：`logs/session-v2-round2/p0-r2-wine-derived-s3v2/work/r/`
- **Launcher**：`scripts/runtime/session_v2_round2/stage3/wine_launcher_stage3_v2.py` (SHA256 `5086855c...`)
- **角色指定**：`--role derived`（触发 `verify_chosen_runtime` 校验 `3b146bbe...`）
- **审批标志**：`--run-approved`

### 2.2 预算对齐（严格同原版一致）
- **vCPU 内部看门狗**：`--timeout 60`
- **Launcher Python 等待**：`wine_proc.wait(timeout=60.0)`
- **P0 Worker 内部超时**：`--timeout 75`
- **P0 Supervisor 外层 watchdog**：`--outer-timeout 85`

### 2.3 环境变量与无 Opt-In 约束（严格纯净）
- 严禁包含任何会话共享或进程内演示选项：
  - **严禁**：`ELFUSE_DIAG_SESSION_SHARED`
  - **严禁**：`ELFUSE_INPROC_PRESENT`
- 显式关闭所有试验性同步机制：
  - `WINEESYNC=0`
  - `WINEFSYNC=0`
  - `PROTON_NO_ESYNC=1`
  - `PROTON_NO_FSYNC=1`
  - `PROTON_NO_NTSYNC=1`
- 传递基础环境：`WINEPREFIX=/prefix`, `HOME=/home`, `TMPDIR=/tmp`, `LD_LIBRARY_PATH=/lib:/usr/lib:/wine/lib/wine/aarch64-unix`, `WINEDLLPATH=/wine/lib/wine/aarch64-unix`, `WINESERVER=/bin/wineserver_shim`。

### 2.4 命令结构
```bash
python3 -I scripts/runtime/session_v2/run.py \
  --run-id p0-r2-wine-derived-s3v2 \
  --timeout 75 \
  --outer-timeout 85 \
  --module launcher_stage3_v2=scripts/runtime/session_v2_round2/stage3/wine_launcher_stage3_v2.py \
  --module adapter=scripts/runtime/session_v2_round2/wine_adapter.py \
  --module shim=sources/p0-session-round2/wineserver_shim \
  --module probe=sources/p0-session-round2/wine_readiness_probe \
  --module wine=sources/proton-v3-deploy/original/files/bin-arm64/wine \
  --module server=sources/proton-v3-deploy/original/files/bin-arm64/wineserver \
  --module pe=fixtures/runtime/pe-worker/pfx/drive_c/minimal-x64.exe \
  --module runtime=sources/elfuse-inproc-present-derived/build/elfuse \
  --module closure_manifest_v2=sources/p0-session-round2/stage3/CLOSURE_MANIFEST_V2.json \
  -- python3 -I scripts/runtime/session_v2_round2/stage3/wine_launcher_stage3_v2.py \
  --root <run_dir>/work/r \
  --role derived \
  --run-approved
```

---

## 3. 状态与门控
- 本方案已准备就绪，**当前未运行任何命令，未持锁**。
- 等待 Lead 正式下发派生运行时的独占 guest 执行锁。
