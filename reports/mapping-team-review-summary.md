# Wine共享会话映射与MAP_PRIVATE独立审查汇总

- 调度与执行：Lead协调独立reviewer子卡（`map-private-id-492e-87f3f9b8`），未另开无关成员；子任务完成纯单元测试与报告审查，无代码/运行时变更。
- 单元测试证据：执行 `python3 -B -m unittest -v scripts.runtime.private_map_coherence.test_probe`，7/7 PASS（exit 0，禁写pycache），日志见 `logs/private-map-coherence-review/tests.log`。
- MAP_PRIVATE观测核对：`linux.json`（elfuse模拟环境）与`darwin.json`（原生Darwin）均确认私有只读映射预触页后保持0，而shared_rw/shared_ro与文件值均为0x1234abcd（305441741）；两端现象一致。
- 语义边界：probe的exit 0仅表示探针诊断完成，非ABI语义完全满足；POSIX未保证MAP_PRIVATE可见后续文件修改，Darwin亦非原生Linux内核基准。
- 会话ID日志核实：`logs/wine-session-id/run-ibzwehco`中确有14条`warn:winstation:find_shared_session_object Session object id doesn't match expected id`警告，与首个类注册失败同线程相邻。
- 因果断言约束：Wine实际内存对象ID未被直接读取，未证精确包提交与生产/消费链路，时序关联不足以断言会话ID不匹配或stale为崩溃根因；因果关系保持未决。
- 只读private live overlay方案验收边界：
  1. 读阶段挂载live backing，但在`mprotect`追加WRITE或写操作前必须切入私有匿名COW快照，确保写操作绝对不回写原文件；
  2. `munmap`或`MAP_FIXED`覆盖时必须先解除文件别名再执行内存清零或重映射，严防误破坏底层文件；
  3. `O_RDONLY`文件描述符映射严禁使用底层RW SHARED提权路径，严格隔离16KiB宿主页与4KiB客户页；
  4. 多线程与fork必须保证quiesce互斥与原子性发布，中间步骤失败必须完整安全回滚旧映射；
  5. 必须具备覆盖上述边界的最小RED/GREEN测试矩阵，不可单凭当前7项分类测试宣布就绪。
