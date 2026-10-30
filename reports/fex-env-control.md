# 恢复受控基础环境后配对验证裸 FEX hello 与阶段库实测报告 (Task-52)

**任务编号**: task-52  
**执行角色**: proton-integration-worker  
**工作区根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`  
**完成时间**: 2026-10-16  
**状态**: **已在 task-50 B2 受控环境 profile 下完成裸 FEX hello-x64 双臂严格顺序实测；坚决摒弃 --clear-env 准备缺陷；Arm A (基线) 与 Arm B (阶段库) 双臂 100% 成功输出 X64_FEX_OK 并达成纯净 Exit 0 (overall 0 / target 0 / notimeout / cleanuperror 0)；证实在此受控配置下 v3 阶段库完全未阻碍裸控制台 PE 启动**  

---

## 一、 实验背景与双臂对照设计

在 task-48 中，由于错误引入 `--clear-env` 导致环境 profile 整体剥离（task-50 实证：`--clear-env` 使 `wine --version` 0.16s 触发 139 崩溃，而恢复 `clean_env` 后 `wine --version` 0.17s 成功输出 `wine-11.0` 且 Exit 0）。
本任务在 task-50 确立的受控环境 profile 基础上，彻底剔除 `--clear-env`，针对裸 Windows x64 控制台程序 `hello-x64.exe` 开展精准受控双臂对比实测。

### 实验设计与门禁要求
1. **严格限制最多 2 次顺序真实 Wine 运行**:
   - **Arm A (基线)**: 显式 `unset LD_PRELOAD`；
   - **Arm B (阶段库)**: 唯一变量增加 `export LD_PRELOAD=libbadalloc_phase.so`；
   - 绝不因任何原因暗加第三次运行。
2. **前置环境与套接字基址强校验**:
   - Runtime: `sources/elfuse-socket-derived/build/elfuse` (`06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d`)；
   - Native extra_env: `ELFUSE_ABSOCK_BASE=/Users/mewcapoo/Projects/proton-macos-lab/.s`，通过严格 `os.lstat` 验证模式为 `0700`、当前用户属主、非符号链接，禁止自动 chmod；
   - 目标 PE: `fixtures/runtime/pe/hello-x64.exe` (真实字节计算 SHA-256: `26cccc8ced8bb2037b2589f7d7af204ad98a27c4f7919bc7fc0dc21e032be9e7`)；
   - 阶段诊断库: `fixtures/runtime/badalloc-phase/libbadalloc_phase.so` (SHA-256: `105aaa5a7b6956cfafa3561f0184f1533f29348fc556245a75c1d34e056fd173`)；
   - 前缀源: 从已验证的 `fixtures/runtime/steam-review/compat/pfx` COW 独立克隆至 `baseline/pfx` 与 `instrumented/pfx`，6 项核心 DLL (`kernel32`, `kernelbase`, `ntdll`, `libarm64ecfex`, `user32`, `ucrtbase`) 全部实体验证有效。
3. **调用规约与超时控制**:
   - 采用 Linux `/bin/sh -c` 调用，直接由 `run_isolated` 管理，不经过额外的 Python 控制器层（杜绝吞并子进程真实退出码）；
   - 内层超时 100s，外层超时 110s；
   - 剥离所有 `DISPLAY`、`XAUTHORITY` 与 `WINEDLLOVERRIDES`，排除图形服务干扰。

---

## 二、 受控环境差异 (Environment Delta)

两臂环境已完整固化于 `logs/fex-env-control/env_delta.json`，除前缀路径与唯一的 `LD_PRELOAD` 外，其余所有变量完全同构：

```json
{
  "arm_a_baseline": {
    "WINEPREFIX": ".../fixtures/runtime/fex-env-control/baseline/pfx",
    "LD_PRELOAD": null,
    "LD_LIBRARY_PATH": ".../lavapipe-derived/usr/lib:.../aarch64-unix:.../proton-derived/files/lib:.../arch-case/usr/lib",
    "target": "C:\\hello-x64.exe",
    "WINEESYNC": "0", "WINEFSYNC": "0",
    "PROTON_NO_ESYNC": "1", "PROTON_NO_FSYNC": "1", "PROTON_NO_NTSYNC": "1", "PROTON_USE_ARM64": "1",
    "WINEDEBUG": "+loaddll,+process,+seh"
  },
  "arm_b_instrumented": {
    "WINEPREFIX": ".../fixtures/runtime/fex-env-control/instrumented/pfx",
    "LD_PRELOAD": ".../fixtures/runtime/badalloc-phase/libbadalloc_phase.so",
    "LD_LIBRARY_PATH": ".../lavapipe-derived/usr/lib:.../aarch64-unix:.../proton-derived/files/lib:.../arch-case/usr/lib",
    "target": "C:\\hello-x64.exe",
    "WINEESYNC": "0", "WINEFSYNC": "0",
    "PROTON_NO_ESYNC": "1", "PROTON_NO_FSYNC": "1", "PROTON_NO_NTSYNC": "1", "PROTON_USE_ARM64": "1",
    "WINEDEBUG": "+loaddll,+process,+seh"
  },
  "clean_env_inherited": ["HOME", "PATH", "LANG", "TMPDIR", "XDG_*"],
  "removed_env": ["DISPLAY", "XAUTHORITY", "WINEDLLOVERRIDES"],
  "clear_env_used": false
}
```

---

## 三、 实测结果与阶段标记映射

### 1. 双臂实测数据对比矩阵

| 运行臂 (Arm) | 变量设定 | 退出码 | 目标退出码 | 超时 | 耗时 | 标准输出 | 分类判定 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Arm A (基线)** | `unset LD_PRELOAD` | **0** | **0** | False | **79.28s** | **`X64_FEX_OK`** | **`SUCCESS_PE_OUTPUT_CLEAN_EXIT0`** |
| **Arm B (阶段库)** | `export LD_PRELOAD=...` | **0** | **0** | False | **63.98s** | **`X64_FEX_OK`** | **`SUCCESS_PE_OUTPUT_CLEAN_EXIT0`** |

### 2. 实测结果分析
1. **Arm A (基线, `run-9ku8aeiz`)**:
   - 耗时 79.28 秒，成功输出 `X64_FEX_OK`，无超时，无崩溃，纯净退出 0；
   - 确证在恢复受控基础环境（不使用 `--clear-env`）后，裸 FEX + Wine 具备稳定执行 Windows x64 控制台程序的能力。
2. **Arm B (注入阶段诊断库, `run-y6puawlg`)**:
   - 耗时 63.98 秒，成功输出 `X64_FEX_OK`，无超时，无崩溃，纯净退出 0；
   - 阶段诊断库在 Wine 启动链路的多进程（`wineserver`, `wine-preloader`, `wine` 等）中被动态链接器正常加载，累计记录 63 次构造阶段标记（`INIT_ENTER` -> `RESOLVE_TRY` -> `INIT_RESOLVE_DEFERRED` -> `INIT_DONE`）；
   - 由于本用例为正常退出的裸控制台程序，进程内未发生 C++ 异常，因此未触发 `THROW_ENTER`，未产生异常调用栈日志；
   - **核心实证结论**: 在受控基础环境下，`libbadalloc_phase.so` 自身的挂载与构造**完全未阻碍 FEX 启动与 PE 正常退出**，双臂均达成纯净 Exit 0 与正确标语输出。

---

## 四、 客观能力边界与严谨定性声明 (Non-Claims & Unknowns)

1. **有限样本与环境限定**:
   - 本次测试的成功**仅限于裸 Windows x64 控制台程序 (`hello-x64.exe`) 在 task-50 B2 受控环境 profile 下的表现**；
   - 证明了阶段观测库自身在此配置下是安全且非阻塞的；
2. **严禁泛化至图形或复杂应用**:
   - 本任务移除了所有 Xvfb 与 Vulkan 图形组件，因此**不能据此推断阶段库在 GUI/X11/Vulkan 复杂多线程驱动环境下的绝对表现**；
   - 亦不能据此宣称解决了历史任务中的图形驱动超时或内存分配问题；
3. **未决边界与后续推展**:
   - 本任务中 Arm B 未进入 `THROW_ENTER` 仅代表本测试程序未发生异常，不代表异常处理路径在所有场景下均完全透明；
   - 真实图形与驱动环境下的阶段观测需在后续专属受控任务中结合具体环境进一步推进。

---

## 五、 交付物清单与 Lead 复验指引

### 1. 产出物清单（严格在 writeScopes 内部）
- `scripts/runtime/fex_env_control/run_fex_env_control.py`: 双臂受控执行脚本
- `scripts/runtime/fex_env_control/test_env_classifier.py`: 离线分类器单元测试
- `fixtures/runtime/fex-env-control/`: 包含独立 `baseline/pfx` 与 `instrumented/pfx`
- `logs/fex-env-control/`:
  * `fex_env_control_summary.json`: 双臂实测完整数据汇总
  * `env_delta.json`: 严格受控的环境变量差分记录
  * `run-9ku8aeiz/`: Arm A 基线运行原始日志 (Exit 0, 79.28s, X64_FEX_OK)
  * `run-y6puawlg/`: Arm B 阶段库运行原始日志 (Exit 0, 63.98s, X64_FEX_OK, 63 项标记)
- `reports/fex-env-control.md`: 本报告

### 2. Lead 独立复验命令
```bash
# 1. 运行纯离线分类器单元测试 (7项断言全PASS)
python3 scripts/runtime/fex_env_control/test_env_classifier.py

# 2. 查看双臂实测完整汇总与环境差分
cat logs/fex-env-control/fex_env_control_summary.json
cat logs/fex-env-control/env_delta.json
```
