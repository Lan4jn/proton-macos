# 隔离后端与可逆 Steam 接入准备

## 已实现部分

- `scripts/backend/bundle.py`：关键文件摘要核验、明确来源置信度、Wine 组件诊断或完整 Proton 计划、lab 内路径约束、离线 Steam probe 包准备。
- `scripts/backend/process.py`：独立日志目录与 HOME/TMPDIR/XDG、清理父环境、不通过 shell 执行 argv、会话进程组、超时、stdout/stderr 与真实退出码记录。
- `scripts/backend/cli.py`：默认只生成计划，`--execute` 才启动子进程。Wine 组件诊断与 Proton Python launcher 明确分开。
- `tests/backend`：初版16项，进程身份/顽固后代/异常持久化返工后27项。Lead独立复跑27PASS：`logs/lead-backend-review/current-suite.log`；审查员27PASS及黑盒见`logs/continuation-review/backend_test_final_caught.log`。初版及返工红灯保留，不把最初自测绿色当作未发现缺陷的证明。

这些路径和环境隔离不是 OS 级文件访问沙箱；guest 路径缺失时 elfuse 仍有 host fallback。它没有把外来二进制隔离成只能访问 lab 的系统安全容器。

## 真实执行与计划分别验证

```sh
# 默认仅生成 Wine 诊断计划，不启动二进制
python3 -m scripts.backend.cli --engine wine -- --version

# 显式执行原包的 Wine 组件版本查询
python3 -m scripts.backend.cli --engine wine --execute -- --version

# 完整 Proton 路径需要显式提供 Linux Python，不能替换为 host macOS Python
python3 -m scripts.backend.cli --engine proton \
  --sysroot fixtures/runtime/arch-case \
  --linux-python fixtures/runtime/arch-case/usr/bin/python3 \
  --runtime-bundle fixtures/runtime/proton-derived \
  -- run fixtures/runtime/pe/hello-x64.exe
```

最后一个命令仍是计划；并不表示 Windows 程序已经成功。完整 Proton 的实际尝试由独立 runner 留存于 `logs/runtime/run-mbf_0zq4`，超时而非通过。

`logs/backend/wine-version-executed.json` 记录组件执行 exit0；对应 run 目录的 stdout 是 `wine-11.0`。这个结果不是“Proton 游戏后端完成”。

## Steam 离线候选

初版候选 `artifacts/steam-prepared/continuation-probe` 保留为历史产物；返工后的候选重新生成到 `artifacts/steam-prepared/reviewed-probe`，包含 compatibilitytool/toolmanifest、修复后的 probe wrapper、独立 probe-logs 与 `install-plan.json`。候选 commandline 包含 `-- %verb%`，wrapper 自带边界保护，由端到端测试确认带/不带分隔符时都保留 verb、中文/空格和游戏参数，不吞掉游戏的 `--log-dir`。新prepare实测exit0且目标仍不存在，`applied=false`，见 `logs/lead-round3/prepared-reviewed.json`。

准备时目标故意指向 lab 下 `artifacts/steam-prepared/not-installed/compatibilitytools.d`，仅记录目标，没有安装动作。probe 本身只记录，不启动游戏。没有获得当前 macOS Steam “发现→可选→原条目 Play 调用”证据，也没有 Steamworks bridge 运行证据。常见 `/Applications/Steam.app` 与用户 Applications 路径的只读检查均未发现应用；这不宣称全盘不存在 Steam。

## 清理与当前限制

历史runner在回收root后盲目killpg有身份复用风险；第一次supervisor返工又被Lead真实黑盒抓到忽略TERM目标泄漏（`logs/lead-backend-review/timeout-ignore-term.json`）。最终使用整个生命周期的捕获型TERM handler，避免child exec继承SIG_IGN；supervisor存活时清理同组后代，再回收。Lead同症状黑盒复跑目标实际不存在（`timeout-ignore-term-recheck.json`），审查员独立复验后批准。超时overall exit124，无法确认真实target退出时记null；异常记录持久化，不能返回假成功。明确边界：主动setsid脱离组的进程不在组清理保障内，不扫描/误杀无关用户进程。历史EPERM具体成因仍未证实，不将PID复用当作既定事实。详见`reports/backend.md`及`reports/continuation-review.md`。

后端仅核验 manifest 内关键文件，不声称对解压树所有文件完成 Steam depot 级验证。真实 Steam 安装、账号与全局环境持续不改；未 commit/push。
