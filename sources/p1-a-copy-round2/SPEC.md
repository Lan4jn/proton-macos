# P1 A-copy round2：监督规格（Lead 已批准）

只读绑定 P0 parent/worker/cleanup SHA256 `3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b`，最终 presenter SHA256 `b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb`。复用 P0 主入口并只覆写 LOGS，不改原模块。外层 parent 独立于同一 owned session；worker 保留 leader 并核验 identity，先注册并握手，再 GO。probe 与 host 使用普通 Popen，继承 worker PGID，不执行 setsid；记录各 role PID/start identity 及 group。禁止使用旧 probe 中启动独立 session 的 OwnedSession。

frame/ACK v1 原合同不变。客户端采用非阻塞 select + 单调 deadline 累积完整 send/read：真正大 payload 背压、半包不断线、永不 ACK 均独立可测。内层报 phase/timeout；外层 total deadline 即使 probe 卡住也独立触发，身份确认后组 TERM→限时 KILL；登记信号、对象、result、剩余组成员，cleanup 失败令 runner 非零。身份或权限缺失标 UNKNOWN/FAIL，不另走其他信号途径；不声称外层自身 SIGKILL 或目标脱组受治理。

第一关：唯一目录拒绝、无关 sentinel 存活、外层超时下组内 probe 与 host 同时清理、组内孤儿、内/外超时区分、半包/无 ACK/大 payload 真背压、host/producer异常、身份/EPERM，独立 reviewer 审查通过才运行最终二进制 host-only 全回归。第二关：1000变化帧每帧 CRC/自有 view/唯一 terminal；30秒720p30记录输入与显示、替换seq、producer RTT及host年龄分布；latest、resize、预排事件及单独关闭、断连。新日志含真实命令/roles身份/退出/cleanup/SHA，所有旧证据只读。CPU payload非真实 Wine/GDI；不启动guest、不进P2。
