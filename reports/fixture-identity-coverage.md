# 身份观测真实小控制矩阵（round27）

使用冻结ef7cd2a8...诊断binary，不改源码，不执行Wine。新增scripts/runtime/gdb_probe/test_fixture_identity_live.py，通过显式ELFUSE_LIVE_IDENTITY_TEST=1才执行。普通discovery自动skip，避免协议单元测试意外启动HVF。

| 实际guest写法 | stdout是否完整 | 身份检测 | 目标退出 | 时长 |
|---|---|---|---|---|
| write(1,marker) | 是 | 是 | 0 | 0.173744s |
| dup(1)后write | 是 | 否 | 0 | 0.156171s |
| writev两iov分割marker | 是 | 否 | 0 | 0.151679s |
| 两次write分割marker | 是 | 否 | 0 | 0.155942s |
| 无关输出 | 是 | 否（正确） | 0 | 0.159534s |

五个独立run均noTimeout/cleanup[]。测试是1个unittest方法内5个subcase，不宣称5项独立test-method PASS；断言当前检测边界，所以矩阵测试通过不等完整身份检测器已修复。机器可读原件logs/pe-identity-sample/coverage-v1/matrix.json，各run含argv和stdout/stderr；coverage-v1-tests.log。

普通discovery：原7项协议纯测试PASS，新增live项SKIP，合计8 tests/1skip；见pure-discovery.log。本轮没有新增重Wine超时或采样。

## 可支持结论
前轮Wine输出存在而metadata缺失，可以被已证实的dup、writev或分片覆盖缺口解释，但尚未确定实际Wine具体使用哪个。不能因此推断PE PID或等待函数。

## 最小下一设计
统一一个diagnostic scanner给sys_write与sys_writev使用：通过已pin的hostfd fstat与本run stdout输出对象身份比对，而不是guest fd必须1；跨iov/跨调用流式处理，限定字节预算、只输出固定marker身份、不输出任意payload；跨线程/跨fd对象切换须明确状态复位，phase=request不等write已成功。fastpath也需要覆盖；不得通过--verbose重跑解决。

先以原负例变为检测正例，并加入close/reuse、不同输出对象、边界截断/预算负例，然后才再执行唯一Wine采样。正确COW、Vulkan实例、原生Steam目标仍未完成，诊断版仍不得默认接入。

工具目录当前没有team_task/spawn_teammate/wait_agent，仅历史成员以inactive child可见；未使用临时子代理或新执行会话绕过要求。本轮限诊断测试兜底，独立审查未完成。真实Steam/global/accepted runtime不变，无commit/push。
