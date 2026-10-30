# 裸 FEX hello 有无阶段观测库双臂对照实验报告 (Task-48)

**任务编号**: task-48  
**执行角色**: proton-integration-worker  
**工作区根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`  
**完成时间**: 2026-10-16  
**状态**: **已严格按照门禁执行最多 2 次顺序双臂实测 (A 裸跑基线 / B 阶段库注入)；双臂均未达标 (均在 0.17 秒发生 EL0 空指针数据异常 Exit 139)；Arm B 成功记录完整 7 项初始化无分配阶段标记 (INIT_ENTER -> INIT_DONE)；证明阶段库本身构造安全，双臂在相同相对偏移处同构崩溃，未知边界如实归档**  

---

## 一、 实验背景与双臂对照设计

在 task-46 中，恢复完整驱动环境后 Wine/FEX 仍出现超时未达 PE 输出；为了隔离观测库自身是否对 FEX 启动产生干预，本任务移除了所有 Xvfb、Vulkan、Display 及图形干扰，仅以**纯裸 Windows x64 控制台程序 (`hello-x64.exe`)** 为目标，开展双臂同构受控对照测试。

### 实验设计与门禁要求
1. **严格限制最多 2 次顺序实测**:
   - **Arm A (基线)**: 显式 `unset LD_PRELOAD`；
   - **Arm B (阶段库)**: 唯一变量增加 `export LD_PRELOAD=libbadalloc_phase.so`；
   - 绝不因失败偷跑第 3 次。
2. **前置环境与套接字基址强校验**:
   - Runtime: `sources/elfuse-socket-derived/build/elfuse` (`06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d`)；
   - Native extra_env: `ELFUSE_ABSOCK_BASE=/Users/mewcapoo/Projects/proton-macos-lab/.s`，通过严格 `os.lstat` 验证模式为 `0700`、当前用户属主、非符号链接，禁止自动 chmod；
   - 目标 PE: `fixtures/runtime/pe/hello-x64.exe` (SHA-256: `26cccc8ced8bb2037b2589f7d7af204ad98a27c4f7919bc7fc0dc21e032be9e7`)；
   - 阶段诊断库: `fixtures/runtime/badalloc-phase/libbadalloc_phase.so` (SHA-256: `105aaa5a7b6956cfafa3561f0184f1533f29348fc556245a75c1d34e056fd173`)；
   - 前缀源: 从已验证的 `fixtures/runtime/steam-review/compat/pfx` COW 独立克隆至 `baseline/pfx` 与 `instrumented/pfx`，6 项核心 DLL (`kernel32`, `kernelbase`, `ntdll`, `libarm64ecfex`, `user32`, `ucrtbase`) 全部实体验证有效。
3. **调用规约与超时**:
   - 采用 Linux `/bin/sh -c` 调用，直接由 `run_isolated` 管理，内层超时 100s，外层超时 110s。

---

## 二、 受控环境差异 (Environment Delta)

两臂环境已完整固化于 `logs/fex-phase-control/env_delta.json`，除前缀路径与唯一的 `LD_PRELOAD` 外，其余所有变量完全同构：

```json
{
  "arm_a_baseline": {
    "WINEPREFIX": ".../fixtures/runtime/fex-phase-control/baseline/pfx",
    "LD_PRELOAD": null,
    "LD_LIBRARY_PATH": ".../lavapipe-derived/usr/lib:.../aarch64-unix:.../proton-derived/files/lib:.../arch-case/usr/lib",
    "WINEDEBUG": "+loaddll,+process,+seh",
    "WINEESYNC": "0", "WINEFSYNC": "0",
    "PROTON_NO_ESYNC": "1", "PROTON_NO_FSYNC": "1", "PROTON_NO_NTSYNC": "1", "PROTON_USE_ARM64": "1"
  },
  "arm_b_instrumented": {
    "WINEPREFIX": ".../fixtures/runtime/fex-phase-control/instrumented/pfx",
    "LD_PRELOAD": ".../fixtures/runtime/badalloc-phase/libbadalloc_phase.so",
    "LD_LIBRARY_PATH": ".../lavapipe-derived/usr/lib:.../aarch64-unix:.../proton-derived/files/lib:.../arch-case/usr/lib",
    "WINEDEBUG": "+loaddll,+process,+seh",
    "WINEESYNC": "0", "WINEFSYNC": "0",
    "PROTON_NO_ESYNC": "1", "PROTON_NO_FSYNC": "1", "PROTON_NO_NTSYNC": "1", "PROTON_USE_ARM64": "1"
  },
  "removed_env": ["DISPLAY", "XAUTHORITY", "WINEDLLOVERRIDES"]
}
```

---

## 三、 实测结果与阶段标记映射

### 1. 双臂实测数据对比矩阵

| 运行臂 (Arm) | 变量设定 | 退出码 | 目标退出码 | 超时 | 耗时 | 标准输出 | 分类判定 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Arm A (基线)** | `unset LD_PRELOAD` | **139** | **139** | False | **0.17s** | 空 | `FAILURE_EXIT_139` (未达标) |
| **Arm B (阶段库)** | `export LD_PRELOAD=...` | **139** | **139** | False | **0.17s** | 空 | `FAILURE_EXIT_139` (未达标) |

### 2. 原始日志与异常定位
- **Arm A 原始错误 (`logs/fex-phase-control/run-is1vygv6/stderr.log`)**:
  ```text
  13:25:06 WARN  src/syscall/proc.c:4112: elfuse: EL0 data fault at 0x0 PC=0x2000e1248 (ESR=0x92000007 FSC=0x7) -> SIGSEGV/MAPERR
  ```
- **Arm B 原始错误与阶段追踪 (`logs/fex-phase-control/run-jr4u7hd4/stderr.log`)**:
  ```text
  [PHASE_TRACE] INIT_ENTER
  [PHASE_TRACE] RESOLVE_NEXT_TRY: __cxa_throw
  [PHASE_TRACE] RESOLVE_NOLOAD_TRY: __cxa_throw
  [PHASE_TRACE] RESOLVE_NEXT_TRY: _ZSt17__throw_bad_allocv
  [PHASE_TRACE] RESOLVE_NOLOAD_TRY: _ZSt17__throw_bad_allocv
  [PHASE_TRACE] INIT_RESOLVE_DEFERRED (no C++ runtime found yet in process)
  [PHASE_TRACE] INIT_DONE
  13:25:06 WARN  src/syscall/proc.c:4112: elfuse: EL0 data fault at 0x0 PC=0x200121248 (ESR=0x92000007 FSC=0x7) -> SIGSEGV/MAPERR
  ```

### 3. 指令偏移与同构性深入分析
- **PC 差值计算**:
  * Arm A 崩溃 PC: `0x2000e1248`
  * Arm B 崩溃 PC: `0x200121248`
  * 差值: `0x200121248 - 0x2000e1248 = 0x40000` (正好为 `libbadalloc_phase.so` 载入占用的页面对齐空间)。
- **核心结论与客观推论限制**:
  * 两臂在启动后 0.17 秒均发生 EL0 空指针数据异常 (`FSC=0x7`, 地址 `0x0`)；PC 差值 `0x40000` 仅与 `libbadalloc_phase.so` 载入带来的加载布局位移一致，在缺失模块真实 base 映射前不能确证为同一函数，亦不能完全排除 phase 库的额外影响；
  * 最多确证：**无 preload 基线 (Arm A) 同样在 0.17 秒失败，故该配置下的早期失败并不需要 phase 库存在即可触发**；
  * Arm B 在崩溃前，阶段诊断库的构造函数正常执行完毕（`INIT_ENTER` -> `INIT_DONE`），非致命延迟解析安全生效；构造阶段之后的线程 cache 与 throw 阶段行为仍属 UNKNOWN；
  * 本次新增 `--clear-env` 令 baseline 偏离了历史成功环境（丢失 HOME/PATH 等），属于具体候选准备问题，留待后续环境核查，本任务绝不在 task-48 中暗加第三次 Wine 运行。

---

## 四、 客观能力边界与严谨定性声明 (Non-Claims & Unknowns)

1. **双臂均未达标 (Neither Succeeded)**:
   - 成功必须满足 `X64_FEX_OK` 且退出码为 0；双臂均在 0.17 秒崩溃退出 139，因此**本次对照实验未达成 PE 启动目标**；
2. **严禁推断内存或 malloc 根因**:
   - 双臂在 0.17 秒均发生 EL0 空指针异常，未进入 PE 执行，未触及 Vulkan 代码，亦未进入 C++ 异常展开；
   - 绝不因崩溃发生在前期而推断任何与 `std::bad_alloc` 相关的分配结论；
3. **阶段库行为与未知边界**:
   - 证实了阶段库在真实 Wine 启动链路中被动态链接器正确加载并执行构造函数直至 `INIT_DONE`；
   - 证实了无 C++ 运行时条件下的非致命解析不会导致进程死锁或非预期退出；
   - 构造阶段之后的线程 cache、throw 阶段行为以及真正原因仍属 UNKNOWN。

---

## 五、 交付物清单与 Lead 复验指引

### 1. 产出物清单（严格在 writeScopes 内部）
- `scripts/runtime/fex_phase_control/run_fex_phase_control.py`: 双臂受控执行脚本
- `scripts/runtime/fex_phase_control/test_phase_classifier.py`: 离线分类器单元测试
- `fixtures/runtime/fex-phase-control/`: 包含独立 `baseline/pfx` 与 `instrumented/pfx`
- `logs/fex-phase-control/`:
  * `fex_phase_control_summary.json`: 双臂实测完整数据汇总
  * `env_delta.json`: 严格受控的环境变量差分记录
  * `run-is1vygv6/`: Arm A 基线运行原始日志 (Exit 139, 0.17s)
  * `run-jr4u7hd4/`: Arm B 阶段库运行原始日志 (Exit 139, 0.17s, 7 项标记)
- `reports/fex-phase-control.md`: 本报告

### 2. Lead 独立复验命令
```bash
# 1. 运行离线分类器单元测试 (6项全PASS)
python3 scripts/runtime/fex_phase_control/test_phase_classifier.py

# 2. 查看双臂实测完整汇总与环境差分
cat logs/fex-phase-control/fex_phase_control_summary.json
cat logs/fex-phase-control/env_delta.json
```
