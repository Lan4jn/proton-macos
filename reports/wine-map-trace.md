# 原生Wine实际映射跟踪（task59 / round17）

## 执行与范围
当前团队proton-integration-worker恢复以task ready失败，未claim且无工件；本任务有限单次诊断由Lead接手。未新建团队或任务板执行会话。

冻结runtime06a2fceb...，新COW前缀fixtures/runtime/wine-map-trace/pfx，原ARM64 probe-1.exe，新增--verbose和WINEDEBUG=+timestamp,+winstation,+virtual；内60s、外65s，只执行一次，无Vulkan调用。

## 原始结果
- logs/wine-map-trace/result.json → run-bee9k65n：47.976382s，overall38、target38、timed_out=false、cleanup_errors=[]。stdout四个阶段标记齐全，DPI_RETURNED=96。
- 同样14条Session object id mismatch；首条在stderr第4872919行，0068线程/expected1。不把返回96当共享会话缺项已解。
- trace实际435648689字节、5617943行；保留原件，未生成第二份完整副本。工具展示只流式提取有界摘要。
- trace-summary.json统计匹配到的非anonymous、非-1 fd请求：RW+PRIVATE|FIXED（prot3/flags0x12）1427条；RW+PRIVATE（0x2）10条；另含库加载RW+PRIVATE|FIXED|DENYWRITE（0x812）125条。计数是匹配到的请求数，不是成功映射数、独立文件数或完整覆盖。
- 对象名__wine_session未在已收日志中观察到；trace只给指针、数字fd与6参数，不能推出fd访问模式、文件inode/path或跨进程对应关系。来自多个进程的行可能交错，日志无可靠per-process关联；不把相邻mmap归为同一section。
- first-mismatch-context.json保留首警告前14个相关mapping事件及行号，只属时间上下文，不作因果绑定。

## 验收结论
本次观察证明实际运行包含Wine式RW-private请求，未完成“会话文件fd/access/offset”的身份闭合；完整ABI修复与Wine因果仍未证。trace增加了开销，运行时延不可与未跟踪run作等价性能结论。禁重复全量verbose；下一观测应在独立派生runtime mmap入口做有上限的host PID、dev/inode、host F_GETFL、guest flags/prot/offset记录，并只针对需要的文件映射；原accepted binary保持冻结。日志只读扫描不能替代内存object-ID读取或更新生产者/消费者绑定。
