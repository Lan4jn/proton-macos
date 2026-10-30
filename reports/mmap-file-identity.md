# 有界mmap文件身份观测（task60 / round18）

## 构建与验收范围
当前团队执行员恢复task ready失败，独立审查员恢复无closing失败；无新团队/执行会话。Lead对此定点诊断兜底，不把独立复核欠缺写成通过。

- 新目录sources/elfuse-map-observe-derived，原socket-derived及06a2fceb...二进制未变。逐文件核对src仅syscall/mem.c不同，patch记录logs/mmap-file-identity/observer.patch；新二进制SHA 3bd19d04c04568c7f6de8cd150e6c55ffac62a583e0eb0823ff0f4a4058d48d4。
- 初计划只重编mem.o，但make实际触发更多源重新编译，最终link/sign成功；不能声称只重编了一个对象。源码差异仍只有mem.c，build.log保留实际过程。
- helper在普通mmap两处host fd获取后，筛选非EXEC、regular且unlinked或MAP_SHARED的请求，记录hostPID/dev/inode/nlink、guest/hostfd、host F_GETFL&O_ACCMODE、prot/flags/addr/len/offset，不输出路径与内存内容。保留errno，单write有界行；envgate打开时每process image最多64观测+1cap行。高VA路径未覆盖，fork继承计数/exec重置，不能称整个进程树全局64行；stdio/fstat/fcntl/write有运行时扰动，非完全被动。
- 观察点早于map最终返回，phase=request不等成功，不能从记录推算返回地址或页面内容。env未设置不记录，不改flags/prot/映射实现。

## 最小控制
logs/mmap-file-identity/control-result.json/run-j1gt7vea：0.25181s/overall0/target0/noTimeout/cleanup[]。
精确创建的自有文件unlink后，sharedRW O_RDWR与privateRW O_RDONLY记录同dev/inode，两条请求；client仍快照，private写未污染server/file。验证logger字段和既有映射行为的有限控制，不是完整ABI回归。

## 一次实际Wine观察
logs/mmap-file-identity/wine-result.json/run-gg3q95rt：39.529472s/overall38/target38/noTimeout/cleanup[]，DPI96；14条session mismatch仍在。stderr8124B，未启用--verbose；不是与435MB旧trace逐事件等价。

wine-identities.json：23条记录、8个hostPID、4组dev/inode；没有cap标记。
- dev16777229/ino17175306：pid17136以access2(O_RDWR)、prot3、flags1(SHARED)、off0、len0x144000请求；pid17172/17189/17138/17134以同inode、同access2/prot3/off0/len0x144000、flags0x12(PRIVATE|FIXED)请求。该具体文件上生产者候选与消费者候选的访问模式均为O_RDWR，之前O_RDONLY微探针不等同此真实候选。
- dev16777229/ino17175305：0x1000的小型unlinked共享映射组，多进程同inode；不能只凭共享文件或访问模式称为会话文件。
- 另外两组readonly shared文件dev16777242/ino2991、2993仍有link，长度0xc000/0xd000，不据此认作session。

## 结论与后续
0x144000同inode的跨进程SHARED→PRIVATE链是更窄的共享会话候选，尚未与Wine section对象名、实际memory object id、server生产者修改直接绑定。实际fd O_RDWR意味着host overlay的readonlyfd障碍不适用于此候选，但仍不允许把PRIVATE改SHARED：必须保留首次私写隔离，验证stage1页保护及COW处理、覆盖/munmap防文件回写、fork/线程与失败回滚。下一步应先对候选inode的映射内字节和文件pread进行限定采样并遵循seqlock/并发未知，不改id或伪造成功。

原Proton/Wine/accepted runtime/Steam未修改、无commit/push。此诊断binary只适用于观测，不接入后端默认runtime选择。
