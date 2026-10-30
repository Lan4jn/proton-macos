# Round 3 独立候选预备分析：FEX Unix 运行时动态库依赖预算与规划规格 (待命)

## 1. 规范与隔离边界声明
- **当前状态**：严格处于**静态预备与分析阶段**，当前**不混入**正在进行的 `sortdefault.nls` 单文件假说试验；
- **文件与代码边界**：
  - 绝对不修改已冻结的 `scripts/runtime/session_v2_round2/wine_launcher.py` 内部 `REQUIRED_ARCH_LIBS` 常量；
  - 待后续 `sortdefault` 实测判定并由 Lead 批准后，若需测试 FEX 依赖，仅在 `wine_init_round3` 专属目录下通过独立包装器在 setup 完成后进行 copy 物化。

---

## 2. FEX `libarm64ecfex.so` DT_NEEDED 依赖库清单与实际物理预算

经静态核查，`sources/proton-v3-deploy/original/files/lib/wine/aarch64-unix/libarm64ecfex.so` 缺失的底层 Unix 支持库在 `fixtures/runtime/arch-root/usr/lib/` 内部均完好存在。其物理路径、精确大小与 SHA256 哈希如下：

| 库文件名称 | 源物理路径 (在 arch-root 内) | 部署目标路径 (在 target_root 内) | 真实物理字节 | SHA256 哈希 |
|---|---|---|---|---|
| `libstdc++.so.6` (`.0.35`) | `fixtures/runtime/arch-root/usr/lib/libstdc++.so.6.0.35` | `usr/lib/libstdc++.so.6` 及 `libstdc++.so.6.0.35` | 3,017,768 字节 (~2.88 MiB) | `abdf011833740a6f0ca1654876f18d9a5911a9ad08806a38d015e60e3e516ab8` |
| `libm.so.6` | `fixtures/runtime/arch-root/usr/lib/libm.so.6` | `usr/lib/libm.so.6` | 788,960 字节 (~770 KiB) | `71ed8de709c40acd4fd0177258fc71251a5acdb1d075122409ad42529d6c7a4e` |
| `libgcc_s.so.1` | `fixtures/runtime/arch-root/usr/lib/libgcc_s.so.1` | `usr/lib/libgcc_s.so.1` | 133,352 字节 (~130 KiB) | `ac598673a4bf67c0295b6609e46b1fafd0d4adf3f80a513d61ac49ecff772e48` |

- **总增量预算**：3 项依赖库物理总大小恰好为 **3,940,080 字节 (~3.76 MiB)**；
- **依存关系解析**：
  - `libarm64ecfex.so` 直接依赖 `libstdc++.so.6`；
  - `libstdc++.so.6` 递归依赖 `libm.so.6` 与 `libgcc_s.so.1`；
  - 该 3 库加入后，FEX Unix 动态链接闭包将在现有 glibc（已物化的 libc 与 ld-linux）基础上实现完全自洽闭环。

---

## 3. 当前准入状态
- 本文档仅作为静态候选技术规划落盘归档，**当前不执行、不实现代码、不申请锁**；
- 保持当前工作焦点严格停留在已编制好的 `sortdefault.nls` 单文件假说上，静候审查员与 Lead 决策。
