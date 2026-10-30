# P1 C-decoupled：线程证据与本轮决策

## 状态与范围

**DEFERRED_NOT_SELECTED**。Lead 于 2026-10-28 批准只封存静态证据、成本/收益决策与重开条件。当前优先验证 A 候选，A 尚未全门验收，不声明胜出。

C1 新线程可行性、fork/exec/close 生命周期、1000 帧和三秒纯计算 UI 响应均为 **NOT_RUN**。这不是技术 FAIL 或 HVF/macOS 平台不可行结论。一轮静态调查，runtime 零轮；未创建/迁移 vCPU，未编译运行 guest，未改旧 runtime/Wine/冻结证据。

新增范围仅本报告与 [静态证据目录](../../logs/p1-c-decoupled-v2/static-20261028-r1/manifest.json)。15 个输入的完整 SHA、逐行摘录及摘录 SHA 均在 manifest，manifest SHA256：`5875ab15c7961160ed513bed48b76974c4233168e9e5e35234166e49d113b7f8`。

## 已证：SDK 声明与当前源码调用链

以下“已证”只指静态声明/调用链，不是新线程运行验证。

| 事项 | 定位与结论 |
|---|---|
| HVF affinity | [SDK 摘录](../../logs/p1-c-decoupled-v2/static-20261028-r1/01-hv_vcpu.h.excerpt.txt)，hv_vcpu.h:19–39、358–381：create 为 current thread，每线程同时仅一 vCPU；run/destroy 必须 owning thread。run 阻塞到 exit/kick，hv_vcpus_exit 请求退出，不转移所有权。 |
| SDK身份 | xcrun alias实际为 MacOSX26.5.sdk；arm64 hv_vcpu.h SHA `5f5b8060fb21a70e800291dbd1069f7405c6354c93fab884475329ce136a4094`。不是x86 hv.h或仓库frama-c stub。 |
| normal launch | [launch](../../logs/p1-c-decoupled-v2/static-20261028-r1/03-launch.c.excerpt.txt):188–210、219–236、261–267；[bootstrap](../../logs/p1-c-decoupled-v2/static-20261028-r1/04-bootstrap.c.excerpt.txt):701–709。同步调用栈create→run_loop→join→guest_destroy，不是先create再交任意线程。 |
| guest leader身份 | [thread](../../logs/p1-c-decoupled-v2/static-20261028-r1/07-thread.c.excerpt.txt):141–174，slot0注册pthread_self，host_thread_needs_join=false，注释假设process main thread。整个launch放进worker也需重审leader/join生命周期。 |
| fork-child入口 | [main](../../logs/p1-c-decoupled-v2/static-20261028-r1/06-main.c.excerpt.txt):546–556；[forkipc](../../logs/p1-c-decoupled-v2/static-20261028-r1/08-forkipc.c.excerpt.txt):392–398、459–470、1655–1676、1708–1713。guest fork/clone使用posix_spawn自身+IPC与显式FD继承；child经独立fork_child_main创建新vCPU/注册leader。只改normal launch会漏child。 |
| owner teardown | forkipc.c:901–943；[guest](../../logs/p1-c-decoupled-v2/static-20261028-r1/05-guest.c.excerpt.txt):818–867。worker自己创建/销毁；join超时仍live则延后VM/slab销毁至process exit。AppKit thread不得代销毁活guest vCPU。 |
| guest exec | [exec](../../logs/p1-c-decoupled-v2/static-20261028-r1/09-exec.c.excerpt.txt):716–749，非leader exec交给guest leader，在其自己的vCPU运行。这不是host execve，不会据此自动重置AppKit/slot静态状态；新方案须明确exec generation失效与release。 |
| host fork风险 | [本地fork(2)](../../logs/p1-c-decoupled-v2/static-20261028-r1/02-fork.2.excerpt.txt):125–136，child在exec前仅做async-signal-safe操作，framework/library默认无post-fork继续使用保证。当前posix_spawn+IPC不是继承AppKit对象后继续执行；禁止换成fork后直接继续AppKit/HVF。未找到HVF post-fork可继续使用保证。 |
| 旧合作式UI seam | [syscall](../../logs/p1-c-decoupled-v2/static-20261028-r1/11-syscall.c.excerpt.txt):3015–3076；[present](../../logs/p1-c-decoupled-v2/static-20261028-r1/12-present.m.excerpt.txt):13–18、45–56。hook在syscall_dispatch，guard强制main，tick同步memcpy并泵事件；无syscall就无此UI调度点。三秒freeze来自既有报告，本轮未重跑。 |

SDK约束只绑定当前安装版本。源码SHA绑定当前派生树，不宣称与任意历史二进制逐字对应。初始git status在workspace根exit128（根无.git）；未据此声称git clean，也未commit。

## 三种路线与未实现的最小C1规格

1. **C1：main AppKit + 从创建起归属专属guest pthread。** 从尚未创建vCPU的新入口分派normal launch及fork_child_main；create/run/register访问/destroy全在owner。AppKit不接触guest指针；在guest合法提交seam校验范围后复制进host-owned slot，UI独立取slot。guest纯计算时main event pump不依赖safe point。关闭只发布状态与wake/kick，owner停止并销毁；main不得同步等guest同时guest等main。信号归属、exec/generation、join/error退出均未验证。
2. **C0：继续合作式main safe point。** 改动小，但既有三秒纯计算freeze不满足P1响应门；双缓冲不改变调度依赖。
3. **C2：guest维持原线程+外部AppKit。** 呈现形态变成A-copy，作为C实现无额外独立收益。

C1潜在收益仅省进程间传输，不是零拷贝：旧C有bitmap memcpy，新C为ownership正确仍需guest→host slot受治理复制。A的真实传输成本尚在测量，C的收益无数据。C1增加normal/child双入口、exec handoff、slot生命周期、join/teardown及信号假设回归面。因此本轮停扩实现，并非断言C成本必然超过收益。

## frame/ACK v1对齐

已与A worker/Lead对齐[共同合同](../p1-a-copy-v2/SPEC.md)，本次读取SHA `7b3019545d87c610b609a2a23d8f94c1401b83450cc2ff6491c95eb1b6246565`，24行摘录已封存。未来合同改变需重对齐。

C复用语义，不强制A wire：v1、sid、gen/seq正整数cap<=2^63-1；RGBA8/pitch/payload_bytes/CRC32；两host-owned slots，FREE→WRITING→READY→READING→FREE，READING禁覆写，最多一READY。RECEIVED只表示完整验证且host持有READY，不表示显示；每个RECEIVED唯一CONSUMED terminal，disposition=displayed|replaced|invalidated均release，只有displayed计显示。CREATE/RESIZE CONFIGURED与FRAME ACK分开；resize main-thread barrier等旧READING完成、旧READY invalidated，gen严格增加；旧代/重复seq/尺寸/CRC错误走ERROR+有界退出。close/EOF释放slots且<=3秒退出。correctness等terminal，实时latest-frame-wins记录replacements；同clock RTT，跨clock一程UNKNOWN。

## 重开条件与否决条件

重开须Lead明确确认，且有新收益依据：A实测传输/复制为目标瓶颈，或P2明确需要同进程能力而独立进程接口实证不足。仅理论更快不是新证据。P0独立review通过及Lead放行后，才考虑新树runtime实跑。

重开先确认两个public seams：owner lifecycle（normal/child/create/run/exec/destroy）与frame/ACK v1（slots/terminal release）；每个先负测再最小实现。保留1000变化帧CRC/sequence/ACK、720p30持续30秒分布/帧龄、guest三秒纯计算内预排UI/关闭响应、host/guest任一退出/断连/resize/unmap/exec失效的有界清理。单独HVF affinity微探针也不代替整条guest生命周期测试。

暂停条件：要求vCPU跨线程访问/销毁、guest与AppKit互等、非局部runtime/Wine重构却缺收益、同假设重复而无新证据。每假设最多两轮。

## 验证分层

- 实际工作：15输入SDK/source摘录与SHA封存；后续只读重算输入/摘录及行范围，并核4项冻结当前baseline未变。
- runtime/性能/功能测试：**NOT_RUN（0项）**。未启动HVF、guest、AppKit；无功能实现，不宣称TDD红绿或P1 PASS。
- 核查范围只有manifest列项，不是全仓递归审计；静态材料不证明C1生命周期可靠性。
