# Task-136 只读节适配设计（待 Lead 批准）

## 范围与原理
基于 adea6cbac 的独立 Wine 树，仅修改 dlls/ntdll/unix/virtual.c:map_file_into_view 中不含 VPROT_WRITE 且不含 VPROT_WRITECOPY 的 else 分支。建议复用现有非 Linux 分支 MAP_SHARED，并移除宿主 mmap 的 PROT_WRITE；读写与写拷贝分支保持原样。这个范围覆盖该 helper 的只读文件 section 视图，尚未精确缩小到已证具名会话节，需 Lead 明确批准这一边界。不得使用文件长度或 inode 签名替代权限语义。

## 权限论证与限制
源码当前先判断 VPROT_WRITE，再判断 VPROT_WRITECOPY，else 为无这两种写语义的视图；代码也已有非 Linux MAP_SHARED+只读策略，具有先例。初始 mmap 只读不等于整个生命周期永远只读：后续 mprotect/NtProtectVirtualMemory 以及 pread fallback 都需验证。fallback 当前 mprotect RW + pread，不应声称该分支已保证实时共享或永久禁写。若测试发现后续升权导致私写泄漏或依赖私写，停止并报告，不静默开放写权限、不叠加第二处补丁。

## 先测试、后补丁
1. 保存旧日志，补录 task134 收据：stdout 含 Step3 行，准确描述为进入 vkCreateInstance 后无完成标记。旧 gate-off 无 result.json，exit/cleanup 标为未完整留存，不将脚本 timeout=115 当作已保存的精确实测退出码。
2. 独立运行权限回归：READONLY section 读取、子进程写入触发预期 fault；WRITECOPY 私写不回写且不污染兄弟视图；正常 READWRITE shared 跨进程可见。后续保护变化单独记录。
3. pristine/patch diff 仅该 else 分支；复用既有 cross wrapper/host tools，生成必要头部，只构建 ntdll.so；保存依赖、SONAME、导出符号差异。
4. 安装目标 wrapper 独立前缀运行，源部署目录移开，ELFUSE_DIAG_SESSION_SHARED 从 host/env/config 中真正删除（getenv 对字符串0也触发）；保持 shipped Unix/PE winevulkan 配对和 win32u SHA59a76b05 不变。先枚举，再核对 SHA112377ef 的离屏PE与8点输出，单次运行上限115s，使用受控 owned process group，禁止 killall。
5. COW probe gate-off 完整 raw/argv/sysroot/SHA；两种 probe 的负对照分开判定，不把普通小文件测试作为0x144000门控测试。

## 备选与取舍
elfuse 按 unlinked/长度白名单强制共享会改变原始 MAP_PRIVATE 写语义，即使仅一个文件也不构成 COW 修复，不作为首选。Wine 只读权限适配保留 elfuse 和 winevulkan 原版，但 ntdll 已派生，需诚实标注；成功仅说明此配置的只读 section 兼容，不证明通用 Linux page-cache COW 完备。

## 停止条件
ntdll Unix/PE 不匹配、首个新模块错误、只读升权泄漏或回归失败均停止，不添加布局或额外模块修补。未达验收逐项 FALSE/UNKNOWN，未实现前不宣称修复。

## 执行记录：先行反证及获批修订的 RED / GREEN（尚未部署）

设计边界已批准为整个只读 helper 分支。第一轮泄漏触发停止，随后 Lead 明确批准补充 WRITECOPY 脱共享语义。以下不是生产修复完成声明。

### 旧对照收据补正
- logs/ro-section/gate_off_result.json 独立补录；旧 raw 不变。stdout 为486 bytes，SHA256 cc1c891090e2d61fb52d57eafc13698c01524db182e399ab5472ae21de1f9d3a。
- 准确观察：stdout含Step3行且无完成标记。原result缺失，duration_seconds/exit_code=null，cleanup=UNKNOWN。未将脚本timeout=115写成实测时长或退出码。
- gate_on_result.json 为原收据副本，不重写旧证据。

### 测试边界与复现
- prepare_permission_probe.py 从adea6cbac pristine的virtual.c提取真实map_file_into_view与get_unix_prot，构建Linux AArch64 ELF权限回归。没有完整派生Wine树或新ntdll.so。
- 这是get_unix_prot+mprotect的Unix边界测试，不是PE调用NtProtectVirtualMemory的端到端测试。生产set_protection→set_vprot→mprotect_range路径已读，真实PE回归仍UNKNOWN。
- 编译命令：sources/wine-v3-vulkan-build/wrappers/aarch64-linux-gnu-gcc -O0 -g TEST.c -o TEST。
- runner：python3 scripts/runtime/ro_section/run_permission_probe.py LABEL。拒绝覆盖已有result；删除host诊断门，不注入guest门；start_new_session=True，仅清理owned process group；guest15s/host20s上限。

### 第一轮（证据原样保留）
| 用例 | baseline | 只读共享候选 |
|---|---|---|
| 初始WRITECOPY隔离 | PASS | PASS |
| 初始READWRITE共享 | PASS | PASS |
| READONLY读取 / 子进程直接写fault | PASS / PASS | PASS / PASS |
| READONLY后续文件更新可见 | FAIL（预期RED） | PASS |
| offset=1触发原RW+pread fallback / fallback升权私写隔离 | PASS / PASS | PASS / PASS |
| RO→WRITECOPY私写不污染backing/sibling | PASS | FAIL |
| exit | 1 | 42 |

候选升权写0x7a后backing/sibling均为0x7a，预期0x42。立即停止，当时未修改生产Wine、未构建ntdll、未部署。

### Lead修订的边界 RED→GREEN
- prepare_detach_probe.py生成detach_red.c / detach_green.c，diff在logs/ro-section/detach-boundary.patch。
- RED仍未脱共享：0.059s、exit42；LIVE_UPDATE/WRITE共享/fallback均PASS，WC隔离FAIL。
- GREEN仅当 shared && WRITECOPY && !WRITE 时先 mmap(base,size,PROT_READ,MAP_FIXED|MAP_PRIVATE,fd,offset)，成功后标记detached，再执行请求权限对应mprotect。重映射自身不额外赋写；WRITE不重映射。
- GREEN实测0.054s、exit0：全部PASS；WC私有写0x7a后backing/sibling保持0x42。初始WRITECOPY、READWRITE、RO读取/写fault、LIVE_UPDATE、fallback、RO→WRITE仍共享均PASS。

### 首轮观测限制
approved_candidate.stderr.log中的只读测试范围：size=4096，offset=0/1，unlinked=1，prot=1，vprot=0x21，caller为测试内部地址。其他prot=3/vprot=0x29或0x23记录对应未改变的初始WC/WRITE分支，日志前缀不代表它们也进入RO分支。
这些是测试fixture，非Wine真实会话。0x144000归因仍UNKNOWN；生产观测还需明确真实目标节mmap成功而非fallback。

### 生产落地尚需实现
file_view当前仅base/size/protect，无fd/offset/共享状态。需要在同一virtual.c跟踪成功共享只读mmap的真实范围、独立持有fd和offset、逐页detached状态；仅对WC请求重叠未脱共享页重映射，避免重复升权覆盖私有写。需处理部分范围、fd/视图销毁/占位符复用生命周期及失败不默许写。fallback不登记为共享映射。当前边界测试显式传入元数据，不等于生产跟踪已实现。

### 当前分层状态
| 层次 | 状态 | 依据 |
|---|---|---|
| 原单RO分支方案生命周期隔离 | FALSE | exit42反证 |
| 修订边界RO实时可见 | TRUE | detach_green |
| 修订边界WC隔离 | TRUE | backing/sibling=0x42 |
| 修订边界WRITE共享 | TRUE | READONLY_TO_WRITE_STILL_SHARED=PASS |
| 提取helper的fallback回归 | TRUE | 两项PASS |
| 生产NtProtect PE回归 | UNKNOWN | 尚未执行 |
| 新ntdll构建/ABI比较 | UNKNOWN | 尚未构建 |
| 安装/adapter/gate-off枚举 | UNKNOWN | 尚未部署 |
| gate-off离屏8点 | UNKNOWN | 尚未执行 |
| 完整probe_cow_semantics | UNKNOWN | 本轮未执行 |
| 真实会话mmap/fallback/0x144000归因 | UNKNOWN | 当前仅fixture |
| 回滚指纹 | UNKNOWN | 未安装，无回滚动作 |

## 最新检查点：production-source unit RED / 候选未达 GREEN，按条件停止

本节覆盖前文“生产尚未实现”的时序状态；旧边界detach_green仍仅为测试夹具结果，detach-boundary.patch不是生产补丁。生产补丁现在单独保存为logs/ro-section/production.patch。

### 阶段A同源真实翻译单元
- 被测文件：sources/wine-ro-section-adapt/wine/dlls/ntdll/unix/virtual.c。production_unit.c直接#include完整该文件，没有提取/复制map_file_into_view/set_protection/新增跟踪函数。后续若获准构建ntdll，使用同一源文件。
- build_production_unit.py从现有compile_commands继承Wine头文件/宏/编译链，链接--gc-sections去掉测试不可达函数。
- 仅有两个stub：__wine_dbg_header返回0；__wine_dbg_output将日志写stderr。它们只是Wine日志桥接，不能证明真实Wine日志初始化；映射、保护换算、set_protection/set_vprot/mprotect_range均非stub。
- 测试自建file_view并初始化页保护表；虚拟内存树、wineserver、PE syscall前端未执行，真实PE NtProtect仍UNKNOWN。
- 编译有现有uffd宏重定义、现有pointer/qualifier及测试声明顺序warning，完整保存在build.log；不宣称零warning。

### 生产RED
- 仅RO else共享策略，调用真实map_file_into_view与set_protection：production_red exit42，failures=3。
- RO实时更新/邻页更新/WRITE共享PASS；WRITECOPY backing与sibling隔离FAIL；降权写fault本身PASS但先前污染文件使FAULT_PRESERVES_FILE失败。
- 归档：production_red.virtual.c、production_red.stdout/stderr/result/build。

### 生产候选实现（尚未验收）
- 只改变virtual.c中的只读文件映射及其权限生命周期语义。全局按地址范围跟踪成功共享RO mmap，保存dup fd和逐宿主页0共享/1脱共享/2已移除状态；读写、初始WRITECOPY、匿名映射不登记。
- dup保留调用者fd关闭/unlink后的独立引用，设置CLOEXEC；dup/设置失败时fd=-1，并记录dup_failed_copy_on_upgrade；没有假装保留成功。
- WC且非WRITE请求仅对重叠未脱共享页先以PROT_READ+MAP_PRIVATE重映射；WRITE不脱共享；已脱共享页重复升权不重建，降权保留其私有内容。
- 无fd的copy策略记录no_fd_copy_begin；复制现有页到暂存，匿名私有MAP_FIXED重建、写回后降至READ，再执行正常请求权限。异常返回错误、记录detach_failed；该路径目前未实跑验证，不能宣称正确。
- 地址范围清理接unmap_area及placeholder恢复，全部记录移除后关闭dup fd。fd销毁/失败注入的完整可证伪回归尚未执行，状态UNKNOWN。
- 计数固定为tracked_ranges / detached_via_fd / detached_via_copy / detach_failed，事件都带base/size/offset/fd/pid；tracked_ranges为当前存活范围数，其余为累计计数。

### 生产候选结果：并非GREEN
production_green与仅加观测值的production_observe均exit42、failures=2。后者实测0.079s。
| 用例 | 结果 |
|---|---|
| RO文件更新实时可见 | PASS |
| WC升权私写不污染backing/sibling | PASS |
| 重复WC升权保留private数据 | PASS |
| 降RO保留private数据 | PASS |
| 降RO后写fault且文件不改变 | PASS |
| 未脱共享邻页继续实时文件更新 | **FAIL** |
| 未脱共享邻页WRITE升权保持共享 | **FAIL** |

production_observe实际邻页读0x00（期望0x61）；写0x62后backing/sibling仍0x61。生产stderr实际仅对中间4KiB执行一次detach_fd：tracked_ranges=1、detached_via_fd=1、detached_via_copy=0、detach_failed=0。没有把邻页误标成detached。

### 关联根因证据与停止
宿主getconf PAGESIZE=16384；只读elfuse源码mem.c:cleanup_overlays_in_range先按宿主页向外对齐，MAP_FIXED路径调用它后拆除共享overlay。4KiB脱共享影响同一16KiB邻页的实测与该路径一致。这是源码关联解释，尚未修改runtime做因果对照，不声称已完整修复根因。
依照Lead停止条件：未继续修elfuse，未扩大Wine脱共享范围，未构建或部署ntdll，未做第二模块补丁。证据保留。

### 分层验收（最新）
| 项目 | 状态 |
|---|---|
| 历史收据补正及保留旧raw | TRUE |
| production-source unit RED真实触发 | TRUE |
| production-source unit候选全部GREEN | FALSE |
| 只读共享可见与WC本页隔离 | TRUE（仅阶段A） |
| 邻页共享实时可见/WRITE共享 | FALSE |
| 末页不足一页/部分页完整矩阵 | UNKNOWN（中间整页已测失败） |
| dup关闭/dup失败copy/无fdcopy/失败计数注入 | UNKNOWN |
| 同源候选fallback全回归 | UNKNOWN（先前提取边界PASS不替代） |
| ntdll构建与ABI比较 | UNKNOWN（未执行） |
| 安装/adapter/gate-off枚举/离屏/COW | UNKNOWN（未执行） |
| 0x144000实际会话归因与真实PE NtProtect | UNKNOWN |
| 回滚指纹 | UNKNOWN（未安装） |

最小后续建议：另行批准并测试runtime的局部4KiB MAP_FIXED共享overlay邻页保留，或能维持子页独立语义的backing策略。不能通过把整个16KiB强行脱共享掩盖，因为那会违反邻页继续共享可见验收。

## 最终归档：BLOCKED（Lead确认，等待后续方向）

阻塞条件：需要elfuse提供4KiB粒度overlay保真，或fault级COW；否则该Wine适配方案在当前运行时不可实施。

Lead已独立核验宿主16KiB与guest4KiB硬冲突：cleanup_overlays_in_range按16KiB向外对齐，4KiB MAP_FIXED会连带清理同宿主页的邻页overlay；macOS mmap不能在16KiB宿主页内直接建立独立4KiB私有子页。因此当前失败归类为运行时能力缺失，而非本次Wine逐4KiB脱共享跟踪逻辑错误。
Wine侧已测4KiB单元内自洽：WC隔离、重复升权、降权保留私有数据、降权写fault、文件不变均PASS；未脱共享邻页实时共享及WRITE共享FAIL，导致整体production-source unit exit42。

保留production_observe完整raw、result与build log，保留production.patch SHA256 27bb2c82502ac75517bfc900cc6c026e60d201cc3eabefeb7e901a6e3ef4dccf。未构建ntdll，未部署新模块；不扩大Wine脱共享至16KiB，不改变guest页大小，不以整页私有掩盖邻页共享丢失。

以下未完成项保持UNKNOWN：dup失败回落、无fd复制路径、末页不足一页完整矩阵、真实PE NtProtect、ntdll构建及ABI比较、安装与部署、gate-off图形验收。实际0x144000节归因仍UNKNOWN。
既有gate_on诊断配置及task135已验收CPU离屏绘制产物保持原样，继续是当前可用配置；本轮未重跑，不把旧成功写成本轮验证。
