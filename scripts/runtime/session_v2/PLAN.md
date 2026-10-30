# session_v2 实现计划

目标：按 Lead 已批准规格交付隔离回归入口。标准库，当前新目录隔离，无 git。

- [ ] tests/session_v2/test_runner.py：CLI真实子进程负测，先执行 `python3 -I tests/session_v2/test_runner.py`，确认缺入口红灯。每轮测试UUID目录，sentinel独立会话，finally回收。
- [ ] scripts/runtime/session_v2/run.py：父监督器唯一receipt writer，worker session leader保留至清理后回收，先握手登记PID/PGID/ps身份再发GO执行。worker独立events.jsonl；父独立events.jsonl。两个timeout单独字段；fixture明确允许outer短预算。
- [ ] 覆盖exit0/7、拒绝覆盖、inner timeout、fixture停止worker触发outer timeout、启动异常、父SIGTERM、孤儿后代、忽略TERM、环境/SHA与清理PID。运行同一测试命令保存新日志，失败时先加载debug技能并调查，每假设最多两轮。
- [ ] reviewer独立复跑、检查清理、baseline证据SHA未变。通过后才另审真实runtime同PE/预算命令。
- [ ] 新logs/session-v2封存命令退出、SHA、未测项并交Lead；不将自检视为review通过。
