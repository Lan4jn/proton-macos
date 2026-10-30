# 官方Proton与Wine源码对齐（round16）

- 用户明确指出官方项目 https://github.com/ValveSoftware/Proton.git 。本轮以官方API直接读取子模块，不继续将wine-mirror/wine-11.0当作唯一源码依据。
- 原公开包`version`实际为`1790245028 experimental-11.0-20260924-arm64`，时间字段转换为2026-09-24T10:17:08Z；原ntdll.so仅检出wine-11.0，没有认证的Git SHA，SHA d2d734b53183750f27bd0c7a4093b6665fc94947a38d1bc444411fe6c85fc296。
- 当前官方experimental_11.0分支为7a94df49e4695fc101fd47d614166e69c43d9669，对应Wine子模块7fc704ef49c50e9702c9983a5250d5738697bb04；当前proton_11.0默认分支bc896217...对应Wine e60892cc...。二者都不自动等于旧包来源。
- 按experimental_11.0提交时间<=2026-09-25查询，最新候选Proton为58a40f82ec1a67887feeb806cf53aa81f1d07249（2026-09-23T19:36:19Z），对应官方Wine子模块dc26e61847081a1b5cb0733dc30feba6ee575482。日期邻近不证明精确构建匹配；发布者重分发包仍未被Valve签名独立认证。
- 直接取得该Valve Wine提交的winstation.c和ntdll/unix/virtual.c，原始API与解码源记录在`logs/proton-wine-source-alignment/`；未全仓克隆或编译，也未更换原件。
- winstation.c125-130以SECTION_MAP_READ/PAGE_READONLY请求会话section；176-189校验object id，失败输出已在运行时观测的同名警告。
- **重要精确化**：virtual.c2581-2604中，Linux只读section实际mmap请求为`PROT_READ|PROT_WRITE`加`MAP_PRIVATE`，而非简单PROT_READ。源码明确注释：POSIX不保证文件后续修改可见，但Linux可见所以利用它；非Linux分支才使用MAP_SHARED并去掉WRITE。
- 因此单纯RO-private最小测试及hostRO/HV_READ admission只能作为能力旁证，不能等同Wine该实际mmap参数；本轮补测Wine式O_RDONLY fd + RW-private，与server RW-shared同文件。
- Darwin与当前elfuse均先读0，server写0x1234abcd后client仍0；client私写0xdeadbeef后server不变，server再写0x55667788后client保留私值且文件为server新值。结果：快照缺少后续可见性，但私写隔离成立。Linux ELF实际0.241372s、overall/target0、无timeout/cleanup；诊断exit0不等ABI已修。
- 新源码`probe_wine_rw.py` SHA 1784dd0fa4758d7b99b9dc44d7290a2dad3fef6ed12ac87429a640c094090d33；原始观测`logs/private-map-coherence/{darwin,linux}-wine-rw.json`与`run-ujh732rr`。当前团队成员来源审查恢复再次失败，本轮只读对齐和单点探针缺独立复验，未另起执行会话。
- 下一步不是把MAP_PRIVATE改成共享：须观察实际Wine的fd access/offset/flags并保留首次私写后的隔离。实现Linux页缓存式别名/COW需要单独派生runtime与对应RED→GREEN；本轮未改runtime/Wine/Proton。
