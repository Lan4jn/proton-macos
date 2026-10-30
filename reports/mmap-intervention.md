# 候选共享会话文件的因果干预（task61 / round19）

**不是ABI修复，不接默认后端。** 此实验有意牺牲选中映射的PRIVATE写隔离，仅用于检验文件更新可见性与会话ID警告的联系。

## 单变量改动
从3bd19d04 observer构建独立复制至sources/elfuse-map-intervention-derived；只有mem.c的sys_mmap入口增加显式native envgate ELFUSE_DIAG_SESSION_SHARED。仅nonanonymous、prot=RW、PRIVATE、length=0x144000、offset=0、实际fd O_RDWR且regular/nlink0才改为SHARED；flags变更在track_flags计算之前，后续全部走既有shared覆盖/清理/回滚路径，不留下private metadata伪装。未修改Wine、原Proton或原accepted runtime。

没有匹配时不改flags；env只是存在性开关，字符串0仍算打开，关闭须删除变量。借用独立hostfd_ref核inode/access后关闭；额外访问有时序扰动及短暂重新取得fd的竞态边界，实验非通用正确性证明。筛选size不是可靠的对象类型认证。

patch：logs/mmap-intervention/intervention.patch；build.log显示本轮只编mem.c、link/sign，git版本探测fatal消息保留（派生目录无.git），make总体0。
二进制SHA60f87660402bebb81f12ba179fb02501f7d188c5dd5c878afe9e3c604944197b；mem.c SHA1ff802ca16d7f591e67d384422245bf03685342deeccd8a9516b29a15ff80354。

## 原始结果
logs/mmap-intervention/result.json/run-4_xzpku_：39.3093s、overall38/target38、timed_out=false、cleanup_errors=[]、DPI_RETURNED=96。
恰4条DIAGNOSTIC_SHARED_ALIAS_NOT_ABI_FIX标记，pid17823/17829/17794/17790命中同dev16777229/inode17184353、oldflags0x12/len0x144000。
Session object id mismatch计数**0**；前一observer独立clone同DPI基线14条，原始logs/mmap-file-identity/wine-result.json/run-gg3q95rt。stderr6504B。

## 可支持与不可支持的结论
- 定点共享别名干预使这些会话ID警告在本次运行消失，支持候选映射可见性缺项与该警告的因果联系；已超越仅静态源码与时间邻近。
- 尚缺同binary关gate的反向A'对照、直接绑定section名、内存id以及独立队员复验；不能宣称排除了全部混杂或具体页面级COW机制已正确。
- 没有Vulkan/图形/游戏执行，本次DPI以前也能返回96，不能把同样exit38说成新产品能力通过。
- 绝不接受此flags替换为正式修复：必须实现更新可见且首次private写隔离的机制，并测试线程/fork、16KiB与4KiB、MAP_FIXED/munmap防文件回写、故障回滚；此实验版不安装、不接后端，不泛化到其它同size文件。
- 当前团队proton-darwin-research恢复无closing失败，未claim或产出；Lead仅对此单次因果实验兜底。未创建新执行会话，无global/Steam/commit/push。
