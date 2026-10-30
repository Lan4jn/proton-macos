# 文件只读私有映射更新可见性（task58 / round11）

- 成员会话连续失败后本卡有限兜底；新路由独立成员尝试受当前8成员上限阻断，未取得独立复核。
- 脚本`probe.py` SHA `5f8511bb17e23acd90d8b78142574d9dae0febb2cb5f9227f8d792d005091c06`；7个分类器单元测试通过，日志`logs/private-map-coherence/unit-tests.log`。
- 同一个O_RDWR文件、65536字节、offset0：共享RW、私有RO、共享RO三映射均先读取为0，再从共享RW写入`0x1234abcd`；无sleep、无Wine、无大图形负载。
- Darwin原生Python：共享RW/RO与pread文件值均305441741，私有RO仍0，fsync后仍0，unmap无错误。`darwin.json`。
- Linux Python经冻结06a2fceb...elfuse：相同结果，分类`PRIVATE_STALE_BUT_SHARED_OK`；实际overall/target0，0.229729s，无timeout/cleanup错误。`linux.json`、`run-j4iwzthx`。
- 这里exit0表示诊断完成，不是全部Linux ABI语义通过。Darwin结果不替代真正Linux内核基线；POSIX对该情况下的私有映射更新可见性不作相同保证。
- 当前elfuse `mem.c3505-3533`只对MAP_SHARED+可写fd+host页对齐文件映射作overlay，其余pread快照；本次实际观测与该分支一致。
- 经GitHub API取得版本标签wine-11.0的源码：winstation.c106-143以SECTION_MAP_READ/PAGE_READONLY映射`\\KernelObjects\\__wine_session`；176-189检查locator id与内存object id，不相等返回NULL；class.c572起因此销毁class并报所见错误。
- 这些版本源码与公开Proton包的精确Wine commit尚未认证；它们支持具体可验证候选，不证明当前Wine desktop失败根因已经锁定。下一最小实测应开+winstation确认live id mismatch或NtMapView失败，不先假设映射已成功。
- 不宜直接把所有private映射变为共享：写入隔离、mprotect加WRITE前COW、munmap/覆盖/置零不误写文件、只读fd和16KiB host页边界都须独立测试；本卡未修改运行时。

版本源码记录：`logs/private-map-coherence/{class.c,ntuser_private.h,winstation.c,sysparams.c}.wine-11.0.txt`。来源API：`https://api.github.com/repos/wine-mirror/wine/contents/dlls/win32u/winstation.c?ref=wine-11.0`；外部相关案例 https://github.com/rr-debugger/rr/issues/3972 仅作线索。
