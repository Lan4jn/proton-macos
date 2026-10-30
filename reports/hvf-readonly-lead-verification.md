# HVF只读映射：总Lead原始证据复核（round13）

## 已证事实
- 读取原`probe.jsonl`逐项断言：单VM create0；A匿名hostRW→HV_RWX为0；B O_RDONLY/hostR→HV_R为0xfae94001；C同hostR→HV_RWX亦0xfae94001；D O_RDWR/hostRW→HV_RWX为0；destroy0。各成功map的unmap及各host munmap均0。
- 原`probe.log`明确唯一探针exit0、timed_out=False，种子前后SHA一致；本Lead另计算当前source/binary/seed摘要均与该日志一致：source eb7cd40a0a1e108734223d0b2d849ec5fdec3dbd1a655d196a2bd594bb52d81c；binary 3694ff312e47ac9d92e7bb8e1909d9d45d4d8c5cefbcb7e1062d81b6270e42d3；seed 1fde717d808c7e06c2e08ea843c4c8214ba82e63ff07ab731a2da3bd489e15de。
- 只读宿主页仅降低stage-2请求到READ仍未获准；不是权限不足的VM创建失败，也不是匿名/可写文件正对照不通。限当前宿主/SDK/四个case，不推出所有HVF版本均如此。
- 不执行guest/vCPU，本次API admission测试不是映射内容/coherence测试，不证明Wine已修复。

## 对初版独立报告的补充审查
- 原运行器会在已有seed路径上unlink，不符合不可覆盖约束。当前首次实测结果本身仍可由原JSONL/日志/摘要复核；禁止再运行该初版默认命令。
- 初版分类仅看JSONL，缺少实际进程exit/timeout/文件hash门控；缺字段/None/重复case也需fail closed。初版报告硬编码测试数和controls文字，不是通用可靠报告器。
- 总Lead已将这些具体问题交由另一Gemini实现+审查团队`86293fe0/267d2efa`纯测试修复，冻结原probe.c/bin/seed/JSONL/log与旧报告；禁止补跑新HVF。
- 前一团队根卡bfa2578c因Host子会话history follow地址失配而failed（ownResult=succeeded）；实现子卡有外部完成记录。保留该环境错误，不将其写成整树Host验收成功。

## 下一修复决策（尚未实施）
不采用“把private全改共享”或“只把HV_RWX降至HV_R”的捷径。若要支持只读文件实时更新，需要先设计由匿名可写host slab承载、guest READ保护、明确同步边界/更新机制的派生实现，或其它经微探针验证的backing方案；WRITE升级前私有化、MAP_FIXED/munmap防原file误写、fork/多线程与失败原子回滚都是前置验收。当前没有足够证据选择一个可用于全Wine的同步机制，不把轮询快照包装成完整Linux页缓存语义。
