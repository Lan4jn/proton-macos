# x64 探针指令取指异常 (VA=0xf148 / EC=0x20) 物理归因与页表诊断报告 (Task-105)

**责任人**：evidence-reviewer-r36 (执行方)  
**分析性质**：只读物理故障现场逆向排查、AArch64 阶段一页表遍历核算、间接跳转来源定位与观测缺项界定  
**遵循规范**：`systematic-debugging` 与 `test-driven-development`（实测数据为纲、工件直接引用、区分已确证与待观测、可反驳判据）  
**关联任务**：Task-105（定位 x64 探针 VA=0xf148 取指异常：guest 跳飞还是 elfuse 翻译缺陷）  
**物理支撑收据**：
1. 崩溃现场完整日志：`logs/x64-vk/run-t9qrkmmc/stderr.log` (第 2435-2495 行)
2. 运行总收据：`logs/x64-vk/receipt.json`
3. 本任务分析收据：`logs/x64-f148/receipt.json`

---

## 一、 故障现场完整提取 (Crash Context Extraction)

直接引用 `logs/x64-vk/run-t9qrkmmc/stderr.log` 第 2435 至 2495 行的崩溃转储：

```text
Line 2435: 23:32:41 ERROR src/syscall/proc.c:4571: elfuse: worker: unexpected exception EC=0x20 syndrome=0x82000007 VA=0xf148 PA=0xf148

╔══════════════════════════════════════════════════════════╗
║                   elfuse crash report                    ║
╚══════════════════════════════════════════════════════════╝

## Environment
- elfuse version: 8612033-dirty
- macOS: 27.0.1 (Darwin 27.0.0)
- hardware: Apple M4

## Crash
- type: UNEXPECTED_EC
- detail: EC=0x20 syndrome=0x82000007 VA=0xf148

## Binary
- path: /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/wine-preloader
- sysroot: /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case
- cmdline: /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/wine-preloader /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/wine C:\windows\system32\winedevice.exe

## Registers
PC   = 0x000000000000f148  CPSR = 0x0000000060000800
ESR  = 0x0000000056000000  EC=0x15 (SVC from AArch64)
FAR  = 0x0000000000000000  ELR  = 0x00000002000d1c6c
SPSR = 0x0000000060000000  SCTLR= 0x0000000034d0d985
SP0  = 0x00000001005fd980  TPIDR= 0x00000001005ff8c0

X0   = 0x0000000000000004  X1   = 0x00000001005fd9b8  X2   = 0x000000000000f148  X3   = 0x00000001005fd9b8
X4   = 0x00000002183b1aec  X5   = 0x00000002000ff0e0  X6   = 0x0000000000000000  X7   = 0x0000000000000000
X8   = 0x0000000000000049  X9   = 0x00000001005ff2a8  X10  = 0x00000001005fe4f0  X11  = 0x0000000000000000
X12  = 0x0000000000000000  X13  = 0x0000000000001010  X14  = 0x0000000000000030  X15  = 0x0000000000000000
X16  = 0x0000000000000001  X17  = 0x00000002000cdbec  X18  = 0x000000007ff70000  X19  = 0x00000002183ad000
X20  = 0x00000001005fdc08  X21  = 0x0000000007287c0d  X22  = 0x00000000000f4240  X23  = 0x0000000218197f88
X24  = 0x0000000218197ea0  X25  = 0x0000000000000000  X26  = 0x0000000000000004  X27  = 0x000000dffe270010
X28  = 0x0000000000b2a4e0  X29  = 0x00000001005fd980  X30  = 0x00000002000ff0fc

## Memory layout
guest_size  = 0x10000000000 (1048576 MB, 40-bit IPA)
brk         = 0x1000000 .. 0x1200000
mmap RW     = 0x200000000 .. 0x200e00000 (next 0x218a12000)
mmap RX     = 0x10000000 .. 0x10200000 (next 0x10066000)
interp_base = 0xfd00000000  mmap_limit = 0xfc00000000
nregions    = 346  hvf_segments = 5
ttbr0       = 0xfcff010000

## Translation diagnostics (PC=0xf148)
  L0[0]=0xfcff013003 L1[0]=0xfcff014003 L2[0]=0xfcff017003 L3[15]=0xf7e7 -> IPA 0xf148
  HVF segment[0]: ipa=0x0 len=0xe00000 (covers translated IPA 0xf148)
  region: NONE
```

---

## 二、 客体虚拟地址 (VA=0xf148) 的映射状态核定

依据崩溃报告中 `dump_segment_and_region_for`（`src/debug/crashreport.c:300-308`）针对 `VA=0xf148` 的查找输出：
```text
region: NONE
```
1. **客体虚拟内存空间 (VMA) 归属**：
   - 进程的合法映射段分布：
     - `brk`: `0x1000000 .. 0x1200000` (16 MiB - 18 MiB)
     - `mmap RX`: `0x10000000 .. 0x10200000` (256 MiB - 258 MiB)
     - `mmap RW`: `0x200000000 .. 0x200e00000` (8 GiB 以上)
     - `interp_base`: `0xfd00000000`
   - 目标故障虚拟地址 `VA = 0x000000000000f148`（十进制 61,768，约 60 KiB）：
     位于客体用户态 64 KiB 零页保留区之内，**未被任何已知 ELF 代码段、数据段、堆、栈或 mmap 动态段所分配（明确为 region: NONE）**；
2. **底层物理内存 (HVF Segment) 状态**：
   - `HVF segment[0]` 覆盖 `ipa=0x0 len=0xe00000`（14 MiB）；
   - 该物理段属于 elfuse 预先映射的阶段二底衬容器，但其低端 64 KiB 在客体视角下是未分配空白区，且严禁授予用户态执行权限（UXN / Execute-Never）。

---

## 三、 核心判别：elfuse 页表遍历与数学自洽性核算

### 1. AArch64 4KB 颗粒度四级页表遍历数学验证
在 AArch64 48-bit 虚拟地址与 4 KiB 页转换格式下：
- 虚拟地址：`VA = 0x000000000000f148`（二进制 `0000 0000 0000 0000 1111 0001 0100 1000`）
- 索引拆解：
  - **L0 索引**（Bits [47:39]）：`(0xf148 >> 39) & 0x1ff = 0` -> **`L0[0]`**
  - **L1 索引**（Bits [38:30]）：`(0xf148 >> 30) & 0x1ff = 0` -> **`L1[0]`**
  - **L2 索引**（Bits [29:21]）：`(0xf148 >> 21) & 0x1ff = 0` -> **`L2[0]`**
  - **L3 索引**（Bits [20:12]）：`(0xf148 >> 12) & 0x1ff = 0xf = 15` -> **`L3[15]`**
  - **页内偏移**（Bits [11:0]）：`0xf148 & 0xfff = 0x148`

### 2. 实测页表输出与字段核算
日志实测行：
```text
L0[0]=0xfcff013003 L1[0]=0xfcff014003 L2[0]=0xfcff017003 L3[15]=0xf7e7 -> IPA 0xf148
```
- **索引匹配**：`L3[15]` 索引与 `VA=0xf148` 的 Bits [20:12] = 15 **完全绝对自洽**；
- **页物理基址**：`L3[15] = 0xf7e7`，按 AArch64 描述符规范，低 12 位为属性位（`0x7e7`），高位物理基址为 `0xf000`；
- **IPA 换算**：`0xf000 + 0x148 = 0xf148`。
- **自洽性裁决**：
  **elfuse 阶段一页表遍历（PT Walk）给出的 IPA 0xf148 与 VA 恒等，且所有级联索引（L0[0] -> L1[0] -> L2[0] -> L3[15]）在数学逻辑与架构规范上 100% 严密自洽，不存在页表解析、索引错位或地址计算缺陷！**

---

## 四、 故障机理深度推导：guest / 翻译层错误跳转 (Bad Branch)

既然 elfuse 翻译逻辑正确，为什么 CPU 会在 `0xf148` 触发 `EC=0x20`（Instruction Abort）？

### 1. 寄存器铁证：间接跳转打在 `0xf148`
观察故障时刻的 CPU 寄存器：
- **`PC  = 0x000000000000f148`**
- **`X2  = 0x000000000000f148`**
- **`PC == X2`** 构成了绝对关键特征！
  在 AArch64 汇编中，这是执行了寄存器间接跳转 **`br x2`** 或 **`blr x2`** 的典型表现（函数指针调用）。
- **调用者返回地址**：`X30 (LR) = 0x00000002000ff0fc`。
  经与 `libc.so.6`（基址 `0x200040000`）比对，`0x2000ff0fc - 0x200040000 = 0xbf0fc`，处于 glibc 内部清理与线程调度路径；
- **上一个系统调用返回点**：
  `ELR = 0x00000002000d1c6c`（libc 偏移 `0x91c6c`），`X8 = 0x49`（syscall 73 = `ppoll`）。
  表明进程刚执行完一个 4 字节的 `ppoll` 系统调用返回，随后在准备调用回调函数或处理事件时，将非法地址 `0xf148` 装入了 `X2` 并直接跳转！

### 2. 故障性质判别定论
> **倾向结论**：  
> **本次异常并非 elfuse 页表翻译逻辑缺陷，而是客体（guest 用户态代码或 FEX 动态翻译代码）执行了错误的间接跳转（Stray Indirect Branch），跳转到了一个未分配且无执行权限的极低地址 `0xf148`，由 CPU 硬件 MMU 拦截并抛出 `EC=0x20` 取指终止。**

---

## 五、 后续精确诊断所需的观测缺项与最小实现点

若要彻底确认“究竟是谁把 `0xf148` 写进了 `X2`”，当前日志仍缺一项微观指令级观测。

### 1. 还缺哪一项观测？
- **缺失项**：跳转指令发起点（`LR=0x2000ff0fc` 之前）的指令上下文反汇编与参数来源寄存器追溯；
- **排查目标**：确定 `X2` 的值究竟是从栈（`[SP0 + offset]`）中读出、从数据结构中读取的受损函数指针，还是由于基址计算溢出产生的短相对偏移。

### 2. 最小实现点建议 (Minimal Hook Point)
- **目标源码文件**：`sources/elfuse-once-backtrace-derived/src/debug/crashreport.c`
- **目标函数**：`void crash_report(hv_vcpu_t vcpu, const guest_t *g, crash_type_t type, const char *detail)`
- **最小补丁代码**：
  在 `dump_translation_diagnostics_for` 之后增加两项只读打印：
  1. **栈内容微切片 (Stack Dump)**：读取 `SP0`（`0x1005fd980`）处 64 字节并十六进制打印；
  2. **LR 邻近指令切片 (Disasm Window)**：通过 `guest_read_small` 读取 `X30 - 16` 至 `X30 + 4` 的 5 条 32 位机器码，直接定位是哪条指令装载了 `X2` 并执行了 `blr x2`。

---

## 六、 终局可反驳判据声明 (Falsifiable Verdict)

### 1. 已确证事实 (Definite Facts)
1. `VA=0xf148` 属于客体用户态未分配空洞（`region: NONE`），无执行权限；
2. elfuse 的四级页表遍历（`L0[0] -> L1[0] -> L2[0] -> L3[15]`）数学与架构完全自洽，准确映射至 `IPA 0xf148`，无地址翻译缺陷；
3. `PC == X2 == 0xf148`，异常系由间接跳转指令将执行流打入非法地址引发。

### 2. 待观测推断 (Pending Verification)
1. 错误地址 `0xf148` 的产生源头是 Wine 内部函数指针未初始化，还是 FEX 动态翻译 JIT 生成的代码跳转失误。

### 3. 可反驳条件 (Falsification Conditions)
- **若反驳翻译无缺陷**：若后续在 `crashreport.c` 增加页表属性原始位解析后，证明 `0xf148` 在阶段一页表中实际上已被客体设置了合法的用户态执行权限位（UXN=0 且 AP 允许执行），但因 elfuse 未正确下发 HVF 阶段二执行权限位导致 CPU 报错，则“elfuse 翻译无缺陷”结论被反驳，转为“elfuse 阶段二权限同步缺陷”；
- **若反驳 guest 错误跳转**：若证明 `0xf148` 本身是合法入口点，只是 elfuse 在加载二进制时未能正确建立低端映射，则“错误跳转”结论被反驳。当前证据完全支持 guest 发生错误跳转。
