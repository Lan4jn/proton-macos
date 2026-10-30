# 快速隔离 clear-env 与 Wine 早期空指针失败报告 (task-50 修正版)

## 一、 四组探针实测数据 (Runtime: 06a2fceb... | ABSOCK_BASE: lab/.s)
1. **Case A1 (`/bin/sh -c true` + `--clear-env`)**: Exit 0 (0.18s)，shell 控制端正常。
2. **Case A2 (`wine --version` + `--clear-env` + 完整 LD 路径)**: Exit 139 (0.16s)，重现 task-48: `EL0 data fault at 0x0 PC=0x2000e1248 (SIGSEGV/MAPERR)`.
3. **Case B1 (`/bin/sh -c true` + `clean_env` allowlist)**: Exit 0 (0.16s)，控制端正常。
4. **Case B2 (`wine --version` + `clean_env` allowlist + 完整 LD 路径)**: Exit 0 (0.17s)，成功输出 `wine-11.0`。

## 二、 物理符号与环境边界确证
- **PC 映射事实 (llvm-readelf)**: 段 `[12] .fini 0x1248 (size 0x18)`，符号 `_fini = 0x1248 (FUNC GLOBAL HIDDEN)`。PC `0x2000e1248` 为基址 `0x2000e0000` + `.fini` 入口，属于符号入口粗标签，具体函数逻辑因缺调试符号记为 UNKNOWN，不推定为析构调用。
- **环境 Profile 关联**: 恢复包含 `HOME/PATH/LANG/TMPDIR/XDG_*` 的受控环境后 139 崩溃消失，属于多变量 Profile 联合变化，不单独归因于 `HOME`。
- **task-52 可用 B2 配置**: `sources/elfuse-socket-derived` (`06a2...`) + `ELFUSE_ABSOCK_BASE=lab/.s` + `clean_env` allowlist + `/bin/sh -c 'export LD_LIBRARY_PATH=...; exec wine ...'`。

## 三、 产物路径
- 探针脚本: `scripts/runtime/early_env_probe/run_probe.py`
- 结果数据: `logs/early-env-probe/early_env_probe_results.json`
