# x64 探针 VA=0xf148 间接跳转来源追踪报告 (Task-107)

性质：独立派生运行时的只读崩溃观测与复跑；不修改 accepted 运行时或既有收据。
派生运行时：sources/elfuse-crashdump-derived/build/elfuse，SHA256 950406ca87a944bf8067a398da4865cc963bdf96b41f6c6d0171dffd15dcccb2。
基底运行时：sources/elfuse-once-backtrace-derived/build/elfuse，SHA256 2d0b901d13adcdd459ece4b9827db06096f2fde7b7e3ebf60c88d0802b0448a6。
Probe：scripts/runtime/x64_vk/vk_enum_x64.exe，SHA256 d408405ca8340342a08e6e44ddaccc8ad78d25570bea5a523a4b10067a87dc08。

## 1. 只读观测实现
仅在独立派生树 src/debug/crashreport.c 增加 dump_f148_source_observations()，并由 crash_report() 的寄存器区调用。仅当 live PC==0xf148 执行；读取 PC、X2、X30/LR、SP_EL0，经 guest_read_small 有界只读导出 LR 前 6 条、LR 本条及后 4 条 AArch64 指令 word，以及 SP 起始 64 字节。读取失败仅记录错误码，不改 guest 内存、寄存器、页表、信号或调度状态。构建成功。相对回溯基底仅 crashreport.c 有约 57 行新增观测代码。

## 2. 同一 x64 探针复跑与有效性
复跑脚本：scripts/runtime/x64_f148/run_x64_f148.py。复用同一 x64 probe SHA、logs/vulkan-null-driver/result.json 的 argv 模板、同一 sysroot、诊断环境与 futex-args-vulkan/pfx 的前缀内容副本；使用独立前缀目录。收据：logs/x64-f148-trace/receipt.json，运行目录 logs/x64-f148-trace/rerun/run-mv9wycvr。
本次物理结果：exit=124，timed_out=true，耗时 62.479596 秒；stdout=241 字节，stderr=529,649 字节。stdout 原文：
    [WIN_X64_VK] Starting Windows x64 Vulkan Enumeration Test
    [WIN_X64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
本次未到 Step 3；stderr 中 VA=0xf148 命中 0 次、unexpected exception 命中 0 次、新增 X64_F148_READONLY_TRACE 命中 0 次。因此针对“同 VA 复现并采得现场”的任务门槛，本次 run_valid=false。新 helper 未触发，未取得新的现场 LR 窗口或 SP 64B 栈切片。不得把旧 receipt 当作本轮新观测；logs/x64-f148/receipt.json 仅作为历史现场参考。

## 3. LR 静态指令窗与 X2 操作数链
由于本次没有复现故障，以下为同一 arch-case sysroot libc.so.6 的离线反汇编，而非本轮 crash-time dump。文件 SHA256 6ab264fb4e8df9942b0fb75b48fcd5c30b2f081d8dfaa6c25d7be1d3fce5b2ab，BuildID d04ac300b73a24e0e38fb7ff1dd34e91c77b16ed。归档：logs/x64-f148-trace/libc_lr_window_0xbf0e0.txt。
历史 fault receipt 中 LR=0x2000ff0fc、libc_base=0x200040000，因此文本偏移为 0xbf0fc。对应指令窗：
    0xbf0e0: adrp x2, 0x1bf000
    0xbf0e4: ldr  x2, [x2, #0xe80]   ; effective address 0x1bfe80
    0xbf0e8: ldr  x2, [x2, #0xe0]    ; from structure pointer + 0xe0
    0xbf0ec: cbz  x2, 0xbf108
    0xbf0f0: stp  x29, x30, [sp, #-0x10]!
    0xbf0f4: mov  x29, sp
    0xbf0f8: blr  x2                ; indirect branch/call
    0xbf0fc: cbnz w0, 0xbf13c      ; historical LR exactly matches return PC

libc.so.6 的重定位表在 0x1bfe80 标记 R_AARCH64_GLOB_DAT _rtld_global_ro@GLIBC_PRIVATE。由此，静态操作数链为：ADRP 形成页基址 → GOT 槽 0x1bfe80 取 _rtld_global_ro 指针 → 0xbf0e8 从该结构指针偏移 +0xe0 载入 X2 → 0xbf0f8 的 BLR X2。历史故障快照曾有 PC==X2==0xf148，故若该历史现场对应此链，0xf148 是 `_rtld_global_ro+0xe0` 槽的内容；它不是分支指令里的立即数，也不是 Stage-1 页表计算产物。
该地址是 libc 导出 clock_gettime / __clock_gettime 函数范围内的间接调用路径，因此该槽很可能是运行时 vDSO clock_gettime 回调槽；库 stripped，未取得该结构的 DWARF 类型，本报告不把具体 C 成员名当作确证。由于本次目标异常未复现，运行时槽内容、初始化写入者与 SP 栈链尚未新捕获。

## 4. 来源归属判断与可反驳条件
已确证（历史寄存器快照 + 静态代码链）：历史 fault 的 PC=X2=0xf148，LR 对应 libc+0xbf0fc；同一 libc 在 LR 前 4 字节为 BLR X2，X2 的静态末次装入为 libc+0xbf0e8 从 _rtld_global_ro+0xe0 取值。历史页表换算自洽。
暂定归属：其他——guest glibc 的 rtld-global 间接回调槽含坏值的假设最贴合当前静态链；尚不能区分该槽未初始化、被错误写入、vDSO 解析/安装异常，或更早的 guest 状态破坏。现有证据不支持将其直接归为 Wine 自身函数指针，也未显示 FEX 翻译产物把有效分支目标翻译错；但 FEX/启动层导致该字段被写坏仍待验证。
可反驳条件：若新的 crash-time trace 显示 X2 在 libc+0xbf0e8 之后另有写入，则本操作数链归因被反驳；若现场证明 _rtld_global_ro+0xe0 不等于 0xf148，则该槽来源假设不成立；若拿到该 libc 版本的 DWARF/匹配 glibc 源码证明 +0xe0 不是 vDSO 调度成员，须修正成员语义；若 X2 现场有效而最终 PC/IPA 被翻译到 0xf148，则重开 FEX/elfuse 翻译归属。

## 5. 证据与边界
新派生运行时 SHA256：950406ca87a944bf8067a398da4865cc963bdf96b41f6c6d0171dffd15dcccb2；基底 accepted 回溯运行时 SHA256 仍为 2d0b901d13adcdd459ece4b9827db06096f2fde7b7e3ebf60c88d0802b0448a6。原始复跑 stdout/stderr 留在 logs/x64-f148-trace/rerun/run-mv9wycvr/；汇总收据 logs/x64-f148-trace/receipt.json。仅 sources/elfuse-crashdump-derived/src/debug/crashreport.c 有源码改动。
结论：本次同探针复跑没有重现 VA=0xf148，故没有新栈切片或新 crash 时指令观测。静态指令证明目标操作数来源链指向 _rtld_global_ro+0xe0；具体坏值写入者仍待故障现场复现确认。本报告不宣称来源已完全坐实。
