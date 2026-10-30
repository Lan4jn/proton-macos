# 执行级证据门控补验（round14）

本轮仅使用当前团队的既有lab-reviewer请求一次审查；该恢复会话仍失败、无closing。未创建新的任务板执行会话。以下为L1单点修复与Lead自检，新增修复独立复核仍欠缺。

- 发现并实际离线复现：底层`classify`在没有执行元数据或缺失一侧SHA时仍返回RO_HOST_MAPPING_REJECTED。原真实运行日志是完整的，不因此否定其HOST API数值；但它不应当作为最终执行验收入口。
- 新增`ProbeClassifier.classify_execution`强制要求四项参数：整数退出码（bool不冒充int）、bool超时状态、前后两项64位小写十六进制SHA。缺失/类型错/摘要格式错返回INCONCLUSIVE；完整证据再交给底层case分析，保留非零退出/timeout/hash不等门控。
- `run_probe.py`只改最终调用点为严格入口；未更改原probe.c、编译件、seed或原JSONL/log/report。底层classify保留作结构级分析，其结果单独不构成执行验收。
- 新增6个测试方法覆盖完整传递、逐字段None、参数遗漏、bool退出码、整数timeout和坏摘要；与既有32项共38项，Lead实际纯测试38 PASS。日志`logs/lead-round12/hvf-execution-evidence-tests.log`（目录沿用上轮，不改变本轮归属）。
- 用完整历史execution_metadata经严格入口离线重分类，仍为RO_HOST_MAPPING_REJECTED，0xfae94001。当前seed与原前后SHA、JSONL与原记录摘要再次匹配。结构化证据`logs/lead-round12/strict-execution-reclassification.json`含当前修改代码SHA。
- 未新运行HVF/Wine、未编译或重新签名。纯mock错误路径不等实际HVF失败注入。
- 原加固报告中“杜绝任何覆盖/安全完整”等绝对措辞不采纳：路径预检与后续open之间仍有同owner并发替换TOCTOU，日志/报告写入也不是全部原子排他。当前正常单次执行的不可重复保护与对抗性原子文件系统保证分开。

后续修复前置：只读宿主页HV_READ admission既已失败，需新的shadow或其它backing设计；不得将文件private全部改共享，也不得把定期pread同步写成完整Linux页缓存语义。下一项应限定具体Wine共享session mapping，并先取得真实映射flags/fd access/offset与生产者-消费者更新证据，再选同步边界。
