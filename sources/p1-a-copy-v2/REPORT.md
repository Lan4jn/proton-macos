# P1 A-copy：FINAL_UNVERIFIED / P1 NOT_READY

## 决策与边界

Lead批准v1合同与A-copy独立AppKit+Unix SOCK_STREAM CPU payload。最终结论为**FINAL_UNVERIFIED**：旧版host有有价值的子场景证据；修后最终版本没有重做1000帧和30秒整套；缺真实Linux guest→host transport。P1整体NOT_READY，不进入P2。CPU像素仅传输/呈现架构证据，不代表真实GDI、Wine、GPU、游戏通过。

范围：sources/p1-a-copy-v2、scripts/p1_a_copy_v2、tests/p1_a_copy_v2、logs/p1-a-copy-v2；原runtime/Wine/历史证据未改，真实Steam/系统/全局包未改，无commit/push。P0代码只读复用、绑定SHA。无guest runtime实跑。

## 合同

SPEC.md记录u32be长度、JSON及RGBA8 payload、host-owned双slot、generation、RECEIVED与唯一CONSUMED terminal（displayed/replaced/invalidated）、resize失效和错误边界。CREATE/RESIZE CONFIGURED与FRAME终态分开。捕获是自有NSView cache、opaque RGBA8/sRGB比较，不是桌面合成或人眼可见证据；跨时钟单程延迟UNKNOWN。

## 历史首full（不是最终binary整体通过）

命令 `python3 scripts/p1_a_copy_v2/probe.py --suite full`；整体exit 1，summary `logs/p1-a-copy-v2/run-c5ff6e5daa84/summary.json`。当时binary SHA256 **a85985e2f015f205800aa233e7270f51ee3c3b28d716fe7e95a41a05dab1b2bc**，source SHA256 **3233b895e0d646922a64cfaee60366a7a61734fc1a8f5545cd1c893cedf1b5e0**。逐case JSON含source/ACK/log SHA、目标退出和PID。

- correctness `run-512559a84b17/receipt.json`：runner/target exit0，1000个64×64变化帧，每帧RECEIVED、唯一CONSUMED、displayed及capture全像素相等；总16,384,000字节。
- throughput `run-793b7980d044/receipt.json`：runner/target exit0，30.003228708秒、900帧720p输入，3,317,760,000 payload字节，**生产者有效payload 110.5801 MB/s**；896 displayed、4 replaced（23,93,98,149），不是900显示帧。READY峰值1。生产者同域terminal RTT p50/p95/p99 20.792/39.170/47.353 ms；host本域接收至消费年龄9.630/18.189/19.927 ms。该轮无逐帧view capture；capture_all_match字段无样本时为真，不是像素验证。
- latest `run-8c4d9fb11fdc/receipt.json`：runner/target exit0，实际替换及唯一terminal详ACK；resize `run-74542067e99d/receipt.json` exit0，但不等同所有并发resize竞争组合均覆盖。
- busy `run-4854efd023bb/receipt.json`：native CPU纯算3001.258ms期间，预先ARM的AppKit主线程事件HANDLED ACK在producer忙算窗口内观察，host事件比计划晚15.055ms。独立busy-close `run-7f7ca84e8e4a/receipt.json`：3000.446ms忙算期间观察关闭HANDLED及EOF，host事件晚15.356ms。实验CPU host producer，不是guest。
- length、short、CRC、截断与disconnect子场景exit0；overflow、generation、duplicate子场景runner exit1：host提前ERROR，producer仍发送完整payload触发BrokenPipe，不能把这三项计作通过。原日志/收据保留，不能把full exit1涂成PASS。

## 修复及冻结版本

旧版出现两个治理问题：leader退出时同组孙进程泄漏；Popen后身份探测异常未登记。迁至已审P0 `scripts/runtime/session_v2/run.py` worker/cleanup适配，P0冻结SHA256 **3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b**；P0变动则拒绝加载并要求重审。适配范围独立于P0主runner：唯一目录、handshake前无身份不GO且无信号、P0身份核验清理、结果记录。fixture覆盖独立sentinel、父先退出的组内孙进程、身份探测失败和EPERM；EPERM不换信号通道。P0 worker 65秒inner超时不等于外层watchdog。**A适配器独立outer watchdog尚未实现**；旧full收据中的outer_timeout:false只是固定字段，非实测无超时，不得引用为外层监督通过。setsid逃离组、父进程被SIGKILL等不保证。半包无EOF时的reader和producer sendall也缺独立外层监督。

CRC对象旧版红例 `run-5ad00bb5ec9e`；capture对象旧版红例 `run-d6106ed73873`。修复为字段类型检查、CRC合法整数后再转换；metadata负测发送header，BrokenPipe必须额外观察ERROR方可认定拒绝。最终编译命令/退出见 `logs/p1-a-copy-v2/run-4e2a63efe2f2/build.json`，exit0，源码SHA256 **590b490cf6ed786f9bec340cd054744188fc249780ab5a1b89535ac5d6ef5da2**；二进制SHA256 **b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb**。此版本尚无1000/30秒复测，不能继承旧版完整验收。

本worker执行 `PYTHONPATH=tests/p1_a_copy_v2 python3 -m unittest test_contract.Governance test_contract.Wire test_contract.HeaderNegative test_contract.Busy -v`：8 tests OK exit0（修复后字段修改仅影响presenter，尚待reviewer定点）。独立reviewer已完成先前adapter Governance+Wire 5/5，证据 `logs/round1-v2/review/review-20261028T102002/a-governance-independent.json` 与对应log；该证据不等于A治理全门通过。最终binary协议边界与真实producer死亡EOF已交reviewer定点，结果以reviewer实际收据为准。

## 剩余门与建议

1. 独立reviewer审查最后binary和特定schema负测、producer实际死亡EOF；审查fail则保留FINAL_UNVERIFIED。
2. 增加独立外层watchdog与有界send/read、owned进程身份和异常退出证据，扩展负测覆盖后再执行最终binary完整1000帧和30秒验收；任何重跑独立新目录、同假设最多两轮，先经Lead批准预算。
3. P0放行后，另行设计最小可移植Linux C producer：在真实guest发送3,686,400字节RGBA8至host、CRC/ACK与有界持续吞吐；需核Linux工具链/sysroot和AF_UNIX真实连通、独立run目录与P0治理。须先估算与批准；本轮未构建、未运行，无法估算耗时和结论。
4. 前述证据与独立review通过后由Lead决定P1路线；P2 Wine HWND/GDI尚未开始。
