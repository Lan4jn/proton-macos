# Linux ARM64 C++ 异常调用栈观测器 v3 阶段标记自测报告 (Task-47)

**任务编号**: task-47  
**执行角色**: proton-integration-worker  
**工作区根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`  
**完成时间**: 2026-10-16  
**状态**: **已完成独立 v3 阶段标记诊断器构建与纯 Linux ARM64 ELF 4 组自测试套件验证；通过纯 C 主程序延迟解析、直接 C++ 抛出、C main + dlopen(RTLD_LOCAL) 插件、以及直接调用 std::__throw_bad_alloc() 辅助函数全部 4 组 TDD 测试；实测证实纯 write 无分配阶段标记与原始调用者 PC 准确输出，全套测试基线与注入均正常 Exit 0**  

---

## 一、 执行摘要与设计意图

在 task-39（v2 拦截器）与 task-42（Wine 注入观测）的实践中，观测到 Wine 在 `vkCreateInstance` 内部等待并最终超时，未输出 `[BADALLOC_TRACE]`。为了在复杂客体环境及后续 Wine 对照测试中能够**严格区分“拦截库未挂载 / 进程从未进入 throw / 阻塞在 dlsym 解析阶段 / 阻塞在 backtrace 内部”**，本任务构建了独立的 v3 阶段标记诊断库 `libbadalloc_phase.so`。

### 核心改进与设计原则
1. **构造函数与抛出入口绝对无内存分配 (Zero-Allocation Markers)**:
   - 构造函数入口与各个解析阶段采用纯系统调用 `write(STDERR_FILENO, ...)` 输出阶段标记，完全不调用 `malloc`、`printf` 或 `stdio` 缓冲；
   - 构造函数中若未发现 C++ 运行时（如纯 C 主程序启动阶段），**允许安全延迟解析（`INIT_RESOLVE_DEFERRED`）而不退出、不阻塞、不报错**，允许后续动态加载的 C++ 共享库在实际抛出时再行绑定；
2. **抛出入口首指令记录原始调用者 PC (Raw Caller PC Ahead of All)**:
   - 在 `__cxa_throw` 与 `_ZSt17__throw_bad_allocv` 的**第一条有效指令**处，立即提取 `__builtin_return_address(0)`，通过栈上 19 字节固定缓冲区手写十六进制，直接通过 `write(2)` 输出原始调用者 PC；
   - 确保在执行任何 `dlsym`、`dladdr`、`backtrace` 或堆分配之前，抛出点的硬件 PC 已经被绝对写入标准错误流；
3. **扩展拦截 `std::__throw_bad_alloc()` 辅助函数**:
   - 拦截 mangled 符号 `_ZSt17__throw_bad_allocv`（确认真实导出于 `libstdc++.so.6`，ABI 为 `void (void) noreturn`）；
   - 在辅助函数入口与转发阶段插入独立阶段标记，使得在 `std::bad_alloc` 发生之初即可精确捕获分配调用点；
4. **门禁与纪律遵守**:
   - 本任务**绝不启动 Xvfb 或 Wine**，原 v2 产物（`fixtures/runtime/badalloc-trace/libbadalloc_trace.so` `6f034...`）保持完全冻结；
   - 全程仅在独立的 Linux ARM64 ELF 自测试套件下开展 TDD 闭环验证。

---

## 二、 阶段标记与函数架构设计

### 1. 无分配底层 I/O 设计
```c
static void raw_write(const char *buf, size_t len);
static void raw_write_str(const char *s);
static void raw_write_hex64(uint64_t v);
```
- 直接使用 `write(STDERR_FILENO, ...)` 循环写出；
- `raw_write_hex64` 在当前函数栈帧上开辟 19 字节固定数组（`char buf[19]`），就地展开 16 位十六进制，零外部依赖、零锁争用、零堆分配。

### 2. 阶段标记生命周期序列
```text
[程序加载阶段 (Constructor)]
  ├─► [PHASE_TRACE] INIT_ENTER
  ├─► [PHASE_TRACE] RESOLVE_NEXT_TRY: __cxa_throw
  ├─► [PHASE_TRACE] RESOLVE_NEXT_OK / RESOLVE_NOLOAD_TRY ...
  ├─► (若无 C++ 运行时) [PHASE_TRACE] INIT_RESOLVE_DEFERRED
  └─► [PHASE_TRACE] INIT_DONE

[C++ 异常抛出阶段 (__cxa_throw 入口)]
  ├─► [PHASE_TRACE] THROW_ENTER | caller_pc: 0x... | obj: 0x... | tinfo: 0x...
  ├─► (若此前未解析) 触发延迟解析 -> [PHASE_TRACE] RESOLVE_NOLOAD_OK ...
  ├─► [PHASE_TRACE] BACKTRACE_ENTER
  │     └─► [BADALLOC_TRACE] === C++ EXCEPTION THROWN === (详细调用栈格式化输出)
  ├─► [PHASE_TRACE] BACKTRACE_DONE
  ├─► [PHASE_TRACE] FORWARD_ENTER: calling real __cxa_throw
  └─► 真实 C++ 异常展开与捕获处理 (Transparent Forwarding)

[std::__throw_bad_alloc() 辅助函数入口]
  ├─► [PHASE_TRACE] THROW_BAD_ALLOC_HELPER_ENTER | caller_pc: 0x...
  ├─► [PHASE_TRACE] HELPER_BACKTRACE_ENTER
  │     └─► [BADALLOC_TRACE] === STD::__THROW_BAD_ALLOC() INVOKED ===
  ├─► [PHASE_TRACE] HELPER_BACKTRACE_DONE
  ├─► [PHASE_TRACE] HELPER_FORWARD_ENTER: calling real _ZSt17__throw_bad_allocv
  └─► 进入 libstdc++ 构造 bad_alloc 对象并下发至 __cxa_throw
```

---

## 三、 源码演进对比 (v3 vs v2)

源码补丁真实差异如下（`diff -u badalloc_trace.c badalloc_phase.c`）：
```diff
--- fixtures/runtime/badalloc-trace/badalloc_trace.c (v2)
+++ fixtures/runtime/badalloc-phase/badalloc_phase.c (v3)
@@ -7,17 +7,62 @@
 #include <stdlib.h>
 #include <unistd.h>
 
+/* --- Allocation-free low-level I/O helpers (pure write(2), zero malloc) --- */
+static void raw_write(const char *buf, size_t len);
+static void raw_write_str(const char *s);
+static void raw_write_hex64(uint64_t v);
+
+/* --- Real function pointers --- */
 typedef void (*cxa_throw_fn)(void *thrown_exception, void *tinfo, void (*dest)(void *));
+typedef void (*throw_bad_alloc_fn)(void);
 static cxa_throw_fn real_cxa_throw = NULL;
+static throw_bad_alloc_fn real_throw_bad_alloc = NULL;
 static __thread bool in_trace = false;
 
 static cxa_throw_fn resolve_real_cxa_throw(void) {
+    raw_write_str("[PHASE_TRACE] RESOLVE_NEXT_TRY: __cxa_throw\n");
     cxa_throw_fn fn = (cxa_throw_fn)dlsym(RTLD_NEXT, "__cxa_throw");
-    if (fn) return fn;
+    if (fn) {
+        raw_write_str("[PHASE_TRACE] RESOLVE_NEXT_OK: __cxa_throw\n");
+        return fn;
+    }
+    raw_write_str("[PHASE_TRACE] RESOLVE_NOLOAD_TRY: __cxa_throw\n");
+    ...
 }
+static throw_bad_alloc_fn resolve_real_throw_bad_alloc(void);
 
 static void badalloc_phase_init(void) __attribute__((constructor));
 static void badalloc_phase_init(void) {
+    raw_write_str("[PHASE_TRACE] INIT_ENTER\n");
+    real_cxa_throw = resolve_real_cxa_throw();
+    real_throw_bad_alloc = resolve_real_throw_bad_alloc();
+    if (!real_cxa_throw && !real_throw_bad_alloc) {
+        raw_write_str("[PHASE_TRACE] INIT_RESOLVE_DEFERRED (no C++ runtime found yet in process)\n");
+    }
+    raw_write_str("[PHASE_TRACE] INIT_DONE\n");
 }
 
 void __cxa_throw(void *thrown_exception, void *tinfo, void (*dest)(void *)) {
+    /* 1. First instruction: pure allocation-free write of marker and raw caller PC */
+    void *caller_pc = __builtin_return_address(0);
+    raw_write_str("[PHASE_TRACE] THROW_ENTER | caller_pc: ");
+    raw_write_hex64((uint64_t)caller_pc);
+    ...
+    raw_write_str("[PHASE_TRACE] BACKTRACE_ENTER\n");
+    ...
+    raw_write_str("[PHASE_TRACE] BACKTRACE_DONE\n");
+    raw_write_str("[PHASE_TRACE] FORWARD_ENTER: calling real __cxa_throw\n");
+    real_cxa_throw(thrown_exception, tinfo, dest);
 }
+
+void _ZSt17__throw_bad_allocv(void) {
+    void *caller_pc = __builtin_return_address(0);
+    raw_write_str("[PHASE_TRACE] THROW_BAD_ALLOC_HELPER_ENTER | caller_pc: ");
+    raw_write_hex64((uint64_t)caller_pc);
+    ...
+    raw_write_str("[PHASE_TRACE] HELPER_FORWARD_ENTER: calling real _ZSt17__throw_bad_allocv\n");
+    real_throw_bad_alloc();
+}
```

---

## 四、 关键资产与指纹审计 (已全数冻结)

| 资产名称 | 本地文件路径 | SHA-256 校验和 | 属性说明 |
| :--- | :--- | :--- | :--- |
| **宿主执行器** | `sources/elfuse-lifecycle-derived/build/elfuse` | `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a` | 冻结 |
| **v3 阶段标记拦截库** | `fixtures/runtime/badalloc-phase/libbadalloc_phase.so` | `105aaa5a7b6956cfafa3561f0184f1533f29348fc556245a75c1d34e056fd173` | 新增产物 (FROZEN) |
| **v3 拦截库源码** | `fixtures/runtime/badalloc-phase/badalloc_phase.c` | `cf613c77eb0509425ae1df0486c478a3c8ae930f79ae6b643b0f55cf66bf9149` | 新增产物 (FROZEN) |
| **Case 1 测试 ELF** | `fixtures/runtime/badalloc-phase/test_pure_c` | `a8539f0a2fc82cd361e61416c505f96907fd676b48e6966dfc74c10e5674f11a` | 纯 C 二进制 (FROZEN) |
| **Case 2 测试 ELF** | `fixtures/runtime/badalloc-phase/test_throw42` | `174c4c34c08b255159d03b52eb0e882ff9cad23c64072ddfb4c07616a6c1aebd` | 直接 C++ 二进制 (FROZEN) |
| **Case 3 主程序 ELF** | `fixtures/runtime/badalloc-phase/test_dlopen_local` | `08ee21eb8bdc1d1bdacfc9266a95979f89311d6eb533f6dacdd31ad5b29bfbe5` | 纯 C dlopen 主程序 (FROZEN) |
| **Case 3 插件 DSO** | `fixtures/runtime/badalloc-phase/plugin_cpp.so` | `2e0542b81eb07e09197c61bba0dc42db5506d53b2431c354b030be9071e42efb` | 局部作用域 C++ 插件 (FROZEN) |
| **Case 4 测试 ELF** | `fixtures/runtime/badalloc-phase/test_bad_alloc` | `84cc7e356d31e8932f513f45357e41354f789119810e0b384b92975122f31726` | 直接调用辅助函数 (FROZEN) |
| **测试套件运行器** | `scripts/runtime/badalloc_phase/run_badalloc_phase_test.py` | `011bc90520e58c0c16922ff1e1383796bb8676239ba395f1be6d5b078519106d` | 自动化自测脚本 (FROZEN) |

---

## 五、 4 组 TDD 自测试套件实测验证矩阵

测试由自动化套件 `scripts/runtime/badalloc_phase/run_badalloc_phase_test.py` 在受控隔离主管进程下运行，针对 4 组用例分别执行 Baseline（未注入）与 Interposed（注入 `libbadalloc_phase.so`）对比验证：

| 测试用例 | 运行模式 | 退出码 | 目标退出码 | 标准输出 | 阶段标记捕获情况 | 判定 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Case 1: 纯 C 主程序** (test_pure_c) | Baseline | **0** | **0** | `CASE1_PURE_C_OK` | 无标记 (0 行) | **PASS** |
| | Interposed | **0** | **0** | `CASE1_PURE_C_OK` | `INIT_ENTER` -> `INIT_RESOLVE_DEFERRED` -> `INIT_DONE` | **PASS (延迟解析正常)** |
| **Case 2: 直接 C++ 抛出** (test_throw42) | Baseline | **0** | **0** | `CASE2_THROW42_OK` | 无标记 (0 行) | **PASS** |
| | Interposed | **0** | **0** | `CASE2_THROW42_OK` | `INIT_ENTER` -> `THROW_ENTER(caller_pc)` -> `FORWARD_ENTER` | **PASS (捕获并透传)** |
| **Case 3: C main dlopen 局部插件** | Baseline | **0** | **0** | `CASE3_DLOPEN_OK` | 无标记 (0 行) | **PASS** |
| | Interposed | **0** | **0** | `CASE3_DLOPEN_OK` | `INIT_ENTER(deferred)` -> `THROW_ENTER` -> `RESOLVE_NOLOAD_OK` -> `FORWARD_ENTER` | **PASS (NOLOAD 穿透)** |
| **Case 4: std::__throw_bad_alloc** | Baseline | **0** | **0** | `CASE4_BAD_ALLOC_OK` | 无标记 (0 行) | **PASS** |
| | Interposed | **0** | **0** | `CASE4_BAD_ALLOC_OK` | `THROW_BAD_ALLOC_HELPER_ENTER(caller_pc)` -> `HELPER_FORWARD` -> `THROW_ENTER` -> `FORWARD` | **PASS (双层拦截透传)** |

### 4 组用例注入运行实测标准错误原始日志
```text
=== Case 1: Pure C (test_pure_c) ===
[PHASE_TRACE] INIT_ENTER
[PHASE_TRACE] RESOLVE_NEXT_TRY: __cxa_throw
[PHASE_TRACE] RESOLVE_NOLOAD_TRY: __cxa_throw
[PHASE_TRACE] RESOLVE_NEXT_TRY: _ZSt17__throw_bad_allocv
[PHASE_TRACE] RESOLVE_NOLOAD_TRY: _ZSt17__throw_bad_allocv
[PHASE_TRACE] INIT_RESOLVE_DEFERRED (no C++ runtime found yet in process)
[PHASE_TRACE] INIT_DONE

=== Case 2: Direct C++ throw 42 (test_throw42) ===
[PHASE_TRACE] INIT_ENTER
[PHASE_TRACE] RESOLVE_NEXT_TRY: __cxa_throw
[PHASE_TRACE] RESOLVE_NEXT_OK: __cxa_throw
[PHASE_TRACE] RESOLVE_NEXT_TRY: _ZSt17__throw_bad_allocv
[PHASE_TRACE] RESOLVE_NEXT_OK: _ZSt17__throw_bad_allocv
[PHASE_TRACE] INIT_DONE
[PHASE_TRACE] THROW_ENTER | caller_pc: 0x00000000004108c4 | obj: 0x00000000010120a0 | tinfo: 0x0000000200364390 | dest: 0x0000000000000000
[PHASE_TRACE] BACKTRACE_ENTER
[BADALLOC_TRACE] === C++ EXCEPTION THROWN ===
[BADALLOC_TRACE] Caller PC: 0x4108c4 | Thrown Object: 0x10120a0 | TypeInfo Ptr: 0x200364390 | Destructor: (nil)
[BADALLOC_TRACE] Backtrace (5 frames):
  [BADALLOC_TRACE] #00: 0x2000219f0 in .../libbadalloc_phase.so (+0x119f0) [__cxa_throw+0x598]
  [BADALLOC_TRACE] #01: 0x4108c4 in .../test_throw42 (+0x108c4) [<unknown>+0x0]
  [BADALLOC_TRACE] #02: 0x2003e2d94 in /usr/lib/libc.so.6 (+0x22d94) [<unknown>+0x0]
  [BADALLOC_TRACE] #03: 0x2003e2ef8 in /usr/lib/libc.so.6 (+0x22ef8) [__libc_start_main+0x98]
  [BADALLOC_TRACE] #04: 0x410870 in .../test_throw42 (+0x10870) [<unknown>+0x0]
[BADALLOC_TRACE] === END BADALLOC TRACE ===
[PHASE_TRACE] BACKTRACE_DONE
[PHASE_TRACE] FORWARD_ENTER: calling real __cxa_throw

=== Case 3: C main dlopen(RTLD_LOCAL) plugin (test_dlopen_local) ===
[PHASE_TRACE] INIT_ENTER
[PHASE_TRACE] RESOLVE_NEXT_TRY: __cxa_throw
[PHASE_TRACE] RESOLVE_NOLOAD_TRY: __cxa_throw
[PHASE_TRACE] RESOLVE_NEXT_TRY: _ZSt17__throw_bad_allocv
[PHASE_TRACE] RESOLVE_NOLOAD_TRY: _ZSt17__throw_bad_allocv
[PHASE_TRACE] INIT_RESOLVE_DEFERRED (no C++ runtime found yet in process)
[PHASE_TRACE] INIT_DONE
[PHASE_TRACE] THROW_ENTER | caller_pc: 0x0000000200290624 | obj: 0x0000000001000090 | tinfo: 0x00000002005a4390 | dest: 0x0000000000000000
[PHASE_TRACE] RESOLVE_NEXT_TRY: __cxa_throw
[PHASE_TRACE] RESOLVE_NOLOAD_TRY: __cxa_throw
[PHASE_TRACE] RESOLVE_NOLOAD_OK: __cxa_throw in libstdc++.so.6
[PHASE_TRACE] BACKTRACE_ENTER
[BADALLOC_TRACE] === C++ EXCEPTION THROWN ===
[BADALLOC_TRACE] Caller PC: 0x200290624 | Thrown Object: 0x1000090 | TypeInfo Ptr: 0x2005a4390 | Destructor: (nil)
[BADALLOC_TRACE] Backtrace (6 frames):
  [BADALLOC_TRACE] #00: 0x2000219f0 in .../libbadalloc_phase.so (+0x119f0) [__cxa_throw+0x598]
  [BADALLOC_TRACE] #01: 0x200290624 in .../plugin_cpp.so (+0x10624) [run_plugin_throw+0x2c]
  [BADALLOC_TRACE] #02: 0x410860 in .../test_dlopen_local (+0x10860) [<unknown>+0x0]
  [BADALLOC_TRACE] #03: 0x2000d2d94 in /usr/lib/libc.so.6 (+0x22d94) [<unknown>+0x0]
  [BADALLOC_TRACE] #04: 0x2000d2ef8 in /usr/lib/libc.so.6 (+0x22ef8) [__libc_start_main+0x98]
  [BADALLOC_TRACE] #05: 0x4107f0 in .../test_dlopen_local (+0x107f0) [<unknown>+0x0]
[BADALLOC_TRACE] === END BADALLOC TRACE ===
[PHASE_TRACE] BACKTRACE_DONE
[PHASE_TRACE] FORWARD_ENTER: calling real __cxa_throw

=== Case 4: std::__throw_bad_alloc() (test_bad_alloc) ===
[PHASE_TRACE] INIT_ENTER
[PHASE_TRACE] RESOLVE_NEXT_TRY: __cxa_throw
[PHASE_TRACE] RESOLVE_NEXT_OK: __cxa_throw
[PHASE_TRACE] RESOLVE_NEXT_TRY: _ZSt17__throw_bad_allocv
[PHASE_TRACE] RESOLVE_NEXT_OK: _ZSt17__throw_bad_allocv
[PHASE_TRACE] INIT_DONE
[PHASE_TRACE] THROW_BAD_ALLOC_HELPER_ENTER | caller_pc: 0x0000000000410824
[PHASE_TRACE] HELPER_BACKTRACE_ENTER
[BADALLOC_TRACE] === STD::__THROW_BAD_ALLOC() INVOKED ===
[BADALLOC_TRACE] Caller PC: 0x410824
[BADALLOC_TRACE] Backtrace (5 frames):
  [BADALLOC_TRACE] #00: 0x200021d5c in .../libbadalloc_phase.so (+0x11d5c) [_ZSt17__throw_bad_allocv+0x218]
  [BADALLOC_TRACE] #01: 0x410824 in .../test_bad_alloc (+0x10824) [<unknown>+0x0]
  [BADALLOC_TRACE] #02: 0x2003e2d94 in /usr/lib/libc.so.6 (+0x22d94) [<unknown>+0x0]
  [BADALLOC_TRACE] #03: 0x2003e2ef8 in /usr/lib/libc.so.6 (+0x22ef8) [__libc_start_main+0x98]
  [BADALLOC_TRACE] #04: 0x4107f0 in .../test_bad_alloc (+0x107f0) [<unknown>+0x0]
[BADALLOC_TRACE] === END BADALLOC TRACE ===
[PHASE_TRACE] HELPER_BACKTRACE_DONE
[PHASE_TRACE] HELPER_FORWARD_ENTER: calling real _ZSt17__throw_bad_allocv
[PHASE_TRACE] THROW_ENTER | caller_pc: 0x0000000200127e28 | obj: 0x00000000010120e0 | tinfo: 0x00000002003638f0 | dest: 0x0000000200131160
[PHASE_TRACE] BACKTRACE_ENTER
[BADALLOC_TRACE] === C++ EXCEPTION THROWN ===
[BADALLOC_TRACE] Caller PC: 0x200127e28 | Thrown Object: 0x10120e0 | TypeInfo Ptr: 0x2003638f0 | Destructor: 0x200131160
[BADALLOC_TRACE] Backtrace (7 frames):
  [BADALLOC_TRACE] #00: 0x2000219f0 in .../libbadalloc_phase.so (+0x119f0) [__cxa_throw+0x598]
  [BADALLOC_TRACE] #01: 0x200127e28 in /usr/lib/libstdc++.so.6 (+0xa7e28) [_ZSt28__throw_bad_array_new_lengthv+0x0]
  [BADALLOC_TRACE] #02: 0x200021e90 in .../libbadalloc_phase.so (+0x11e90) [<unknown>+0x0]
  [BADALLOC_TRACE] #03: 0x410824 in .../test_bad_alloc (+0x10824) [<unknown>+0x0]
  [BADALLOC_TRACE] #04: 0x2003e2d94 in /usr/lib/libc.so.6 (+0x22d94) [<unknown>+0x0]
  [BADALLOC_TRACE] #05: 0x2003e2ef8 in /usr/lib/libc.so.6 (+0x22ef8) [__libc_start_main+0x98]
  [BADALLOC_TRACE] #06: 0x4107f0 in .../test_bad_alloc (+0x107f0) [<unknown>+0x0]
[BADALLOC_TRACE] === END BADALLOC TRACE ===
[PHASE_TRACE] BACKTRACE_DONE
[PHASE_TRACE] FORWARD_ENTER: calling real __cxa_throw
```

---

## 六、 技术边界与严谨定性声明 (Non-Claims & Unknowns)

1. **严格限定于自测 ELF 范围**:
   - 本报告的结论**仅适用于本次在 Linux ARM64 ELF 自测试程序（Case 1~4）中验证通过的符号拦截与阶段标记能力**；
   - 证明了在上述测试 ELF 环境下，无分配阶段标记能准确记录初始化与抛出调用者 PC，且透明透传未破坏应用本身的 throw/catch 正常执行；
2. **非信号安全与 OOM 二次分配局限**:
   - 本观测器并非信号处理器（非 async-signal-safe）；仅前置的 `[PHASE_TRACE]` 阶段标记与 raw caller PC 采用纯 `write(2)` 栈缓冲保证无堆分配；
   - 后续的 `backtrace()`、`dladdr()` 与 `fprintf(stderr)` 包含标准库内部逻辑；在真实物理内存绝对耗尽（极端 OOM）时，标准库内部可能产生二次分配异常，该局限属于客观已知技术事实，**绝不泛化宣称“在所有极端 OOM 场景下100%保证输出”**；
3. **未决边界与无 Wine 启动**:
   - 本任务按约束**完全未启动 Wine 或 Xvfb**；
   - 本任务不声称历史 Wine 运行中的 `std::bad_alloc` 已经被解释或解决；
   - 后续 Wine 环境中是否存在未知的其他 C++ 异常运行时（如私有打包的 libc++abi 或静态链接）仍属技术未知，待后续由 Lead 统一调度的对照实验进一步验证。

---

## 七、 交付物清单与独立复验指引

### 1. 产出物清单（严格在 writeScopes 内部）
- `fixtures/runtime/badalloc-phase/badalloc_phase.c`: v3 拦截库源码
- `fixtures/runtime/badalloc-phase/libbadalloc_phase.so`: 编译好的 ARM64 阶段标记共享库 (SHA: `105aaa5a...`)
- `fixtures/runtime/badalloc-phase/test_pure_c.c` & `test_pure_c`: Case 1 测试程序源码与二进制
- `fixtures/runtime/badalloc-phase/test_throw42.cpp` & `test_throw42`: Case 2 测试程序源码与二进制
- `fixtures/runtime/badalloc-phase/test_dlopen_local.c` & `test_dlopen_local`: Case 3 主程序源码与二进制
- `fixtures/runtime/badalloc-phase/plugin_cpp.cpp` & `plugin_cpp.so`: Case 3 局部插件源码与共享库
- `fixtures/runtime/badalloc-phase/test_bad_alloc.cpp` & `test_bad_alloc`: Case 4 辅助函数测试源码与二进制
- `scripts/runtime/badalloc_phase/run_badalloc_phase_test.py`: 自动化 4 组自测试套件运行脚本
- `logs/badalloc-phase/phase_verification_summary.json`: 4 组用例全量运行结果汇总
- `reports/badalloc-phase.md`: 本报告

### 2. Lead 独立复验命令
```bash
# 执行 4 组自测试套件对比验证 (耗时约 1 秒，输出 PASS (ALL 4 CASES VERIFIED))
python3 scripts/runtime/badalloc_phase/run_badalloc_phase_test.py
```
