# Linux ARM64 C++ 阶段标记观测库 (v3) 独立核验报告

**报告日期**：2026-10-16  
**审查角色**：`final-lab-reviewer`（独立审查员）  
**关联任务**：`task-49`（独立核验v3无分配阶段标记与C++异常转发）  
**被审任务**：`task-47`（为C++观测器增加无分配初始化与抛出阶段标记）  
**工作区根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**基准运行环境**：`sources/elfuse-lifecycle-derived/build/elfuse`（SHA-256：`f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`）  
**被审观测器动态库**：`fixtures/runtime/badalloc-phase/libbadalloc_phase.so`（SHA-256：`105aaa5a7b6956cfafa3561f0184f1533f29348fc556245a75c1d34e056fd173`）  
**被审源码**：`fixtures/runtime/badalloc-phase/badalloc_phase.c`（SHA-256：`94826b543b5f7a7bb798d13be94a761c0654d6bf04cc3c206a6d5daad7b68eac`）  
**审查专属归档目录**：`logs/badalloc-phase-review/`  

---

## 一、 执行摘要与总体验收判定

1. **核心验收结论**：**批准通过（APPROVED FOR BARE FEX A/B BENCHMARK）**。
   - **阶段标记与零分配前置保证确证**：
     * `constructor` 入口首先使用 `write(2)` 写入 `[PHASE_TRACE] INIT_ENTER`，且在无 C++ 运行时环境下安全标记 `INIT_RESOLVE_DEFERRED` 并正常退出，纯 C 应用退出码严格保持 0；
     * `__cxa_throw` 与 `_ZSt17__throw_bad_allocv` 入口第一条指令直接调用 `__builtin_return_address(0)` 并通过固定栈缓冲区 `raw_write_hex64` 纯系统调用输出 caller PC，**无任何 dlsym / dladdr / backtrace / stdio / heap 先于首标记**；
     * 原异常参数与对象精准透传至 real 真实实现，未吞噬异常，未破坏 C++ catch/unwind 语义。
   - **多场景纯 ELF 实测全量通过（4/4 PASS）**：
     * Case 1（纯 C 进程）：无 libstdc++ 仍安全 init 并退出 0；
     * Case 2（直接 throw 42）：捕获 caller PC 并正常 catch 退出 0；
     * Case 3（dlopen RTLD_LOCAL 插件抛出）：延迟解析正常触发并 catch 退出 0；
     * Case 4（直接调用 `std::__throw_bad_alloc()` helper）：捕获专属 helper 标记并 catch 退出 0。
2. **未知边界与严谨声明**：
   - 观测器中仅低级 `raw_write` 阶段标记保证零堆分配；后续的 `backtrace()` 与 `dladdr()` 属于 glibc/libgcc 内部实现，在极端内存耗尽（OOM）场景下是否触发内部内存分配仍属未知；
   - 缓存函数指针（`real_cxa_throw`）采用普通静态指针写入，仅在单线程或有锁加载场景成立；
   - 本任务范围严格受限于**纯 ELF 自测**，未运行 Wine / Xvfb，未涉及真实 Windows PE。

---

## 二、 关键实现审查与证据矩阵

| 审查要点 | 源码审查证据 | 实测回显与运行日志 | 判定 |
| :--- | :--- | :--- | :---: |
| **首 Marker 零分配** | `badalloc_phase.c:131-141, 197-202`：`raw_write_str` + `raw_write_hex64` 直写 `STDERR_FILENO`，先于任何动态解析与 stdio | `run-n8kzorsh/stderr.log`: 首行输出 `THROW_ENTER \| caller_pc: 0x00000000004108c4` | **PASS** |
| **纯 C 延迟解析安全** | `badalloc_phase.c:121-125`：若未解析到 C++ 运行时，仅输出 `INIT_RESOLVE_DEFERRED`，不退出、不挂起 | Case 1 `run-6hwmlznb`: `INIT_RESOLVE_DEFERRED`，退出码 `0`，stdout `PURE_C_MAIN_OK` | **PASS** |
| **RTLD_LOCAL 插件支持**| `badalloc_phase.c:75-86, 144-150`：throw 入口若未解析，使用 `RTLD_NOLOAD` 再次解析，不强制全局加载 | Case 3 `run-5qb1su_q`: 插件 dlopen 后触发 throw，捕获 `RESOLVE_NOLOAD_OK`，退出码 `0` | **PASS** |
| **Helper 独立拦截** | `badalloc_phase.c:194-251`：为 `_ZSt17__throw_bad_allocv` 提供独立无分配标记与回溯转发 | Case 4 `run-823rxn24`: 捕获 `THROW_BAD_ALLOC_HELPER_ENTER`，退出码 `0` | **PASS** |
| **异常保真转发** | `badalloc_phase.c:188-190, 247-249`：诊断完成后直接调用 real 指针，`__builtin_unreachable()` 声明 | 全部 4 组用例 baseline 与 interposed 模式 stdout/exitcode 100% 一致 | **PASS** |

---

## 三、 交付清单与下一步门禁

- **审查报告**：`reports/badalloc-phase-review.md`
- **归档日志**：`logs/badalloc-phase-review/suite_run.log`
- **结论签字**：`task-49` 满足验收条件，可正式解锁 `task-48`（在受控双臂前提下进行 Bare FEX 运行验证）。
