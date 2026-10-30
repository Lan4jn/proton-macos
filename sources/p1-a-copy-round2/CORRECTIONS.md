# P1 A-copy 第二轮：审计与修正补记 (CORRECTIONS)

## 1. 关于 r2-latest-01 数值笔误的修正与证据链路

- **问题现象**：在首版汇报及 `REPORT.md` (Line 42) 中，曾将 `r2-latest-01` 的结果写为 `displayed: 9, replaced: 91`；而 reviewer 独立核对磁盘文件时发现实际内容为 `displayed: 3, replaced: 97`。
- **证据核实**：
  1. 在 `r2-latest-01` 运行完成并发生 `r2-resize-01` 失败后，我于当期会话中首次执行 `shasum -a 256` 冻结相关产物，计算并通报给 reviewer 的哈希指纹为：
     - `logs/p1-a-copy-round2/r2-latest-01/receipt.json`: `f2888d1b71a40f217b9413d5746a636e326df12ee295e6893f940b0c106563c6`
     - `logs/p1-a-copy-round2/r2-latest-01/work/result.json`: `9c57dce848fe6eb3e83e33fe1c9ff5bd49cd8d26a2a1a918ea51c95b54362779`
  2. 此时（第二次审计核对），再次计算磁盘该文件的哈希值，结果完全相同：
     - `9c57dce848fe6eb3e83e33fe1c9ff5bd49cd8d26a2a1a918ea51c95b54362779  logs/p1-a-copy-round2/r2-latest-01/work/result.json`
  3. 读取该文件的实际内容：顶层字段确为 `"displayed": 3`，`"replaced"` 数组确由 97 个帧序号组成。
- **结论与更正**：
  - 当前artifact hash与先前声明值一致；当前字节验收，历史生成阶段未覆盖未知；
  - 冲突系汇报与撰写报告时的文案笔误（倒置并误记为 9/91）；
  - [`REPORT.md`](<REPORT.md>) 正文中的文字描述已更正为与磁盘客观记录一致的 `displayed: 3, replaced: 97`；
  - 旧 run 目录保持冻结，不再进行任何写入或修改；涉及文件参见 [`receipt.json`](<../../logs/p1-a-copy-round2/r2-latest-01/receipt.json>) 与 [`result.json`](<../../logs/p1-a-copy-round2/r2-latest-01/work/result.json>)。
