# P0 session_v2 最小规格（待 Lead 审核）

## 目标和隔离
仅新增 scripts/runtime/session_v2、tests/session_v2、logs/session-v2。Python 标准库 runner，不调用旧入口、不修改原 runtime/Wine/真实 Steam/全局包。fixture 先行，真实 runtime 基线须独立 reviewer 先验收清理机制。

## 方案
推荐独立 Python 监督器 + start_new_session 进程组：无需依赖，PID/PGID 所有权清楚。备选逐 PID 遍历易漏后代；容器隔离会改变真实 runtime 环境且超出范围。

## 最小接口
`python3 -I scripts/runtime/session_v2/run.py --run-id ID --timeout SECONDS --outer-timeout SECONDS --module ROLE=PATH [--env KEY=VALUE] -- COMMAND ARG...`
- run-id 仅 ASCII 字母数字/下划线/连字符；在固定 logs/session-v2 下以 mkdir(exist_ok=False) 分配，重复 ID 退出 2，原目录逐字节保留。
- prefix 自动新建为 run/prefix；cwd 为 run/work；HOME/TMPDIR 为 run 独立目录。环境仅最小 PATH/LANG 与显式参数；不继承 ELFUSE opt-in。
- 父监督器实施外层预算；内层 worker 实施 target timeout。worker 在独立 session 启动后先握手，父记录 PID/PGID/ps lstart 身份后才发 GO 执行 payload；父唯一写最终 receipt。worker 结果/事件分开文件，父事件单独文件，不竞争覆盖。正常预算要求 outer > inner + 2s；仅显式 --fixture-short-outer 允许测试更短 outer。
- worker 保持 session leader 存活至父清理，不提前 reap，保留 PID/PGID 身份；每次发信号前枚举组内 PID 并重核 leader identity。清理记录枚举 PID、PGID、身份、信号及结果；最终 live 状态不含已退出 zombie。
- 所有 target 用 start_new_session，记录 PID=PGID；所有正常退出/超时/信号/启动异常均 TERM→有界等待→KILL owned PGID。无 killall、无按名称杀进程。
- receipt 分开记录 target_exit、runner_exit、inner_timed_out、outer_timed_out、异常、命令、显式环境、绝对 prefix/cwd、配置、模块完整 SHA256、stdout/stderr SHA256、cleanup 对象/信号/结果。对已退出无残留组记录 absent，不假称发出信号成功代表清理已证。
- 目标非零退出保留原 target_exit，runner_exit=1；内层超时=124，外层超时=125，runner异常=70，SIGINT/SIGTERM=128+signum。

## 验收
TDD 首轮先证明 runner 尚缺失，随后真实 fixture subprocess 覆盖：无关 sentinel 存活；重复目录不覆盖；target exit 0/7；内层超时；外层 watchdog 超时；runner 异常/信号；忽略 TERM 的子进程和父进程先退出的后代均清理；启动失败收据；stdout/stderr 与模块 SHA；无 opt-in 继承。每次测试唯一 logs/session-v2/test-UUID，不改旧证据。

## 真实基线门
reviewer 通过上述清理路径后，另拟最小原 runtime/C 派生无 opt-in 比较命令；同一 PE、相同配置/负载/预算，独立 prefix，记录完整 runtime/PE/模块 SHA。若清理机制未验收，真实运行保持未测。逃逸 owned session 的自行 setsid/double-fork daemon 不在首版支持范围，检测/观测为未知；不将此 runner 宣称通用进程沙箱。
