# P1 A-copy 第二轮：增量场景 (scenario_extra.py) 规格与差异说明

## 1. 目标与范围
- 在已有 4 底座（`runner.py`, `roles.py`, `deadline_io.py`, `wire.py`）及已冻结收据（`r2-correctness-01`, `r2-throughput-01`）完全不变的前提下，通过独立新文件 `scripts/p1_a_copy_round2/scenario_extra.py` 覆盖余下子场景：
  1. `latest`: 高频推帧产生 replaced 终态；
  2. `resize`: generation 递增后旧 gen 失效与新 gen 绘制；
  3. `busy`: producer 原生 3s 纯算期间 host AppKit 自定义事件在预排窗口被处理；
  4. `busy-close`: 3s 纯算期间 host 响应并处理窗口关闭事件，producer 观察到关闭断开；
  5. `disconnect`: 正常断连清理。

## 2. 架构设计与底座复用
- 严格遵循单一 P0 进程组架构：通过 `roles.spawn('host', ...)` 继承同一 PGID，不创建新 session；
- 继承单调非阻塞 deadline I/O；
- 校验每一帧 ACK 的身份 (`v=1, sid=1, gen, seq, slot in (0, 1), crc32`) 及 disposition；
- 严格绑定固定 host binary (`b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb`)，支持 `--fixture-host` 仅用于受控单元测试。
