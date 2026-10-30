# vDSO / AT_SYSINFO_EHDR 与 x64 VA=0xf148 异常分析 (Task-108)

**结论**：elfuse 当前实现确实发布 `AT_SYSINFO_EHDR=0xf000`，并在该位置生成可执行的合成 AArch64 vDSO；`__kernel_clock_gettime` 的合法 `st_value=0x148`，所以入口 `0xf148` 是由 `vDSO_BASE + st_value` 正确得到，并非坏指针。最小 guest 测试经 libc 与直接入口调用均通过。原 x64 故障日志中 Stage-1 页表 walk 显示有效 PTE，但异常 syndrome 报 L3 translation fault；实际 fault 时硬件 TTBR0/TCR 未记录，故根因仍待观测。没有证据支持“忘记映射 vDSO”，本轮未修改默认映射路径或声称修复。

## 1. 源码事实与地址计算
- `src/core/vdso.h:22-23`：`VDSO_BASE=0x0000F000`，`VDSO_SIZE=0x1000`。
- `src/core/stack.c:309-312`：`vdso_base != 0` 时写入 `AUX(AT_SYSINFO_EHDR, vdso_base)`。
- `src/core/vdso.c:212-215`：`TEXT_OFF_GETRES=0x0EC`、`TEXT_GETRES_SIZE=0x5C`，因此 `TEXT_OFF_GETTIME=0x148`。`sym_text_off[]` 顺序为 sigreturn/getres/gettime/gettimeofday/getcpu（约第371-374行），dynsym `st_value` 由该数组赋值（第1113行）；clock_gettime 对应索引2，即 `st_value=0x148`。所以 `0xf000+0x148=0xf148`。
- `src/core/vdso.c:989-1018` 在 `g->host_base+VDSO_BASE` 构造 ELF64/AArch64 vDSO；PT_LOAD 标志 `PF_R|PF_X`（第1051-1060行），clock trampoline 于 `TEXT_OFF_GETTIME` 写入（第1091-1092行）。
- `src/core/bootstrap.c:294-319` 与 `src/syscall/exec.c:1098-1107` 把 `[0xf000,0x10000)` 注册为 `MEM_PERM_RX` boot region；`src/core/guest.c:3273-3290` 的 `make_page_desc()` 对 RX 不设 UXN/PXN。Stage-2 由 `guest_init` `hv_vm_map(..., HV_MEMORY_READ|HV_MEMORY_WRITE|HV_MEMORY_EXEC)` 创建；原故障报告所列 `HVF segment[0] ipa=0 len=0xe00000` 覆盖 `0xf148`。
- 因此，崩溃现场 `region: NONE` 是 region-tracker 缺项，不等于 Stage-1 未映射：`crashreport.c` 注释明确说 vDSO/shim 等非普通 VMA 可无 tracker 项。

## 2. 最小 guest clock_gettime 探针
新增 `scripts/runtime/vdso_probe/clock_vdso_probe.py`，在现有 baseline elfuse 下读取 auxv，再执行 libc `clock_gettime` 1000 次和直接调用 `AT_SYSINFO_EHDR+0x148` 1000 次。收据 `logs/vdso/clock-test-receipt.json`：`run_valid=true`, `exit_code=0`, `elapsed_seconds=0.204039209`，输出 `AT_SYSINFO_EHDR=0xf000`、`ENTRY=0xf148`、`LIBC_CLOCK_GETTIME_PASS iterations=1000`、`DIRECT_VDSO_CLOCK_GETTIME_PASS iterations=1000`、`VDSO_PROBE_PASS`。这证明 vDSO 地址和代码在此直接测试场景可执行。

## 3. option A 诊断试验：不发布 AT_SYSINFO_EHDR
在独立派生目录 `sources/elfuse-vdso-derived` 中只增加 opt-in 的 `ELFUSE_DIAG_DISABLE_VDSO_AUXV` gate；默认行为不变，仅诊断模式在初始栈省略 `AT_SYSINFO_EHDR`。该模式 guest 探针观测 `AT_SYSINFO_EHDR=0x0`，libc syscall fallback 的 clock_gettime 1000 次通过，收据 `logs/vdso/no-vdso-clock-receipt.json`，`run_valid=true`, `exit_code=0`。
同一派生运行时下又跑 x64 Vulkan 一次：`logs/vdso/x64-no-vdso-receipt.json` 记录 `exit=124`, `timed_out=true`, `stdout_bytes=0`, `has_step3=false`, `run_valid=false`，本次无 `VA=0xf148` exception。故 option A 能绕过 vDSO dispatch 测试路径，但 x64 探针仍未过 Step 3，不能作为修复或验收通过。其代价是所有依赖 vDSO 的 guest 时间调用降级到 syscall，未建议默认启用。

## 4. 原异常与非复现性：已确证 / 未决
- 原日志 `logs/x64-vk/run-t9qrkmmc/stderr.log:2435`：`EC=0x20 syndrome=0x82000007 VA=0xf148 PA=0xf148`；task-107 assessment 记录 `PC=X2=0xf148`，glibc `clock_gettime` 的间接调用链从 `_rtld_global_ro+0xe0` 槽读出目标后 `blr x2`。目标地址恰为合成 vDSO clock_gettime 入口。
- 页表诊断 `L0[0] -> L1[0] -> L2[0] -> L3[15]=0xf7e7 -> IPA 0xf148` 的索引和 IPA 与 `VA=0xf148` 自洽；`L3[15]` 是 valid page，按源码 `make_page_desc` 为 RO、可执行。Stage-2 backing 范围覆盖且具 EXEC。
- 但 syndrome 的 IFSC=0x07 表示 L3 translation fault，与 crashreport 从 `g->ttbr0` 镜像读到有效 PTE 相矛盾。crash dump 未记录 fault 时 VCPU 的实际 `TTBR0_EL1`、`TCR_EL1`，也未证明诊断读到的页表镜像与硬件当刻使用的 root/TLB 状态一致。故目前不能归因为 Stage-1/Stage-2 翻译缺陷，也不能断言 guest/FEX 指针错误；两个方向均待观测。
- task-107 fresh rerun 使用不同派生 runtime SHA `950406ca...`，仅到 Step 1 后超时，没有 `VA=0xf148` exception；最小直接 vDSO 调用亦正常。可确认的是故障具有运行情境依赖性；具体差异（loader/线程启动次序、exec 地址空间重建或活跃 TTBR0/TLB 状态）尚无字段支撑，保留为假设。

## 5. 最小修复选项与判据
| 选项 | 影响 | 本轮结论 |
|---|---|---|
| A. 不发布 `AT_SYSINFO_EHDR` | glibc 使用 syscall fallback；已在派生 runtime 验证 clock_gettime 1000 次通过，但 x64 probe 仍未过 Step 3，且会损失 vDSO fast path | 仅为诊断 toggle，不作为默认修复 |
| B. 映射可执行 vDSO 内容 | 确保 auxv 地址对应 ELF 与 RX trampoline；现有实现已生成 vDSO、boot region RX、Stage-2 映射含 EXEC，直接调用已通过 | 未发现“缺 vDSO 页/执行映射”可修项 |
| C. 记录 fault 时真实翻译上下文 | 在派生 `src/debug/crashreport.c::crash_report()` 输出 VCPU 实际 TTBR0_EL1/TCR_EL1 与相关 PTE generation/原始描述符，并关联 fault VA；对比当前 `g->ttbr0` PT walker | 下一步最小有效观测 |

## 6. 可反驳判据
- 若复现故障时实际 VCPU TTBR0/TCR 指向的活动 Stage-1 表中 `0xf000` 页无效/UXN，或 Stage-2 映射无 EXEC，则映射/权限缺陷成立，可按观测修复；
- 若活动 Stage-1 PTE 与 Stage-2 均可执行且页内容仍是预期 vDSO 指令，则静态 vDSO 映射缺陷被反驳，应检查 TLB/地址空间切换、异常上下文以及 `_rtld_global_ro+0xe0` 槽值来源；
- 若移除 `AT_SYSINFO_EHDR` 后同一 x64 运行达到 Step 3 且故障消失，表明 vDSO 路径与故障具有因果关联；当前 A 试验未达 Step 3，不能支持该因果结论。

**最终定性**：elfuse 在源码上已经构造、RX 映射并 auxv 发布合法合成 vDSO；clock_gettime 最小探针通过。原 x64 故障的 PTE/syndrome 冲突和运行不稳定性仍未定位。没有修改默认 vDSO 映射；x64 Vulkan probe 仍未达 Step 3。
