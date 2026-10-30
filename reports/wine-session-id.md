# Wine共享会话对象ID的单次有界观察（round11）

本项为L1既有探针的单一日志配置观察，不写新执行模块、不改Wine/运行时，不启动图形负载。

- 新前缀由task56 COW克隆；冻结06a2fceb...runtime，原生ARM64 `probe-1.exe`，noDISPLAY/noPreload，与56受控环境相同，仅增加`+winstation`（连同timestamp/loaddll/seh）。实际只运行一次。
- `logs/wine-session-id/run-ibzwehco`：39.236609s，overall/target38，timed_out=false，cleanup_errors=[]；stdout确认user32加载返回、GetDpiForSystem返回96。
- 发现14条精确`warn:winstation:find_shared_session_object Session object id doesn't match expected id ...`，前例来自0068期望id1/2/3、00ac期望id4/5、002c期望id6。
- 本次收集的session诊断全部是id mismatch；没有记录到所筛选的open/map/initial-map错误。该负面观察不泛化为所有NtMapView状态已经验证。
- 实际对象内存id值尚未直接读取；不能把ABI探针的0直接套到Wine对象。版本Wine11.0源的同名函数在find_shared_session_block成功后比较object id，但包的精确Wine提交仍未认证。
- 这比原先通用desktop失败更精确：live阻断链含会话对象ID不匹配，且最小ABI独立复现private RO快照不更新。仍须派生runtime RED→GREEN与原包同条件复测，才可判定因果修复成立。
- 简单放开MAP_PRIVATE overlay是不完整方案：HVF当前强制host RW MAP_SHARED，private写隔离、mprotect加WRITE前COW、munmap/MAP_FIXED清除overlay都需元数据与回归测试；默认原runtime维持冻结。

结构化原始结果与完整14条诊断：`logs/wine-session-id/result.json`。未声称已通过Windows Vulkan或真实游戏。
