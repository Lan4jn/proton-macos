# 共享会话因果对照与Vulkan分层结果（round20）

## A/B/A'实际对照

| 配置 | 二进制 | DPI/目标退出 | session ID mismatch | 时长 | timeout/cleanup |
|---|---|---|---|---|---|
| A：身份observer，无语义干预 | 3bd19d04... | 96/38 | 14 | 39.529472s | false/[] |
| B：候选shared别名诊断gate开 | 60f87660... | 96/38 | 0 | 39.309300s | false/[] |
| A'：与B相同binary，gate完全移除 | 60f87660... | 96/38 | 14 | 39.217388s | false/[] |

三者独立COW前缀来自同一wine-session-id/pfx基底。A'/B native开关是主要变量；不同独立prefix及运行时序仍不是严格随机化统计对照。A'没有干预marker、B四条marker命中同inode。原件run收据：logs/mmap-file-identity/wine-result.json、logs/mmap-intervention/result.json、logs/mmap-reversal/result.json。

这组可逆干预证据支持选中候选映射的更新不可见造成已观察ID mismatch。尚未把inode与Wine对象名、实际expected/actual内存id直接绑定，不能写成完整共享内存子系统已修。

## Vulkan单次增量验证

logs/mmap-intervention-vulkan/result.json/run-b5wutvm2：同60f87660...、gate开、新独立prefix，原ARM64 vk_enum_arm64.exe SHA f82f4e7987ae1dc4ef20674c2f24809b4e7c88bbd4b902fb754a8dc0a8ec6b62及原ICD配置路径。

- 六个进程干预marker指向同一unlinked inode；session ID mismatch=0。
- 目标成功LoadLibrary及GetProcAddress，Step3调用vkCreateInstance后仍未打印返回。
- trace:vulkan显示vulkan_init_once已列出宿主实例扩展；这是扩展初始化可达，不是目标实例已创建。warn报告部分扩展不支持，不能据此单独归根因。
- outer70.121939s超时，overall124、target_exit=null、timed_out=true、cleanup_errors=[]。Linux软件Vulkan已通不推出此Windows桥已通。
- 日志末有get_shared_desktop/get_shared_queue观测，证明干预后部分会话读取路径可达；USB/driver错误与其它等待仍需区分。无DISPLAY情况下的桌面/驱动初始化、IPC/同步是下一候选，未证排他根因。

## 正确性与交付门

**60f87660实验版故意丢失候选PRIVATE写隔离，不是ABI修复，也不是产品运行时。** 没有接入backend运行时允许列表、Steam prepare或默认配置。严禁把14→0当作可用游戏/图形证明；仍需guest只读保护/首次写COW或其它正确实现，并验证mprotect、fork、多线程、MAP_FIXED/munmap、16KiB/4KiB与失败原子回滚。固定长度筛选只是诊断选择器，不是可靠会话类型识别。

round20纯回归：backend63 PASS（5.683s），HVF证据/运行器38 PASS（0.018s）；日志logs/mmap-intervention/{backend-regression,probe-regression}.log。这些不是实际guest COW测试。

最后重新计算accepted runtime06、诊断binary60、派生与原包Proton脚本四项SHA均符合冻结值；原上游sources/elfuse git status clean，见logs/mmap-intervention/integrity-final.json。没有修改真实Steam/全局包、没有commit/push。

## 未完成与下一步

1. 正确的Linux live-private/COW兼容实现尚未实现；本次不把诊断干预当修复。
2. Vulkan实例返回、Windows设备/渲染、Metal/Apple GPU、真实原生Steam识别/Play/Steamworks/游戏均未通过或未测。
3. Valve来源的精确ARM64二进制认证仍未闭合；现公开seed仅发布者声明+摘要。官方源码与日期候选Wine引用已取得，后续源码构建须另标self-built不冒充官方分发物。
4. 当前团队既有成员恢复失败；round20独立审查恢复无closing，缺独立复验，不以任务板另开会话绕过用户限制。
5. 后续先定位gate开后vkCreateInstance的具体等待/桌面驱动入口，不重复同一70s超时；正确COW设计与实现需独立工程及验收，不在本报告伪装完成。

总目标保持active而非complete。本阶段有可复现的新因果证据和代码，但整项产品目标尚未达成。
